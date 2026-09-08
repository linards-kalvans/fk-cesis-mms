"""Querysets, totals and paging for the outstanding-invoice review page.

Reads Invoice Ninja sync state that the nightly sweeps and the per-record
push write; it never calls the provider itself.

Two deliberate shapes here, both the result of review findings:

- **"Overdue" has exactly one definition**, ``_overdue_q``. The kaveti tab
  filter, the per-row flag and the stat card's count are all derived from it.
  An earlier version wrote the rule once in SQL and once in the template, and
  they disagreed: a fully paid invoice with an old due date rendered as
  "kavēts" on the tabs that do not filter by payment status.
- **Totals describe the whole filtered set; only rows are paginated.** The
  stat strip reports money owed, so a figure that silently described page 1
  would understate it. Totals are therefore DB aggregates over the unpaged
  queryset, and never a sum of the rows on screen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import (
    BooleanField,
    Case,
    Count,
    DecimalField,
    Q,
    Sum,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.billing.models import BillingInvoice, PaymentStatus

PAGE_SIZE = 25

INVOICE_TABS: dict[str, str] = {
    "neapmaksati": "Neapmaksāti",
    "kaveti": "Kavēti",
    "daleji": "Daļēji apmaksāti",
    "kludas": "Sinhronizācijas kļūdas",
    "nav_izrakstiti": "Nav izrakstīti",
    "visi": "Visi",
}
DEFAULT_INVOICE_TAB = "neapmaksati"

# payment_status -> badge class. Never derive a CSS class straight from the DB
# enum: a new PaymentStatus member would render unstyled instead of failing.
PAYMENT_BADGE_CLASSES: dict[str, str] = {
    str(PaymentStatus.PAID): "badge--paid",
    str(PaymentStatus.PARTIAL): "badge--partial",
    str(PaymentStatus.UNPAID): "badge--unpaid",
}


_CENTS = Decimal("0.01")
_MONEY = DecimalField(max_digits=12, decimal_places=2)


def _money(value) -> Decimal:
    """Two-decimal money, independent of the database backend.

    SQLite's SUM() comes back without the scale a DecimalField carries, so an
    un-quantised aggregate renders as "30" locally and "30.00" on Postgres.
    Local dev and the test suite run on SQLite while CI and production run on
    Postgres, so anything money-shaped is quantised here rather than trusted
    to arrive formatted."""
    return (Decimal(value or 0)).quantize(_CENTS)


def normalize_invoice_tab(raw: str | None) -> str:
    return raw if raw in INVOICE_TABS else DEFAULT_INVOICE_TAB


def _overdue_q(today) -> Q:
    """The one definition of "overdue". A past due date is not enough on its
    own: a fully paid invoice with an old due date is not overdue.

    Everything that needs this rule derives it from here — the kaveti tab
    filter, the ``is_overdue`` annotation each row carries, and the stat
    card's count. Do not restate the comparison anywhere else, and never in a
    template."""
    return Q(due_date__lt=today) & ~Q(payment_status=PaymentStatus.PAID)


def invoice_queryset(tab: str):
    """Rows for one tab, annotated with ``is_overdue`` so the template reads a
    flag rather than re-deriving the rule."""
    today = timezone.localdate()
    base = (
        BillingInvoice.objects.filter(cancelled_at__isnull=True)
        .select_related(
            "billing_record",
            "billing_record__member",
            "billing_record__member__guardian",
            "billing_record__member__training_group",
        )
        .annotate(
            is_overdue=Case(
                When(_overdue_q(today), then=True),
                default=False,
                output_field=BooleanField(),
            )
        )
    )
    if tab == "neapmaksati":
        return base.exclude(payment_status=PaymentStatus.PAID).order_by("due_date")
    if tab == "kaveti":
        return base.filter(_overdue_q(today)).order_by("due_date")
    if tab == "daleji":
        return base.filter(payment_status=PaymentStatus.PARTIAL).order_by("due_date")
    if tab == "kludas":
        return base.exclude(external_error_code="").order_by("-updated_at")
    if tab == "nav_izrakstiti":
        return base.filter(external_invoice_id="").order_by("due_date")
    return base.order_by("-due_date")


def invoice_totals(queryset) -> dict[str, object]:
    """Totals over the WHOLE filtered set, computed in the database.

    Deliberately not a sum of the rows on screen: these figures report money
    owed, and one that described only the current page would understate it.
    ``balance`` is nullable, so it falls back to ``amount`` the same way the
    row display does."""
    today = timezone.localdate()
    aggregates = queryset.aggregate(
        count=Count("pk"),
        outstanding=Sum(
            Coalesce("balance", "amount", output_field=_MONEY), output_field=_MONEY
        ),
        paid_total=Sum("paid_to_date", output_field=_MONEY),
        unsynced_count=Count("pk", filter=Q(external_invoice_id="")),
        overdue_count=Count("pk", filter=_overdue_q(today)),
    )
    return {
        "count": aggregates["count"] or 0,
        "outstanding": _money(aggregates["outstanding"]),
        "paid_total": _money(aggregates["paid_total"]),
        "unsynced_count": aggregates["unsynced_count"] or 0,
        "overdue_count": aggregates["overdue_count"] or 0,
    }


def normalize_page(raw: Any, paginator: Paginator) -> int:
    """Never trust the query string: an invalid or out-of-range page falls
    back to page 1, the same way normalize_invoice_tab handles a bad tab."""
    try:
        return int(paginator.validate_number(raw))
    except (TypeError, ValueError, PageNotAnInteger, EmptyPage):
        return 1


def invoice_page(queryset, page_number: Any) -> tuple[list[Any], Any]:
    """One page of invoice rows plus the Paginator page object.

    The queryset is paginated before the rows are fetched, so the number of
    rows materialised never grows with the club's history — this page's
    archival tabs would otherwise load every invoice ever raised."""
    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.page(normalize_page(page_number, paginator))
    return list(page_obj.object_list), page_obj

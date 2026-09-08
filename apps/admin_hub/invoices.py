"""Querysets and totals for the outstanding-invoice review page.

Reads Invoice Ninja sync state that the nightly sweeps and the per-record
push write; it never calls the provider itself.
"""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.billing.models import BillingInvoice, PaymentStatus

INVOICE_TABS: dict[str, str] = {
    "neapmaksati": "Neapmaksāti",
    "kaveti": "Kavēti",
    "daleji": "Daļēji apmaksāti",
    "kludas": "Sinhronizācijas kļūdas",
    "nav_izrakstiti": "Nav izrakstīti",
    "visi": "Visi",
}
DEFAULT_INVOICE_TAB = "neapmaksati"

# An interactive bulk action above this many rows asks for confirmation first.
# This is a UI guard against a mis-click, not the nightly-sweep batch cap -
# that is tracked as its own change (see the spec).
BULK_CONFIRM_THRESHOLD = 50


def normalize_invoice_tab(raw: str | None) -> str:
    return raw if raw in INVOICE_TABS else DEFAULT_INVOICE_TAB


def invoice_queryset(tab: str):
    today = timezone.localdate()
    base = BillingInvoice.objects.filter(cancelled_at__isnull=True).select_related(
        "billing_record",
        "billing_record__member",
        "billing_record__member__guardian",
        "billing_record__member__training_group",
    )
    if tab == "neapmaksati":
        return base.exclude(payment_status=PaymentStatus.PAID).order_by("due_date")
    if tab == "kaveti":
        return (
            base.exclude(payment_status=PaymentStatus.PAID)
            .filter(due_date__lt=today)
            .order_by("due_date")
        )
    if tab == "daleji":
        return base.filter(payment_status=PaymentStatus.PARTIAL).order_by("due_date")
    if tab == "kludas":
        return base.exclude(external_error_code="").order_by("-updated_at")
    if tab == "nav_izrakstiti":
        return base.filter(external_invoice_id="").order_by("due_date")
    return base.order_by("-due_date")


def invoice_totals(queryset) -> dict[str, object]:
    today = timezone.localdate()
    rows = list(queryset)
    outstanding = Decimal("0.00")
    for invoice in rows:
        balance = invoice.balance if invoice.balance is not None else invoice.amount
        outstanding += balance
    aggregates = queryset.aggregate(paid=Sum("paid_to_date"))
    return {
        "count": len(rows),
        "outstanding": outstanding,
        "overdue_count": sum(
            1
            for invoice in rows
            if invoice.due_date < today
            and invoice.payment_status != PaymentStatus.PAID
        ),
        "unsynced_count": sum(1 for invoice in rows if not invoice.external_invoice_id),
        "paid_total": aggregates["paid"] or Decimal("0.00"),
        "rows": rows,
    }


def parse_id_list(raw: str) -> list[int] | None:
    """Parse a comma-separated id list. Returns None when anything is not an
    integer, so the caller can answer 400 instead of guessing."""
    if not raw:
        return []
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return [int(part) for part in parts]
    except ValueError:
        return None

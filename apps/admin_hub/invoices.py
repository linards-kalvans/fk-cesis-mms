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


def _is_overdue(invoice, today) -> bool:
    """Single source of truth for "is this invoice overdue": a past due date
    is not enough on its own - a fully paid invoice with an old due date is
    not overdue. The kaveti tab filter (queryset-level, above) and this
    function must never diverge, and the template must never re-derive the
    comparison itself - it reads only the ``is_overdue`` attribute this sets
    on each row in ``invoice_totals``."""
    return bool(
        invoice.due_date < today and invoice.payment_status != PaymentStatus.PAID
    )


def invoice_totals(queryset) -> dict[str, object]:
    today = timezone.localdate()
    rows = list(queryset)
    outstanding = Decimal("0.00")
    for invoice in rows:
        balance = invoice.balance if invoice.balance is not None else invoice.amount
        outstanding += balance
        invoice.is_overdue = _is_overdue(invoice, today)
    aggregates = queryset.aggregate(paid=Sum("paid_to_date"))
    return {
        "count": len(rows),
        "outstanding": outstanding,
        "overdue_count": sum(1 for invoice in rows if invoice.is_overdue),
        "unsynced_count": sum(1 for invoice in rows if not invoice.external_invoice_id),
        "paid_total": aggregates["paid"] or Decimal("0.00"),
        "rows": rows,
    }

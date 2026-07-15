"""Parent-facing invoice presentation helpers for /portal/ (P12).

Build read-only invoice groups for the verified parent's portal. Invoice
visibility is ownership-scoped (ParentAccount -> Guardian -> Member ->
BillingRecord -> BillingInvoice); only issued invoices appear, and only
those with a stored parent-safe URL expose a proxy link.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from django.db.models import Q
from django.urls import reverse

from apps.accounts.models import ParentAccount
from apps.billing.messages import PAYMENT_STATUS_LABELS
from apps.billing.models import BillingInvoice


def parent_invoice_groups(account: ParentAccount) -> list[dict[str, Any]]:
    """Return invoice groups for the parent's family, grouped by (member, season).

    Each group is ``{"member_name": str, "season": str, "final_amount": Decimal,
    "currency": str, "rows": [...]}``. A row exposes the invoice plus display
    fields the template needs (sequence, due_date, amount, sent status,
    payment status, sync time, and a proxy URL when the invoice has a stored
    safe external URL).
    """
    invoices = (
        BillingInvoice.objects.filter(
            Q(sent_at__isnull=False) | Q(external_status="sent"),
            billing_record__member__guardian__parent_account=account,
            cancelled_at__isnull=True,
        )
        .select_related("billing_record__member", "billing_record__plan")
        .order_by(
            "billing_record__member__full_name",
            "billing_record__season",
            "due_date",
            "sequence",
        )
    )
    groups: OrderedDict[tuple[int, str], dict[str, Any]] = OrderedDict()
    for invoice in invoices:
        record = invoice.billing_record
        member = record.member
        key = (record.member_id, record.season)
        if key not in groups:
            groups[key] = {
                "member_name": member.full_name,
                "season": record.season,
                "final_amount": record.final_amount,
                "currency": record.plan.currency,
                "rows": [],
            }
        groups[key]["rows"].append(
            {
                "invoice": invoice,
                "sequence": invoice.sequence,
                "due_date": invoice.due_date,
                "amount": invoice.amount,
                "sent_status": "Izsūtīts",
                "payment_status": PAYMENT_STATUS_LABELS.get(
                    invoice.payment_status, "—"
                ),
                "last_synced_at": invoice.last_synced_at,
                "open_url": (
                    reverse(
                        "registrations:parent-invoice-open", args=[invoice.pk]
                    )
                    if invoice.external_url
                    else ""
                ),
            }
        )
    return list(groups.values())

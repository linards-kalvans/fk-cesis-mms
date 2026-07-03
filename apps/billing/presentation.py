"""Presentation helpers for billing records (admin summaries)."""

from __future__ import annotations

from apps.billing.messages import PAYMENT_MODE_LABELS


def billing_summary_line(record) -> str:
    mode = PAYMENT_MODE_LABELS.get(record.payment_mode, record.payment_mode)
    discount = (
        f", atlaide {record.discount_amount} {record.plan.currency}"
        if not record.is_full_price
        else ""
    )
    return (
        f"{record.final_amount} {record.plan.currency} ({mode}){discount}"
    )

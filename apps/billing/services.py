"""Billing services — pure discount engine + draft-record creation.

Slice A is local only. The engine never writes to the DB; record creation
snapshots the computed amounts so later plan edits do not mutate drafts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

logger = logging.getLogger(__name__)

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BillingAmounts:
    base_amount: Decimal
    is_full_price: bool
    discount_percent_applied: Decimal
    discount_amount: Decimal
    final_amount: Decimal


def _member_opted_out(member) -> bool:
    """True when the member's source application opted out of the sibling
    discount (support_club_instead_of_multi_child_discount is True)."""
    application = getattr(member, "source_application", None)
    if application is None:
        return False
    return application.support_club_instead_of_multi_child_discount is True


def _is_first_child(member) -> bool:
    """The full-price child is the earliest-created Member of the guardian
    (by pk). Stable regardless of signing order."""
    earliest = member.guardian.members.order_by("pk").first()
    return earliest is not None and earliest.pk == member.pk


def compute_billing_amounts(member, plan) -> BillingAmounts:
    base = _money(plan.annual_amount)
    full_price = _is_first_child(member) or _member_opted_out(member)
    if full_price:
        return BillingAmounts(
            base_amount=base,
            is_full_price=True,
            discount_percent_applied=Decimal("0.00"),
            discount_amount=Decimal("0.00"),
            final_amount=base,
        )
    percent = plan.sibling_discount_percent
    discount = _money(base * percent / Decimal("100"))
    return BillingAmounts(
        base_amount=base,
        is_full_price=False,
        discount_percent_applied=percent,
        discount_amount=discount,
        final_amount=_money(base - discount),
    )

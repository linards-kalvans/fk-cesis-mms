"""Billing services — pure discount engine + draft-record creation.

Slice A is local only. The engine never writes to the DB; record creation
snapshots the computed amounts so later plan edits do not mutate drafts.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone


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


def derive_installment_schedule(plan, total: Decimal) -> list[tuple[datetime.date, Decimal]]:
    """Split `total` into `plan.installment_count` equal monthly entries starting
    at `plan.first_installment_month`. Equal cents; the last entry absorbs the
    rounding remainder. Due dates are the 1st of each successive month; the year
    is anchored to the first year in `plan.season` ("2026/2027" -> 2026) and rolls
    forward when the month wraps past December.

    Exact day-of-month and final calendar anchoring are revisited in Slice B once
    the Invoice Ninja API dictates the invoice shape.
    """
    count = max(int(plan.installment_count), 1)
    per = _money(total / Decimal(count))
    amounts = [per] * (count - 1)
    amounts.append(_money(total - per * (count - 1)))

    start_year = int(plan.season.split("/")[0])
    schedule: list[tuple[datetime.date, Decimal]] = []
    month = int(plan.first_installment_month)
    year = start_year
    for amount in amounts:
        schedule.append((datetime.date(year, month, 1), amount))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return schedule


def create_draft_billing_for_member(member, agreement):
    """Idempotently create a draft BillingRecord for the active plan's season.

    Returns the record (existing or new), or None when no active plan exists.
    Never raises on missing config — signing must not break.
    """
    from apps.billing.models import BillingRecord, MembershipPlan

    plan = MembershipPlan.objects.filter(is_active=True).order_by("-pk").first()
    if plan is None:
        logger.warning(
            "No active MembershipPlan; skipping billing draft for member %s", member.pk
        )
        return None

    existing = BillingRecord.objects.filter(member=member, season=plan.season).first()
    if existing is not None:
        return existing

    amounts = compute_billing_amounts(member, plan)
    application = getattr(member, "source_application", None)
    payment_mode = BillingRecord.PaymentMode.INSTALLMENTS
    opt_out = False
    if application is not None:
        if application.preferred_payment_mode:
            payment_mode = application.preferred_payment_mode
        opt_out = application.support_club_instead_of_multi_child_discount is True

    record, _created = BillingRecord.objects.get_or_create(
        member=member,
        season=plan.season,
        defaults={
            "plan": plan,
            "agreement": agreement,
            "base_amount": amounts.base_amount,
            "is_full_price": amounts.is_full_price,
            "sibling_discount_percent_applied": amounts.discount_percent_applied,
            "discount_amount": amounts.discount_amount,
            "final_amount": amounts.final_amount,
            "payment_mode": payment_mode,
            "full_price_opt_out": opt_out,
        },
    )
    return record


def recompute_billing_record(record) -> None:
    """Re-derive natural amounts from the record's plan for a DRAFT record.
    No-op on a confirmed record. Honors a manual override for final_amount."""
    from apps.billing.models import BillingRecord

    if record.status != BillingRecord.Status.DRAFT:
        return
    # Refresh plan from DB so any edits made after the record was created are picked up.
    plan = record.plan.__class__.objects.get(pk=record.plan_id)
    amounts = compute_billing_amounts(record.member, plan)
    record.base_amount = amounts.base_amount
    record.is_full_price = amounts.is_full_price
    record.sibling_discount_percent_applied = amounts.discount_percent_applied
    record.discount_amount = amounts.discount_amount
    record.final_amount = (
        record.manual_amount_override
        if record.manual_amount_override is not None
        else amounts.final_amount
    )
    record.save(
        update_fields=[
            "base_amount",
            "is_full_price",
            "sibling_discount_percent_applied",
            "discount_amount",
            "final_amount",
            "updated_at",
        ]
    )


def roll_up_payment_status(record) -> None:
    """Derive the record-level payment_status from its invoices and stamp
    payment_synced_at. all paid -> paid; any paid/partial -> partial; else unpaid."""
    from apps.billing.models import PaymentStatus

    statuses = list(record.invoices.values_list("payment_status", flat=True))
    if statuses and all(s == PaymentStatus.PAID for s in statuses):
        record.payment_status = PaymentStatus.PAID
    elif any(s in (PaymentStatus.PAID, PaymentStatus.PARTIAL) for s in statuses):
        record.payment_status = PaymentStatus.PARTIAL
    else:
        record.payment_status = PaymentStatus.UNPAID
    record.payment_synced_at = timezone.now()
    record.save(update_fields=["payment_status", "payment_synced_at", "updated_at"])


def membership_plan_product_key(plan) -> str:
    """Deterministic Invoice Ninja product_key for a plan (no stored column,
    so it can never drift): season "2026/2027" -> "biedra-maksa-2026-2027"."""
    slug = plan.season.replace("/", "-")
    return f"biedra-maksa-{slug}"


def materialize_installments(record):
    """Create the BillingInvoice rows for a record from the snapshotted
    final_amount, idempotently. Upfront -> one row due on the first
    installment date; installments -> derive_installment_schedule rows."""
    from apps.billing.models import BillingInvoice, BillingRecord

    existing = list(record.invoices.order_by("sequence"))
    if existing:
        return existing

    schedule = derive_installment_schedule(record.plan, record.final_amount)
    if record.payment_mode == BillingRecord.PaymentMode.UPFRONT:
        first_due = schedule[0][0]
        schedule = [(first_due, record.final_amount)]

    rows = [
        BillingInvoice.objects.create(
            billing_record=record, sequence=i, due_date=due, amount=amount
        )
        for i, (due, amount) in enumerate(schedule, start=1)
    ]
    return rows

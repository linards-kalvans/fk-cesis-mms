"""Billing services — pure discount engine + draft-record creation.

Slice A is local only. The engine never writes to the DB; record creation
snapshots the computed amounts so later plan edits do not mutate drafts.
"""

from __future__ import annotations

import calendar
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


def get_default_billing_plan():
    """Return the single active default MembershipPlan, or None when none is set.

    The default is explicit (one row, marked ``is_default=True``); it must also
    be active. New agreements preselect this plan + a derived first billing
    month so the signed transition can realise billing without a staff step.
    """
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.filter(is_default=True, is_active=True).first()


def derive_first_billing_month(plan, today: datetime.date | None = None) -> str:
    """Return the ``YYYY-MM`` of the first invoice: when ``today.day <= cutoff``
    the current month, otherwise the next month (year-wrap when month rolls
    past December). Falls back to the configured ``today`` so tests can pin
    a deterministic date."""
    today = today or timezone.localdate()
    year = int(today.year)
    month = int(today.month)
    if int(today.day) > int(plan.billing_start_cutoff_day):
        month += 1
        if month > 12:
            month = 1
            year += 1
    return f"{year:04d}-{month:02d}"


def parse_first_billing_month(value: str) -> tuple[int, int] | None:
    """Parse a ``YYYY-MM`` override. Blank → None (caller falls back to plan).
    Any malformed non-blank value raises ValueError so the admin form rejects
    garbage and the service refuses to persist it."""
    if not value:
        return None
    try:
        year_str, month_str = value.split("-", 1)
        year = int(year_str)
        month = int(month_str)
    except (ValueError, AttributeError) as exc:
        raise ValueError("first billing month must use YYYY-MM") from exc
    if len(year_str) != 4 or len(month_str) != 2 or not 1 <= month <= 12:
        raise ValueError("first billing month must use YYYY-MM")
    return year, month


def derive_installment_schedule(
    plan,
    total: Decimal,
    *,
    first_billing_month: str = "",
) -> list[tuple[datetime.date, Decimal]]:
    """Split `total` into `plan.installment_count` equal monthly entries, placed on
    successive billing months. When ``first_billing_month`` (YYYY-MM) is given,
    the schedule anchors there; otherwise the plan's ``first_installment_month``
    + season start-year is the anchor. SKIPS any month in ``plan.skip_months_list``
    (default July + December). Equal cents; the last entry absorbs the rounding
    remainder. Each due date is ``plan.payment_due_day`` clamped to the month
    length. Year wraps past December."""
    count = max(int(plan.installment_count), 1)
    per = _money(total / Decimal(count))
    amounts = [per] * (count - 1)
    amounts.append(_money(total - per * (count - 1)))

    skip = set(plan.skip_months_list)
    due_day = int(plan.payment_due_day)

    parsed = parse_first_billing_month(first_billing_month)
    if parsed is None:
        start_year = int(plan.season.split("/")[0])
        month = int(plan.first_installment_month)
        year = start_year
    else:
        year, month = parsed

    schedule: list[tuple[datetime.date, Decimal]] = []
    for amount in amounts:
        skipped = 0
        while month in skip:
            month += 1
            if month > 12:
                month = 1
                year += 1
            skipped += 1
            if skipped > 12:  # 12 consecutive skips => every month is skipped
                raise ValueError(
                    "derive_installment_schedule: no billing months available"
                )
        day = min(due_day, calendar.monthrange(year, month)[1])
        schedule.append((datetime.date(year, month, day), amount))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return schedule


class DiscontinuationInvoiceError(ValueError):
    """Base for billing-side discontinuation selection errors."""


class PaidInvoiceSelected(DiscontinuationInvoiceError):
    """Raised when staff selects a paid invoice for discontinuation."""


def is_invoice_due_to_send(invoice, today: datetime.date) -> bool:
    """True when a Draft installment invoice should be issued + emailed: it
    exists in Invoice Ninja, is still Draft, today is on/after the first
    day of its due month, and it has not been locally cancelled.
    (Guardian-email presence + the autosend flag are checked by the
    caller — see apps.integrations.tasks.send_due_invoices.)"""
    if getattr(invoice, "cancelled_at", None) is not None:
        return False
    if not invoice.external_invoice_id:
        return False
    if invoice.external_status != "created":
        return False
    return bool(today >= invoice.due_date.replace(day=1))


def create_discontinuation_adjustments(member, event, invoice_ids, reason: str):
    """Process selected BillingInvoice rows for a member discontinuation.

    - Paid or partially paid invoices block the operation (PaidInvoiceSelected).
    - Invoices without an external id and never sent are cancelled locally.
    - Invoice Ninja draft invoices (external_status='created') are cancelled
      locally and queued for external archive.
    - Invoice Ninja sent unpaid invoices (external_status='sent') are cancelled
      locally and queued for external cancel.

    Returns ``(adjustments, invoice_actions)`` where ``adjustments`` is a list
    of created BillingAdjustment rows (empty for normal unpaid invoices) and
    ``invoice_actions`` is a list of ``(invoice_pk, action)`` tuples describing
    pending external archive/cancel jobs the caller must enqueue.
    """
    from apps.billing.models import BillingInvoice, PaymentStatus

    if not invoice_ids:
        return [], []

    selected = list(
        BillingInvoice.objects.filter(
            pk__in=invoice_ids, billing_record__member=member
        ).select_related("billing_record")
    )
    if len(selected) != len(invoice_ids):
        raise ValueError("one or more selected invoices are foreign to this member")

    # Validate every selected invoice before any mutation.
    for invoice in selected:
        if invoice.payment_status in (PaymentStatus.PAID, PaymentStatus.PARTIAL):
            raise PaidInvoiceSelected(
                f"Invoice {invoice.pk} is paid; refund manually in Invoice Ninja."
            )
        if not invoice.external_invoice_id and invoice.sent_at is not None:
            raise DiscontinuationInvoiceError(
                "Rēķins atzīmēts kā nosūtīts, bet trūkst Invoice Ninja identifikatora."
            )
        if invoice.external_invoice_id and invoice.external_status not in (
            "created",
            "sent",
        ):
            raise DiscontinuationInvoiceError(
                f"Rēķinam {invoice.pk} nav derīgs Invoice Ninja statuss."
            )

    adjustments: list = []
    invoice_actions: list[tuple[int, str]] = []
    now = timezone.now()
    for invoice in selected:
        if not invoice.external_invoice_id and invoice.sent_at is None:
            invoice.cancelled_at = now
            invoice.cancellation_reason = reason
            invoice.save(
                update_fields=["cancelled_at", "cancellation_reason", "updated_at"]
            )
            continue

        invoice.cancelled_at = now
        invoice.cancellation_reason = reason
        if invoice.external_status == "created":
            invoice.external_cancellation_action = "archive"
        else:
            invoice.external_cancellation_action = "cancel"
        invoice.external_cancellation_status = "pending"
        invoice.external_cancellation_error_code = ""
        invoice.save(
            update_fields=[
                "cancelled_at",
                "cancellation_reason",
                "external_cancellation_action",
                "external_cancellation_status",
                "external_cancellation_error_code",
                "updated_at",
            ]
        )
        invoice_actions.append((invoice.pk, invoice.external_cancellation_action))

    return adjustments, invoice_actions


def create_draft_billing_for_member(member, agreement):
    """Idempotently create a draft BillingRecord for the season of the plan
    the member is on.

    Plan resolution (P9):
      - When ``agreement`` is provided and carries a non-null ``billing_plan``,
        that plan is used (signed agreement's explicit intent). Its
        ``first_billing_month`` is snapshotted onto the record.
      - When the agreement is missing or has no ``billing_plan``, fall back to
        the latest active plan (legacy backfill + ``manage.py backfill_billing``
        + the agreement_signed signal for pre-P9 agreements without a plan).

    Returns the record (existing or new), or None when no plan can be resolved.
    Never raises on missing config — signing must not break.
    """
    from apps.billing.models import BillingRecord, MembershipPlan

    plan = getattr(agreement, "billing_plan", None) if agreement is not None else None
    first_billing_month = (
        getattr(agreement, "first_billing_month", "") or ""
    ) if agreement is not None else ""

    if plan is None:
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
            "first_billing_month": first_billing_month,
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

    schedule = derive_installment_schedule(
        record.plan,
        record.final_amount,
        first_billing_month=record.first_billing_month,
    )
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


def renew_member_billing(
    member,
    plan,
    *,
    first_billing_month: str = "",
    actor=None,
):
    """Create a missing draft BillingRecord for ``(member, plan.season)`` and
    audit the creation.

    Returns the new record, or None when a record for that season already
    exists (skip). The caller is expected to filter out discontinued members
    upstream — the service is intentionally simple so it stays composable in
    the selected-member admin action and any future batch flow. Audits only
    on real creation, never on the no-op path.
    """
    from apps.agreements.services import get_current_agreement
    from apps.billing.models import BillingRecord
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent

    if first_billing_month:
        parse_first_billing_month(first_billing_month)

    if BillingRecord.objects.filter(member=member, season=plan.season).exists():
        return None

    amounts = compute_billing_amounts(member, plan)
    application = getattr(member, "source_application", None)
    payment_mode = BillingRecord.PaymentMode.INSTALLMENTS
    opt_out = False
    if application is not None:
        if application.preferred_payment_mode:
            payment_mode = application.preferred_payment_mode
        opt_out = application.support_club_instead_of_multi_child_discount is True

    record = BillingRecord.objects.create(
        member=member,
        plan=plan,
        agreement=get_current_agreement(member),
        season=plan.season,
        first_billing_month=first_billing_month,
        base_amount=amounts.base_amount,
        is_full_price=amounts.is_full_price,
        sibling_discount_percent_applied=amounts.discount_percent_applied,
        discount_amount=amounts.discount_amount,
        final_amount=amounts.final_amount,
        payment_mode=payment_mode,
        full_price_opt_out=opt_out,
    )
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_RENEWED),
        actor=actor,
        target=record,
        metadata={
            "plan_id": plan.pk,
            "season": plan.season,
            "first_billing_month": first_billing_month,
        },
    )
    return record


def reassign_draft_billing_record(
    record,
    plan,
    *,
    first_billing_month: str = "",
    actor=None,
) -> None:
    """Replace a draft BillingRecord's plan/season/month, recompute amounts, and
    audit the change.

    Hard guards (raise ValueError — never silently mutate):
      - record is not DRAFT (confirmed / pushed / paid records must not drift);
      - any invoice already pushed to Invoice Ninja (has external_invoice_id);
      - any invoice already emailed to a parent (has sent_at).

    Local-only invoices are deleted so the new plan+month materializes fresh
    dates. A manual override on the record is preserved across the swap.
    """
    from apps.billing.models import BillingRecord
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent

    if record.status != BillingRecord.Status.DRAFT:
        raise ValueError(
            "only draft billing records can be reassigned; confirmed records must stay locked"
        )
    if first_billing_month:
        parse_first_billing_month(first_billing_month)
    if (
        record.invoices.exclude(external_invoice_id="").exists()
        or record.invoices.filter(sent_at__isnull=False).exists()
    ):
        raise ValueError(
            "cannot reassign a billing record with pushed or sent invoices"
        )

    old_plan_id = record.plan_id
    old_month = record.first_billing_month

    record.invoices.all().delete()
    amounts = compute_billing_amounts(record.member, plan)
    record.plan = plan
    record.season = plan.season
    record.first_billing_month = first_billing_month
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
            "plan",
            "season",
            "first_billing_month",
            "base_amount",
            "is_full_price",
            "sibling_discount_percent_applied",
            "discount_amount",
            "final_amount",
            "updated_at",
        ]
    )
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_REASSIGNED),
        actor=actor,
        target=record,
        metadata={
            "old_plan_id": old_plan_id,
            "new_plan_id": plan.pk,
            "old_first_billing_month": old_month,
            "new_first_billing_month": first_billing_month,
        },
    )

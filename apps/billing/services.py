"""Billing services — pure discount engine + draft-record creation.

P14: fixed family tier engine (0/50/75/100 %) snapshotting per
``(member, season)`` under a guardian-row lock. Existing records
preserve their stored snapshot forever — recompute/reassign/renewal
never rerun the family-rank query.
"""

from __future__ import annotations

import calendar
import datetime
import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q
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


# ---------------------------------------------------------------------------
# P14 — fixed family tier engine.
#
# Family rank is computed from the guardian's current signed Agreements
# (state=signed, is_current=True), ordered by signed_at ASC then member_id
# ASC. Normal signing path filters agreements by billing_plan__season ==
# plan.season. P9 renewal omits that filter to carry the current signed
# family across target-plan seasons.
# ---------------------------------------------------------------------------

TIER_DISCOUNT_PERCENT: dict[int, Decimal] = {
    0: Decimal("0.00"),
    1: Decimal("50.00"),
    2: Decimal("75.00"),
    3: Decimal("100.00"),
}


def _member_opted_out(member) -> bool:
    """True when the member's source application opted out of the sibling
    discount (support_club_instead_of_multi_child_discount is True)."""
    application = getattr(member, "source_application", None)
    if application is None:
        return False
    return application.support_club_instead_of_multi_child_discount is True


def compute_family_tier(
    member,
    plan,
    first_due_date: datetime.date,
    *,
    season_scoped: bool = True,
) -> int:
    """Return the candidate's rank in the guardian's current signed family,
    clamped to ``max(TIER_DISCOUNT_PERCENT)``. Candidate absent -> 0
    (legacy no-agreement full-price fallback)."""
    from apps.agreements.models import Agreement
    from apps.members.models import Member

    candidates = (
        Agreement.objects.filter(
            is_current=True,
            state=Agreement.State.SIGNED,
            member__guardian_id=member.guardian_id,
        )
        .exclude(
            Q(
                member__discontinued_effective_date__isnull=False,
                member__discontinued_effective_date__lte=first_due_date,
            )
            | Q(
                member__status=Member.Status.DISCONTINUED,
                member__discontinued_effective_date__isnull=True,
            )
        )
        .select_related("member")
        .order_by("signed_at", "member_id")
    )
    if season_scoped:
        candidates = candidates.filter(billing_plan__season=plan.season)
    for rank, candidate in enumerate(candidates):
        if candidate.member_id == member.pk:
            return min(rank, max(TIER_DISCOUNT_PERCENT))
    return 0


def _first_billable_due_date(plan, first_billing_month: str) -> datetime.date:
    return derive_installment_schedule(
        plan, Decimal("0.00"), first_billing_month=first_billing_month
    )[0][0]


def _tiered_billing_amounts(
    member,
    plan,
    first_billing_month: str,
    *,
    season_scoped: bool,
    base_amount: Decimal | None = None,
) -> BillingAmounts:
    # P15: caller may pass a pre-computed partial-year base (P15
    # calendar-year partial). Default is the plan's full annual amount.
    base = _money(base_amount if base_amount is not None else plan.annual_amount)
    tier_percent = TIER_DISCOUNT_PERCENT[
        compute_family_tier(
            member,
            plan,
            _first_billable_due_date(plan, first_billing_month),
            season_scoped=season_scoped,
        )
    ]
    opt_out = _member_opted_out(member)
    percent = Decimal("0.00") if opt_out else tier_percent
    discount = _money(base * percent / Decimal("100"))
    return BillingAmounts(
        base_amount=base,
        is_full_price=percent == Decimal("0.00"),
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


def _plan_season_start_year(plan) -> int:
    """Return the start year of ``plan.season`` (``YYYY/YYYY`` → first YYYY).

    P15: invalid/malformed seasons must fail safe as a ValueError (the caller
    maps it to a Latvian staff message). Never silently fall back to the
    current calendar year — that would let a corrupt plan row leak through
    into billing setup."""
    try:
        year_str = str(plan.season).split("/")[0]
        year = int(year_str)
    except (ValueError, AttributeError, IndexError) as exc:
        raise ValueError("plan season is malformed") from exc
    if not 1900 <= year <= 9999:
        raise ValueError("plan season year out of range")
    return year


def normalize_first_billing_month(plan, value: str) -> str:
    """Validate a ``YYYY-MM`` value and advance past any skip month on the
    plan, returning the canonical ``YYYY-MM`` of the first billable month.

    ``December → January next year`` is the only year wrap path. Raises
    ``ValueError`` when the year wraps past the start year with no billable
    month in sight, or when the input is malformed (the service-layer
    contract: refuse silently, never rewind to a default)."""
    parsed = parse_first_billing_month(value)
    if parsed is None:
        raise ValueError("first billing month must use YYYY-MM")
    year, month = parsed
    skip = set(plan.skip_months_list)
    advanced = 0
    while month in skip:
        month += 1
        if month > 12:
            month = 1
            year += 1
        advanced += 1
        if advanced > 12:
            raise ValueError("no billing months available in selected year")
    return f"{year:04d}-{month:02d}"


def count_calendar_year_billable_installments(plan, first_billing_month: str) -> int:
    """Count scheduled installments the plan would actually emit in the
    first_billing_month's calendar year, using the plan's own schedule.

    Delegates to ``derive_installment_schedule`` with a zero total (so
    amount distribution is irrelevant) and the plan's default
    ``installment_count`` (no cap kwarg), then filters rows whose
    ``due_date.year`` matches the parsed first billing month year. This
    caps the count at the plan's real scheduled installments — a
    one-installment plan starting September returns 1, not the three
    Sep/Oct/Nov months that a manual walk through the calendar would
    count. Used by P15 to derive the partial-year snapshot count that
    the saved ``BillingRecord.scheduled_installment_count`` carries."""
    parsed = parse_first_billing_month(first_billing_month)
    if parsed is None:
        raise ValueError("first billing month must use YYYY-MM")
    start_year, _start_month = parsed
    schedule = derive_installment_schedule(
        plan, Decimal("0.00"), first_billing_month=first_billing_month
    )
    return sum(1 for due_date, _amount in schedule if due_date.year == start_year)


def partial_base_amount(plan, scheduled_installment_count: int) -> Decimal:
    """Return the partial-year base: ``annual_amount * count / installment_count``
    rounded HALF_UP to cents. Used by P15 to snapshot the calendar-year base
    before P14's fixed family tier is applied."""
    total_installments = max(int(plan.installment_count), 1)
    count = max(int(scheduled_installment_count), 1)
    return _money(plan.annual_amount * Decimal(count) / Decimal(total_installments))


def derive_installment_schedule(
    plan,
    total: Decimal,
    *,
    first_billing_month: str = "",
    installment_count: int | None = None,
) -> list[tuple[datetime.date, Decimal]]:
    """Split `total` into monthly entries, placed on successive billing months.
    When ``first_billing_month`` (YYYY-MM) is given, the schedule anchors
    there; otherwise the plan's ``first_installment_month`` + season start-year
    is the anchor. SKIPS any month in ``plan.skip_months_list`` (default July +
    December). Equal cents; the last entry absorbs the rounding remainder.
    Each due date is ``plan.payment_due_day`` clamped to the month length.
    Year wraps past December.

    P15: ``installment_count`` caps the generated rows to the saved snapshot
    count (legacy callers omit it and the plan's full ``installment_count``
    applies). A P15 record never rolls into the next calendar year because
    the saved count was derived from the year."""
    count = max(
        int(installment_count) if installment_count is not None else int(plan.installment_count),
        1,
    )
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

    P14 — fixed tier engine + guardian-row lock:
      - tier rank is computed under ``Guardian.select_for_update()`` so
        concurrent sibling signings cannot claim the same rank;
      - the snapshotted tier never reruns — later family changes do not
        mutate the record.

    P15 — calendar-year partial base:
      - when the agreement has a non-blank ``first_billing_month``, the
        calendar-year partial base is snapshotted (annual × remaining
        billable months / plan installment count) and the
        ``scheduled_installment_count`` is saved; the P14 tier is applied
        on top of that partial base;
      - legacy ``agreement=None`` or blank-month paths keep the full
        annual base + NULL saved count (legacy full-plan materialization).

    Plan resolution (P9):
      - When ``agreement`` is provided and carries a non-null ``billing_plan``,
        that plan is used (signed agreement's explicit intent). Its
        ``first_billing_month`` is snapshotted onto the record.
      - When the agreement is missing or has no ``billing_plan``, fall back to
        the latest active plan (legacy backfill + ``manage.py backfill_billing``
        + the agreement_signed signal for pre-P9 agreements without a plan).

    Legacy fallback: ``agreement=None`` is intentionally full-price (rank 0)
    even when the member happens to have signed agreements, preserving the
    pre-P14 backfill/signal behaviour for that calling pattern.

    Returns the record (existing or new), or None when no plan can be resolved.
    Never raises on missing config — signing must not break.
    """
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.members.models import Guardian

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

    with transaction.atomic():
        if member.guardian_id is not None:
            Guardian.objects.select_for_update().get(pk=member.guardian_id)

        existing = BillingRecord.objects.filter(member=member, season=plan.season).first()
        if existing is not None:
            return existing

        scheduled_count: int | None = None
        if agreement is None:
            # Legacy fallback: agreement=None is intentionally full-price
            # (rank 0 / 0 % discount) even when the member happens to have
            # signed agreements, preserving the pre-P14 backfill/signal
            # behaviour for that calling pattern.
            base = _money(plan.annual_amount)
            amounts = BillingAmounts(
                base_amount=base,
                is_full_price=True,
                discount_percent_applied=Decimal("0.00"),
                discount_amount=Decimal("0.00"),
                final_amount=base,
            )
        elif not first_billing_month:
            # P15 nonblank-free legacy path: full annual base + NULL
            # saved count. The P14 tier still applies (legacy behaviour
            # for a draft that was created without a staff-confirmed
            # month — e.g. a direct ORM-built test fixture or a
            # backfilled record that predates P15). The signed transition
            # is blocked at mark_agreement_signed for blank months, so
            # this branch only fires for non-signing calling patterns
            # (backfill, signal, tests).
            amounts = _tiered_billing_amounts(
                member, plan, first_billing_month, season_scoped=True
            )
        else:
            # P15: every agreement that carries a staff-confirmed
            # first_billing_month snapshots the calendar-year partial
            # base (annual × remaining billable months / plan installment
            # count) and the scheduled count. The P14 tier is applied on
            # top. There is no "== first_installment_month is full annual"
            # exception — a September start on a plan whose
            # first_installment_month is also 9 still produces a partial
            # base (3 remaining billable months on skip_months='7,12').
            scheduled_count = count_calendar_year_billable_installments(
                plan, first_billing_month
            )
            base = partial_base_amount(plan, scheduled_count)
            amounts = _tiered_billing_amounts(
                member,
                plan,
                first_billing_month,
                season_scoped=True,
                base_amount=base,
            )
        application = getattr(member, "source_application", None)
        payment_mode = BillingRecord.PaymentMode.INSTALLMENTS
        opt_out = _member_opted_out(member)
        if application is not None and application.preferred_payment_mode:
            payment_mode = application.preferred_payment_mode

        return BillingRecord.objects.create(
            member=member,
            plan=plan,
            agreement=agreement,
            season=plan.season,
            base_amount=amounts.base_amount,
            is_full_price=amounts.is_full_price,
            sibling_discount_percent_applied=amounts.discount_percent_applied,
            discount_amount=amounts.discount_amount,
            final_amount=amounts.final_amount,
            payment_mode=payment_mode,
            full_price_opt_out=opt_out,
            first_billing_month=first_billing_month,
            scheduled_installment_count=scheduled_count,
        )


def recompute_billing_record(record) -> None:
    """Re-derive natural amounts from the record's plan for a DRAFT record.
    No-op on a confirmed record. Honors a manual override for final_amount.

    P14: never recomputes the family rank — the stored
    ``sibling_discount_percent_applied`` is preserved verbatim and used as
    the percent input. ``is_full_price`` / ``full_price_opt_out`` are
    preserved on the snapshotted record.

    P15: when ``scheduled_installment_count`` is set, the partial-year
    base (annual × saved count / plan installment count) is recomputed
    instead of resetting to ``annual_amount``; the saved count itself is
    preserved. P14 zero-total behaviour (final_amount = 0 → no materialised
    invoices) still flows through naturally."""
    from apps.billing.models import BillingRecord

    if record.status != BillingRecord.Status.DRAFT:
        return
    # Refresh plan from DB so any edits made after the record was created are picked up.
    plan = record.plan.__class__.objects.get(pk=record.plan_id)
    percent = record.sibling_discount_percent_applied
    if record.scheduled_installment_count is not None:
        record.base_amount = partial_base_amount(
            plan, record.scheduled_installment_count
        )
    else:
        record.base_amount = _money(plan.annual_amount)
    record.discount_amount = _money(record.base_amount * percent / Decimal("100"))
    record.final_amount = (
        record.manual_amount_override
        if record.manual_amount_override is not None
        else _money(record.base_amount - record.discount_amount)
    )
    record.save(
        update_fields=[
            "base_amount",
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
    installment date; installments -> derive_installment_schedule rows.

    P14: a 100 % tier record (final_amount == 0) never materialises
    invoices — it exists only as a local history/audit row.

    P15: when ``scheduled_installment_count`` is set, the saved count caps
    the schedule so partial-year rows never roll into the next calendar
    year. Legacy NULL rows keep the plan's full installment count."""
    from apps.billing.models import BillingInvoice, BillingRecord

    if record.final_amount == Decimal("0.00"):
        return []

    existing = list(record.invoices.order_by("sequence"))
    if existing:
        return existing

    count = record.scheduled_installment_count
    schedule = derive_installment_schedule(
        record.plan,
        record.final_amount,
        first_billing_month=record.first_billing_month,
        installment_count=count,
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

    P14: tier rank is computed under ``Guardian.select_for_update()`` with
    ``season_scoped=False`` — P9's billing-only renewal carries the
    current signed family across target-plan seasons without creating a
    new agreement. A renewal member with no current signed agreement falls
    back to rank 0 / full price (legacy no-agreement behaviour).

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
    from apps.members.models import Guardian

    if first_billing_month:
        parse_first_billing_month(first_billing_month)

    with transaction.atomic():
        if member.guardian_id is not None:
            Guardian.objects.select_for_update().get(pk=member.guardian_id)

        if BillingRecord.objects.filter(member=member, season=plan.season).exists():
            return None

        amounts = _tiered_billing_amounts(
            member, plan, first_billing_month, season_scoped=False
        )
        application = getattr(member, "source_application", None)
        payment_mode = BillingRecord.PaymentMode.INSTALLMENTS
        opt_out = _member_opted_out(member)
        if application is not None and application.preferred_payment_mode:
            payment_mode = application.preferred_payment_mode

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
    """Replace a draft BillingRecord's plan/season/month and audit the change.

    Hard guards (raise ValueError — never silently mutate):
      - record is not DRAFT (confirmed / pushed / paid records must not drift);
      - any invoice already pushed to Invoice Ninja (has external_invoice_id);
      - any invoice already emailed to a parent (has sent_at);
      - P15: a non-blank first_billing_month must normalize to a month in
        the new plan's season-start year (no rollover to the next year)
        and must not backdate before the cutoff-derived default.

    P14: the stored tier snapshot is preserved verbatim — only
    ``base_amount`` / ``discount_amount`` / ``final_amount`` are re-derived
    from the stored ``sibling_discount_percent_applied``. A manual override
    is preserved across the swap.

    P15: a non-blank replacement plan/month is always normalized, the
    calendar-year count is recomputed, and the partial base is used. This
    applies even to a legacy draft with ``scheduled_installment_count=NULL``
    — explicit staff replacement is a deliberate P15 transformation. A
    blank ``first_billing_month`` keeps the legacy full-annual / NULL-count
    path. The audit event carries the new scheduled count when set.
    """
    from apps.billing.models import BillingRecord
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent

    if record.status != BillingRecord.Status.DRAFT:
        raise ValueError(
            "only draft billing records can be reassigned; confirmed records must stay locked"
        )
    if (
        record.invoices.exclude(external_invoice_id="").exists()
        or record.invoices.filter(sent_at__isnull=False).exists()
    ):
        raise ValueError(
            "cannot reassign a billing record with pushed or sent invoices"
        )

    # P15: validate the new plan/month before any mutation. A non-blank
    # month is normalized, the season-start-year is checked, the no-backdate
    # floor is enforced, and the calendar-year count is derived — all
    # before the record is touched. Blank input keeps the legacy path
    # (full annual / NULL count).
    normalized_month = ""
    new_count: int | None = None
    if first_billing_month:
        parse_first_billing_month(first_billing_month)
        normalized_month = normalize_first_billing_month(plan, first_billing_month)
        season_year = _plan_season_start_year(plan)
        if int(normalized_month.split("-")[0]) != season_year:
            raise ValueError("next year plan required")
        cutoff_default = derive_first_billing_month(plan)
        if normalized_month < cutoff_default:
            raise ValueError(
                "first billing month cannot be before cutoff-derived default"
            )
        new_count = count_calendar_year_billable_installments(plan, normalized_month)

    old_plan_id = record.plan_id
    old_month = record.first_billing_month

    record.invoices.all().delete()
    percent = record.sibling_discount_percent_applied
    # P15: a non-blank month always lands on the partial base + saved
    # count, even when the prior record was a legacy NULL-count row.
    # Blank input preserves the legacy full-annual / NULL-count path.
    if new_count is not None:
        record.base_amount = partial_base_amount(plan, new_count)
    else:
        record.base_amount = _money(plan.annual_amount)
    record.plan = plan
    record.season = plan.season
    record.first_billing_month = normalized_month or first_billing_month
    record.scheduled_installment_count = new_count
    record.discount_amount = _money(record.base_amount * percent / Decimal("100"))
    record.final_amount = (
        record.manual_amount_override
        if record.manual_amount_override is not None
        else _money(record.base_amount - record.discount_amount)
    )
    record.save(
        update_fields=[
            "plan",
            "season",
            "first_billing_month",
            "scheduled_installment_count",
            "base_amount",
            "discount_amount",
            "final_amount",
            "updated_at",
        ]
    )
    audit_metadata = {
        "old_plan_id": old_plan_id,
        "new_plan_id": plan.pk,
        "old_first_billing_month": old_month,
        "new_first_billing_month": record.first_billing_month,
    }
    if new_count is not None:
        audit_metadata["scheduled_installment_count"] = new_count
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_REASSIGNED),
        actor=actor,
        target=record,
        metadata=audit_metadata,
    )

"""P15 — calendar-year partial billing.

Staff-confirmed ``Agreement.first_billing_month`` drives the price, never the
signing date. A mid-year start produces a partial base proportional to the
remaining billable months in the calendar year; P14's fixed family tier
applies on top. A plan skip month advances to the next billable month.
When no billable month remains in the calendar year, signing must not mutate
agreement state or create a BillingRecord.

P15 records persist a nullable ``BillingRecord.scheduled_installment_count``;
legacy NULL rows retain the existing full-schedule fallback. Invoice
materialization for P15 creates only snapshot-count rows, never next-year
rows. Manual override remains final total and splits across saved count.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(*, skip_months="7,12", **overrides):
    from apps.billing.models import MembershipPlan

    defaults = dict(
        name="P15-Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        payment_due_day=20,
        skip_months=skip_months,
        is_active=True,
    )
    defaults.update(overrides)
    plan = MembershipPlan(**defaults)
    plan.save()
    return plan


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    return make_guardian(full_name="P15 Guardian", email="p15@example.test")


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(full_name="P15 Child", guardian=guardian)


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer_p15", is_staff=True)


# ---------------------------------------------------------------------------
# 1. normalize_first_billing_month — skip months advance
# ---------------------------------------------------------------------------


class TestNormalizeFirstBillingMonth:
    def test_july_skip_advances_to_august(self):
        """A plan skipping July and December normalizes '2026-07' to
        '2026-08'."""
        from apps.billing.services import normalize_first_billing_month

        plan = _make_plan(skip_months="7,12")
        assert normalize_first_billing_month(plan, "2026-07") == "2026-08"

    def test_non_skip_month_passes_through(self):
        """A non-skip month normalizes to itself."""
        from apps.billing.services import normalize_first_billing_month

        plan = _make_plan(skip_months="7,12")
        assert normalize_first_billing_month(plan, "2026-08") == "2026-08"

    def test_december_skip_advances_to_january_next_year(self):
        """December skip advances to January of the next year."""
        from apps.billing.services import normalize_first_billing_month

        plan = _make_plan(skip_months="7,12")
        assert normalize_first_billing_month(plan, "2026-12") == "2027-01"


# ---------------------------------------------------------------------------
# 2. count_calendar_year_billable_installments
# ---------------------------------------------------------------------------


class TestCountCalendarYearBillableInstallments:
    def test_august_start_counts_four(self):
        """Starting August with skip_months='7,12' counts Aug-Nov = 4."""
        from apps.billing.services import count_calendar_year_billable_installments

        plan = _make_plan(skip_months="7,12")
        assert count_calendar_year_billable_installments(plan, "2026-08") == 4

    def test_january_start_counts_ten(self):
        """Starting January with skip_months='7,12' counts 10 (skipping Jul+Dec)."""
        from apps.billing.services import count_calendar_year_billable_installments

        plan = _make_plan(skip_months="7,12")
        assert count_calendar_year_billable_installments(plan, "2026-01") == 10


# ---------------------------------------------------------------------------
# 3. partial_base_amount
# ---------------------------------------------------------------------------


class TestPartialBaseAmount:
    def test_four_installments_of_ten(self):
        """€300 / 10 installments * 4 remaining = €120.00."""
        from apps.billing.services import partial_base_amount

        plan = _make_plan(installment_count=10)
        assert partial_base_amount(plan, 4) == Decimal("120.00")

    def test_full_count_equals_annual(self):
        """Full count (10) yields the full annual amount."""
        from apps.billing.services import partial_base_amount

        plan = _make_plan(installment_count=10)
        assert partial_base_amount(plan, 10) == Decimal("300.00")


# ---------------------------------------------------------------------------
# 4. derive_installment_schedule — installment_count kwarg
# ---------------------------------------------------------------------------


class TestDeriveInstallmentScheduleWithCount:
    def test_four_rows_aug_to_nov(self):
        """A P15 record with scheduled_installment_count=4 and start August
        materializes four due dates Aug-Nov and no 2027 row."""
        from apps.billing.services import derive_installment_schedule

        plan = _make_plan(skip_months="7,12", installment_count=10)
        schedule = derive_installment_schedule(
            plan,
            Decimal("120.00"),
            first_billing_month="2026-08",
            installment_count=4,
        )
        assert len(schedule) == 4
        months = [due.month for due, _ in schedule]
        years = [due.year for due, _ in schedule]
        assert months == [8, 9, 10, 11]
        assert all(y == 2026 for y in years)

    def test_no_december_row(self):
        """The schedule never lands on a skip month."""
        from apps.billing.services import derive_installment_schedule

        plan = _make_plan(skip_months="7,12", installment_count=10)
        schedule = derive_installment_schedule(
            plan,
            Decimal("300.00"),
            first_billing_month="2026-01",
            installment_count=10,
        )
        months = {due.month for due, _ in schedule}
        assert 7 not in months
        assert 12 not in months


# ---------------------------------------------------------------------------
# 5. materialize_installments — P15 snapshot count vs legacy fallback
# ---------------------------------------------------------------------------


class TestMaterializeP15SnapshotCount:
    def test_p15_record_materializes_saved_count_only(self, member):
        """A P15 BillingRecord with scheduled_installment_count=4 and
        first_billing_month='2026-08' materializes exactly four Aug-Nov
        invoices and no 2027 row, even though the plan has 10 installments."""
        from apps.billing.models import BillingRecord
        from apps.billing.services import materialize_installments

        plan = _make_plan(skip_months="7,12", installment_count=10)
        record = BillingRecord.objects.create(
            member=member,
            plan=plan,
            season=plan.season,
            base_amount=Decimal("120.00"),
            final_amount=Decimal("120.00"),
            first_billing_month="2026-08",
            scheduled_installment_count=4,
        )

        rows = materialize_installments(record)
        assert len(rows) == 4
        assert all(r.due_date.year == 2026 for r in rows)
        assert [r.due_date.month for r in rows] == [8, 9, 10, 11]


class TestMaterializeLegacyNullCountFallback:
    def test_legacy_null_count_uses_plan_count(self, member):
        """A legacy BillingRecord with scheduled_installment_count=NULL
        materializes plan.installment_count rows (existing behavior)."""
        from apps.billing.models import BillingRecord
        from apps.billing.services import materialize_installments

        plan = _make_plan(installment_count=3, skip_months="")
        record = BillingRecord.objects.create(
            member=member,
            plan=plan,
            season=plan.season,
            base_amount=plan.annual_amount,
            final_amount=plan.annual_amount,
            first_billing_month="2026-09",
            # scheduled_installment_count intentionally left NULL/default.
        )

        rows = materialize_installments(record)
        assert len(rows) == 3


# ---------------------------------------------------------------------------
# 6. create_draft_billing_for_member — P15 partial base + P14 tier
# ---------------------------------------------------------------------------


class TestCreateDraftPartialBaseWithTier:
    def test_first_child_partial_base(self, member):
        """A signed agreement with first_billing_month='2026-08' produces a
        draft BillingRecord with scheduled_installment_count=4 and
        base_amount=€120.00 (partial base) for a single child (rank 0)."""
        from apps.agreements.models import Agreement
        from apps.billing.services import create_draft_billing_for_member

        plan = _make_plan(skip_months="7,12", installment_count=10)
        agreement = Agreement.objects.create(
            member=member,
            is_current=True,
            state=Agreement.State.SIGNED,
            billing_plan=plan,
            signed_at=timezone.now(),
            generated_at=timezone.now() - datetime.timedelta(days=1),
            first_billing_month="2026-08",
        )

        rec = create_draft_billing_for_member(member, agreement)
        assert rec is not None
        assert rec.scheduled_installment_count == 4
        assert rec.base_amount == Decimal("120.00")
        # Rank 0 → no discount; final == base.
        assert rec.final_amount == Decimal("120.00")

    def test_second_child_partial_base_with_p14_tier(self, guardian):
        """Two signed siblings: first child full partial base (€120),
        second child gets P14 50% tier → €60 final."""
        from apps.agreements.models import Agreement
        from apps.billing.models import BillingRecord
        from apps.billing.services import create_draft_billing_for_member
        from apps.members.models import Member

        plan = _make_plan(skip_months="7,12", installment_count=10)

        first = Member.objects.create(full_name="P15 First", guardian=guardian)
        first_agreement = Agreement.objects.create(
            member=first,
            is_current=True,
            state=Agreement.State.SIGNED,
            billing_plan=plan,
            signed_at=timezone.now(),
            generated_at=timezone.now() - datetime.timedelta(days=1),
            first_billing_month="2026-08",
        )
        rec1 = create_draft_billing_for_member(first, first_agreement)
        assert rec1.base_amount == Decimal("120.00")
        assert rec1.final_amount == Decimal("120.00")

        second = Member.objects.create(full_name="P15 Second", guardian=guardian)
        second_agreement = Agreement.objects.create(
            member=second,
            is_current=True,
            state=Agreement.State.SIGNED,
            billing_plan=plan,
            signed_at=timezone.now() + datetime.timedelta(hours=1),
            generated_at=timezone.now(),
            first_billing_month="2026-08",
        )
        rec2 = create_draft_billing_for_member(second, second_agreement)
        assert rec2.scheduled_installment_count == 4
        assert rec2.base_amount == Decimal("120.00")
        assert rec2.sibling_discount_percent_applied == Decimal("50.00")
        assert rec2.final_amount == Decimal("60.00")

        # Sanity: no duplicate records per (member, season).
        assert BillingRecord.objects.filter(member=first).count() == 1
        assert BillingRecord.objects.filter(member=second).count() == 1


# ---------------------------------------------------------------------------
# 7. recompute_billing_record — retains partial base
# ---------------------------------------------------------------------------


class TestRecomputeRetainsPartialBase:
    def test_recompute_uses_saved_count_not_full_annual(self, member):
        """recompute_billing_record retains the partial base derived from
        scheduled_installment_count instead of resetting to annual_amount."""
        from apps.billing.models import BillingRecord
        from apps.billing.services import recompute_billing_record

        plan = _make_plan(skip_months="7,12", installment_count=10)
        record = BillingRecord.objects.create(
            member=member,
            plan=plan,
            season=plan.season,
            base_amount=Decimal("120.00"),
            final_amount=Decimal("120.00"),
            first_billing_month="2026-08",
            scheduled_installment_count=4,
            status=BillingRecord.Status.DRAFT,
        )

        recompute_billing_record(record)
        record.refresh_from_db()
        assert record.base_amount == Decimal("120.00")
        assert record.final_amount == Decimal("120.00")


# ---------------------------------------------------------------------------
# 8. reassign_draft_billing_record — recalculates count + partial base
# ---------------------------------------------------------------------------


class TestReassignRecalculatesPartial:
    def test_reassign_recalculates_count_and_partial_base(self, member, monkeypatch):
        """Reassigning a draft to a new plan/month recalculates the
        scheduled count + partial base while preserving the stored tier
        percentage semantics."""
        from datetime import date

        from apps.billing.models import BillingRecord
        from apps.billing.services import reassign_draft_billing_record

        # Pin localdate so 2026-09 is valid (floor 2026-08 with cutoff day 20).
        monkeypatch.setattr(
            "apps.billing.services.timezone.localdate", lambda: date(2026, 7, 21)
        )

        plan_old = _make_plan(name="P15-Old", skip_months="7,12", installment_count=10)
        plan_new = _make_plan(name="P15-New", skip_months="7,12", installment_count=10)
        record = BillingRecord.objects.create(
            member=member,
            plan=plan_old,
            season=plan_old.season,
            base_amount=Decimal("120.00"),
            final_amount=Decimal("120.00"),
            first_billing_month="2026-08",
            scheduled_installment_count=4,
            status=BillingRecord.Status.DRAFT,
        )

        reassign_draft_billing_record(
            record,
            plan_new,
            first_billing_month="2026-09",
            actor=None,
        )
        record.refresh_from_db()
        assert record.plan_id == plan_new.pk
        assert record.first_billing_month == "2026-09"
        # 3 billable months in 2026 (Sep/Oct/Nov; Dec skipped) → partial base.
        assert record.scheduled_installment_count == 3
        assert record.base_amount == Decimal("90.00")


# ---------------------------------------------------------------------------
# 9. mark_agreement_signed — refuses next-year normalization
# ---------------------------------------------------------------------------


class TestSigningRefusesNextYearNormalization:
    def test_december_with_no_billable_months_raises(self, member):
        """mark_agreement_signed refuses a plan/month that normalizes into
        the next calendar year when the plan season starts in the current
        year. State stays GENERATED, no BillingRecord created."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            mark_agreement_signed,
        )
        from apps.billing.models import BillingRecord

        plan = _make_plan(
            season="2026/2027",
            skip_months="7,12",
            installment_count=10,
        )
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        agreement.billing_plan = plan
        agreement.first_billing_month = "2026-12"
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        with pytest.raises(ValueError):
            mark_agreement_signed(agreement, actor=None)

        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.GENERATED
        assert BillingRecord.objects.filter(member=member).count() == 0


# ---------------------------------------------------------------------------
# 9b. Next-year plan unblocks signing
# ---------------------------------------------------------------------------


class TestNextYearPlanUnblocksSigning:
    def test_current_year_skip_month_blocks_then_next_year_plan_succeeds(
        self, member
    ):
        """With a current-year plan that skips December, signing from
        2026-12 is refused (no billable months remain in 2026). Switching
        the agreement to an active next-year plan with
        first_billing_month='2027-01' unblocks signing and creates a
        BillingRecord with scheduled_installment_count=10."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            mark_agreement_signed,
        )
        from apps.billing.models import BillingRecord, MembershipPlan

        current_plan = MembershipPlan.objects.create(
            name="P15-Current",
            season="2026/2027",
            annual_amount=Decimal("300.00"),
            installment_count=10,
            first_installment_month=9,
            payment_due_day=20,
            skip_months="12",
            is_active=True,
        )
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        agreement.billing_plan = current_plan
        agreement.first_billing_month = "2026-12"
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        # Phase A: cannot sign from 2026-12 with current-year plan.
        with pytest.raises(ValueError):
            mark_agreement_signed(agreement, actor=None)

        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.GENERATED
        assert BillingRecord.objects.filter(member=member).count() == 0

        # Phase B: staff uses set_billing_setup to select next-year plan.
        next_plan = MembershipPlan.objects.create(
            name="P15-Next",
            season="2027/2028",
            annual_amount=Decimal("300.00"),
            installment_count=10,
            first_installment_month=1,
            payment_due_day=20,
            skip_months="7,12",
            is_active=True,
        )
        from apps.agreements.services import set_billing_setup

        set_billing_setup(agreement, next_plan, "2027-01", actor=None)
        agreement.refresh_from_db()
        # Assert normalized month/plan persisted via service path.
        assert agreement.billing_plan_id == next_plan.pk
        assert agreement.first_billing_month == "2027-01"

        mark_agreement_signed(agreement, actor=None)
        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.SIGNED

        record = BillingRecord.objects.filter(member=member).first()
        assert record is not None
        assert record.scheduled_installment_count == 10


# ---------------------------------------------------------------------------
# 15. count_calendar_year_billable_installments — caps at plan installment_count
# ---------------------------------------------------------------------------


class TestCountCapsAtInstallmentCount:
    def test_one_installment_plan_counts_one_not_three(self):
        """A plan with installment_count=1, start September, skip July/December
        has ONE scheduled installment, not Sep/Oct/Nov. Count must cap at the
        plan's actual scheduled installments, not count every non-skip month
        through December. Otherwise partial base can exceed annual amount
        (€400 * 3 / 1 = €1200), violating the formula."""
        from apps.billing.services import (
            count_calendar_year_billable_installments,
            partial_base_amount,
        )

        plan = _make_plan(
            annual_amount=Decimal("400.00"),
            installment_count=1,
            first_installment_month=9,
            skip_months="7,12",
        )
        count = count_calendar_year_billable_installments(plan, "2026-09")
        assert count == 1
        assert partial_base_amount(plan, count) == Decimal("400.00")


# ---------------------------------------------------------------------------
# 9c. No-backdating — set_billing_setup enforces cutoff-derived floor
# ---------------------------------------------------------------------------


@pytest.fixture
def pinned_today_and_plan(member, monkeypatch):
    """Shared setup for no-backdating tests: pins today to 2026-08-21 and
    creates a plan with cutoff day 20 (so cutoff-derived month is 2026-09)
    and skip_months="8" (so "2026-08" normalizes to "2026-09")."""
    from datetime import date

    from apps.agreements.models import Agreement
    from apps.agreements.services import create_agreement_for_member
    from apps.billing.models import MembershipPlan

    monkeypatch.setattr(
        "apps.billing.services.timezone.localdate",
        lambda: date(2026, 8, 21),
    )

    plan = MembershipPlan.objects.create(
        name="P15-NoBackdate",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        payment_due_day=20,
        billing_start_cutoff_day=20,
        skip_months="8",  # August skipped → "2026-08" normalizes to "2026-09"
        is_active=True,
    )
    agreement = create_agreement_for_member(
        member, signing_path=Agreement.SigningPath.PAPER
    )
    return plan, agreement


class TestNoBackdating:
    def test_set_billing_setup_rejects_month_before_cutoff_derived(
        self, pinned_today_and_plan
    ):
        """Pinned today = 2026-08-21, cutoff day = 20 → cutoff-derived
        month is 2026-09. set_billing_setup with a month earlier than the
        cutoff-derived month raises ValueError and does not mutate the
        agreement or emit a BILLING_PLAN_ASSIGNED audit event."""
        from apps.agreements.services import set_billing_setup
        from apps.core.models import AuditEvent

        plan, agreement = pinned_today_and_plan

        with pytest.raises(ValueError):
            set_billing_setup(agreement, plan, "2026-06", actor=None)

        agreement.refresh_from_db()
        assert agreement.billing_plan_id is None
        assert agreement.first_billing_month == ""
        assert not AuditEvent.objects.filter(
            action=str(AuditEvent.Action.BILLING_PLAN_ASSIGNED)
        ).exists()

    def test_skipped_raw_month_normalizes_to_cutoff_derived_floor(
        self, pinned_today_and_plan
    ):
        """A raw month that normalizes (via plan skip_months) to the
        cutoff-derived month remains valid and is persisted as the
        normalized value."""
        from apps.agreements.services import set_billing_setup

        plan, agreement = pinned_today_and_plan

        set_billing_setup(agreement, plan, "2026-08", actor=None)
        agreement.refresh_from_db()
        assert agreement.first_billing_month == "2026-09"
        assert agreement.billing_plan_id == plan.pk


# ---------------------------------------------------------------------------
# 9d. Manual override materialization — splits across saved count
# ---------------------------------------------------------------------------


class TestManualOverrideMaterialization:
    def test_manual_override_splits_across_saved_count(self, member):
        """A P15 record with manual_amount_override=€100.00 and
        scheduled_installment_count=4 materializes exactly four invoice
        rows, each €25.00. The override is persisted and used as the
        final total."""
        from apps.billing.models import BillingRecord
        from apps.billing.services import materialize_installments

        plan = _make_plan(skip_months="7,12", installment_count=10)
        record = BillingRecord.objects.create(
            member=member,
            plan=plan,
            season=plan.season,
            base_amount=Decimal("300.00"),
            final_amount=Decimal("100.00"),
            manual_amount_override=Decimal("100.00"),
            manual_override_reason="Test override",
            first_billing_month="2026-08",
            scheduled_installment_count=4,
        )

        # Assert the override is persisted before materialization.
        record.refresh_from_db()
        assert record.manual_amount_override == Decimal("100.00")

        rows = materialize_installments(record)
        assert len(rows) == 4
        assert all(r.amount == Decimal("25.00") for r in rows)


# ---------------------------------------------------------------------------
# 10. P15 approved formula — partial base when first_billing_month matches
#     plan.first_installment_month (no "< first_installment_month" exception)
# ---------------------------------------------------------------------------


class TestApprovedFormulaPartialBaseOnPlanStartMonth:
    def test_first_child_september_start_equals_plan_start_is_partial(
        self, member
    ):
        """P15 approved formula: when first_billing_month matches
        plan.first_installment_month, the calendar-year partial base still
        applies. With plan first_installment_month=9, skip_months='7,12',
        installment_count=10, annual=€300, and agreement
        first_billing_month='2026-09', the calendar-year count is 3
        (Sep/Oct/Nov; Dec skipped). base = €300 * 3 / 10 = €90.00. final =
        €90.00 for first child (rank 0)."""
        from apps.agreements.models import Agreement
        from apps.billing.services import create_draft_billing_for_member

        plan = _make_plan(
            skip_months="7,12",
            installment_count=10,
            first_installment_month=9,
        )
        agreement = Agreement.objects.create(
            member=member,
            is_current=True,
            state=Agreement.State.SIGNED,
            billing_plan=plan,
            signed_at=timezone.now(),
            generated_at=timezone.now() - datetime.timedelta(days=1),
            first_billing_month="2026-09",
        )

        rec = create_draft_billing_for_member(member, agreement)
        assert rec is not None
        assert rec.scheduled_installment_count == 3
        assert rec.base_amount == Decimal("90.00")
        assert rec.final_amount == Decimal("90.00")


# ---------------------------------------------------------------------------
# 11. reassign_draft_billing_record — legacy NULL count transforms on
#     explicit reassignment with plan + month
# ---------------------------------------------------------------------------


class TestReassignLegacyNullCountTransforms:
    def test_reassign_with_plan_and_month_transforms_legacy_draft(self, member):
        """Explicit reassignment of a legacy (scheduled_installment_count=NULL)
        DRAFT BillingRecord with a new plan + first_billing_month='2026-08'
        recalculates count=4 (Aug-Nov; Dec skipped) and partial base
        €300 * 4 / 10 = €120.00. The saved count is updated from NULL to 4."""
        from apps.billing.models import BillingRecord
        from apps.billing.services import reassign_draft_billing_record

        plan_old = _make_plan(name="P15-Legacy", skip_months="7,12", installment_count=10)
        plan_new = _make_plan(name="P15-New", skip_months="7,12", installment_count=10)
        record = BillingRecord.objects.create(
            member=member,
            plan=plan_old,
            season=plan_old.season,
            base_amount=Decimal("300.00"),
            final_amount=Decimal("300.00"),
            first_billing_month="",
            # Legacy: scheduled_installment_count intentionally left NULL.
            status=BillingRecord.Status.DRAFT,
        )
        assert record.scheduled_installment_count is None

        reassign_draft_billing_record(
            record,
            plan_new,
            first_billing_month="2026-08",
            actor=None,
        )
        record.refresh_from_db()
        assert record.plan_id == plan_new.pk
        assert record.first_billing_month == "2026-08"
        assert record.scheduled_installment_count == 4
        assert record.base_amount == Decimal("120.00")
        assert record.final_amount == Decimal("120.00")


# ---------------------------------------------------------------------------
# 12. set_billing_setup — blank first_billing_month raises
# ---------------------------------------------------------------------------


class TestSetBillingSetupRejectsBlankMonth:
    def test_blank_first_billing_month_raises(self, member):
        """set_billing_setup with a valid active plan but blank
        first_billing_month='' raises ValueError, preserves any prior
        agreement plan/month, and emits no BILLING_PLAN_ASSIGNED audit."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            set_billing_setup,
        )
        from apps.core.models import AuditEvent

        plan = _make_plan()
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        # Pre-set a known plan/month so preservation is observable.
        agreement.billing_plan = plan
        agreement.first_billing_month = "2026-09"
        agreement.save(update_fields=["billing_plan", "first_billing_month"])
        prior_plan_id = agreement.billing_plan_id
        prior_month = agreement.first_billing_month

        with pytest.raises(ValueError):
            set_billing_setup(agreement, plan, first_billing_month="", actor=None)

        agreement.refresh_from_db()
        assert agreement.billing_plan_id == prior_plan_id
        assert agreement.first_billing_month == prior_month
        assert not AuditEvent.objects.filter(
            action=str(AuditEvent.Action.BILLING_PLAN_ASSIGNED),
            target_id=agreement.pk,
        ).exists()


# ---------------------------------------------------------------------------
# 13. mark_agreement_signed — blank first_billing_month raises
# ---------------------------------------------------------------------------


class TestMarkSignedRejectsBlankMonth:
    def test_blank_month_with_plan_raises(self, member):
        """mark_agreement_signed for an agreement that has a billing_plan but
        blank first_billing_month raises before any state mutation or
        BillingRecord creation."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            mark_agreement_signed,
        )
        from apps.billing.models import BillingRecord

        plan = _make_plan()
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        agreement.billing_plan = plan
        agreement.first_billing_month = ""
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        with pytest.raises(ValueError):
            mark_agreement_signed(agreement, actor=None)

        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.GENERATED
        assert BillingRecord.objects.filter(member=member).count() == 0


# ---------------------------------------------------------------------------
# 14. Inactive-plan guard — set_billing_setup and mark_agreement_signed
# ---------------------------------------------------------------------------


class TestInactivePlanGuard:
    def test_set_billing_setup_rejects_inactive_plan(self, member):
        """set_billing_setup called directly with an inactive plan raises
        before any mutation, even with a valid first_billing_month."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            set_billing_setup,
        )
        from apps.billing.models import MembershipPlan

        inactive_plan = MembershipPlan.objects.create(
            name="Inactive",
            season="2026/2027",
            annual_amount=Decimal("300.00"),
            installment_count=10,
            first_installment_month=9,
            is_active=False,
        )
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )

        with pytest.raises(ValueError):
            set_billing_setup(
                agreement, inactive_plan, first_billing_month="2026-09", actor=None
            )

        agreement.refresh_from_db()
        assert agreement.billing_plan_id is None
        assert agreement.first_billing_month == ""

    def test_mark_signed_rejects_inactive_plan(self, member):
        """mark_agreement_signed for a generated agreement referencing an
        inactive plan + valid month raises before state/BillingRecord
        mutation."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            mark_agreement_signed,
        )
        from apps.billing.models import BillingRecord, MembershipPlan

        inactive_plan = MembershipPlan.objects.create(
            name="Inactive-Sign",
            season="2026/2027",
            annual_amount=Decimal("300.00"),
            installment_count=10,
            first_installment_month=9,
            is_active=False,
        )
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        agreement.billing_plan = inactive_plan
        agreement.first_billing_month = "2026-09"
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        with pytest.raises(ValueError):
            mark_agreement_signed(agreement, actor=None)

        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.GENERATED
        assert BillingRecord.objects.filter(member=member).count() == 0

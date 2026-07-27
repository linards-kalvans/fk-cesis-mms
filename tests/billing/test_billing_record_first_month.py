"""P9: Invoice materialization uses BillingRecord.first_billing_month when
present, falls back to plan.first_installment_month when blank."""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    return make_guardian(full_name="Anna Bērziņa", email="anna-mat@example.test")


def _make_plan(**overrides):
    from apps.billing.models import MembershipPlan

    defaults = dict(
        name="Plan-Mat",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=3,
        first_installment_month=9,
        is_active=True,
    )
    defaults.update(overrides)
    plan = MembershipPlan(**defaults)
    plan.billing_start_cutoff_day = defaults.pop("billing_start_cutoff_day", 20)
    plan.save()
    return plan


def _make_record(member, plan, *, first_billing_month=""):
    from apps.billing.models import BillingRecord

    rec = BillingRecord.objects.create(
        member=member,
        plan=plan,
        season=plan.season,
        base_amount=plan.annual_amount,
        final_amount=plan.annual_amount,
    )
    rec.first_billing_month = first_billing_month
    rec.save(update_fields=["first_billing_month"])
    return rec


# ── C1: materialize_installments uses BillingRecord.first_billing_month ──


class TestMaterializeUsesFirstBillingMonth:
    def test_due_dates_start_from_first_billing_month(self, guardian):
        """When BillingRecord.first_billing_month is set, materialized
        invoice due dates start from that month, not plan.first_installment_month."""
        from apps.members.models import Member
        from apps.billing.services import materialize_installments

        member = Member.objects.create(full_name="Test Child", guardian=guardian)
        plan = _make_plan(
            first_installment_month=9,
            installment_count=3,
            payment_due_day=20,
            skip_months="7,12",
        )
        record = _make_record(member, plan, first_billing_month="2026-03")

        rows = materialize_installments(record)
        assert len(rows) == 3
        # First invoice due in March (not September).
        assert rows[0].due_date.month == 3
        assert rows[0].due_date.year == 2026
        assert rows[1].due_date.month == 4
        assert rows[2].due_date.month == 5


# ── C2: blank first_billing_month falls back to plan behavior ───────────


class TestMaterializeFallbackToPlanSchedule:
    def test_blank_first_month_uses_plan_first_installment_month(self, guardian):
        """When BillingRecord.first_billing_month is blank, materialization
        falls back to plan.first_installment_month (existing behavior)."""
        from apps.members.models import Member
        from apps.billing.services import materialize_installments

        member = Member.objects.create(full_name="Test Child 2", guardian=guardian)
        plan = _make_plan(
            first_installment_month=9,
            installment_count=3,
            payment_due_day=20,
            skip_months="7,12",
        )
        record = _make_record(member, plan, first_billing_month="")

        rows = materialize_installments(record)
        assert len(rows) == 3
        # First invoice due in September (plan.first_installment_month).
        assert rows[0].due_date.month == 9


# ── P14 regression: blank first_billing_month stays blank on the record ─
#
# P14 must not mutate the P9 snapshot contract: a blank caller/agreement
# `first_billing_month` is stored verbatim as `""` on the record. The
# schedule calculation (`derive_installment_schedule`) still falls back to
# the plan's first_installment_month when blank, so the tier-rank and
# due-date computations are unaffected. Only the stored value must
# remain blank.


class TestBlankFirstBillingMonthStaysBlank:
    def test_create_draft_stores_blank_when_agreement_has_blank(
        self, active_plan, guardian
    ):
        """A signed agreement with ``first_billing_month=""`` must produce
        a BillingRecord whose ``first_billing_month`` is also ``""`` —
        the P9 snapshot contract stores the value verbatim."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.agreements.models import Agreement
        from apps.billing.services import create_draft_billing_for_member
        from apps.members.models import Member

        member = Member.objects.create(full_name="Blank-month child", guardian=guardian)
        agreement = Agreement.objects.create(
            member=member,
            is_current=True,
            state=Agreement.State.SIGNED,
            billing_plan=active_plan,
            signed_at=timezone.now(),
            generated_at=timezone.now() - timedelta(days=1),
            first_billing_month="",
        )

        rec = create_draft_billing_for_member(member, agreement)

        assert rec is not None
        assert rec.first_billing_month == "", (
            f"expected blank, got {rec.first_billing_month!r}"
        )

    def test_renew_stores_blank_when_caller_passes_blank(
        self, active_plan, guardian
    ):
        """``renew_member_billing(..., first_billing_month="")`` must
        store ``""`` verbatim on the record."""
        from datetime import timedelta

        from django.utils import timezone

        from apps.agreements.models import Agreement
        from apps.billing.services import renew_member_billing
        from apps.members.models import Member

        # An existing signed agreement so the renewal member has a
        # current signed cohort to rank against.
        existing, _ = (
            Member.objects.create(full_name="Existing", guardian=guardian),
            None,
        )
        Agreement.objects.create(
            member=existing,
            is_current=True,
            state=Agreement.State.SIGNED,
            billing_plan=active_plan,
            signed_at=timezone.now() - timedelta(days=1),
            generated_at=timezone.now() - timedelta(days=2),
        )

        target = Member.objects.create(full_name="Renewal target", guardian=guardian)
        rec = renew_member_billing(target, active_plan, first_billing_month="")

        assert rec is not None
        assert rec.first_billing_month == "", (
            f"expected blank, got {rec.first_billing_month!r}"
        )

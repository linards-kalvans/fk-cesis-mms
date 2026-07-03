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

import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_schedule_count_and_sum(active_plan):
    from apps.billing.services import derive_installment_schedule

    schedule = derive_installment_schedule(active_plan, Decimal("300.00"))
    assert len(schedule) == 10
    assert sum(amount for _, amount in schedule) == Decimal("300.00")


def test_schedule_remainder_in_last_entry():
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan(
        name="x", season="2026/2027", installment_count=3, first_installment_month=9
    )
    schedule = derive_installment_schedule(plan, Decimal("100.00"))
    amounts = [a for _, a in schedule]
    assert amounts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


def test_schedule_months_advance_and_wrap():
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan(
        name="x", season="2026/2027", installment_count=5, first_installment_month=11
    )
    schedule = derive_installment_schedule(plan, Decimal("50.00"))
    months = [due.month for due, _ in schedule]
    assert months == [11, 12, 1, 2, 3]

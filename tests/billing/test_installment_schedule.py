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
        name="x", season="2026/2027", installment_count=5, first_installment_month=11,
        skip_months="", payment_due_day=1,
    )
    schedule = derive_installment_schedule(plan, Decimal("50.00"))
    months = [due.month for due, _ in schedule]
    assert months == [11, 12, 1, 2, 3]


def test_schedule_skips_july_and_december(db):
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=10,
        first_installment_month=1, skip_months="7,12", payment_due_day=20,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    assert [d.month for d, _ in sched] == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11]
    assert all(d.day == 20 for d, _ in sched)
    assert all(d.year == 2027 for d, _ in sched)
    assert [a for _, a in sched] == [Decimal("30.00")] * 10
    assert sum(a for _, a in sched) == Decimal("300.00")


def test_schedule_due_day_clamped_to_month_length(db):
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=3,
        first_installment_month=1, skip_months="", payment_due_day=31,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    # Jan 31, Feb 28 (2027 not leap), Mar 31
    assert [(d.month, d.day) for d, _ in sched] == [(1, 31), (2, 28), (3, 31)]


def test_schedule_wraps_year_skipping_december(db):
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=3,
        first_installment_month=11, skip_months="12", payment_due_day=20,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    # Nov 2027, (skip Dec), Jan 2028, Feb 2028
    assert [(d.year, d.month) for d, _ in sched] == [(2027, 11), (2028, 1), (2028, 2)]


def test_schedule_skips_when_first_month_is_a_skip_month():
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=2,
        first_installment_month=7, skip_months="7", payment_due_day=20,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    # July is skipped even as the start month -> Aug, Sep
    assert [d.month for d, _ in sched] == [8, 9]


def test_schedule_all_months_skipped_raises():
    import pytest
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=1,
        first_installment_month=1, skip_months="1,2,3,4,5,6,7,8,9,10,11,12",
        payment_due_day=20,
    )
    with pytest.raises(ValueError):
        derive_installment_schedule(plan, Decimal("300.00"))

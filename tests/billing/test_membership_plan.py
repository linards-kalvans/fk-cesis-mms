import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_membership_plan_defaults():
    from apps.billing.models import MembershipPlan

    plan = MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        installment_count=10,
        first_installment_month=9,
    )
    assert plan.currency == "EUR"
    assert plan.annual_amount == Decimal("300.00")
    # P14: sibling_discount_percent field removed from MembershipPlan.
    assert not hasattr(MembershipPlan, "sibling_discount_percent")
    # P14: sibling_discount_percent_applied retained on BillingRecord.
    from apps.billing.models import BillingRecord
    assert hasattr(BillingRecord, "sibling_discount_percent_applied")
    assert plan.is_active is False
    assert str(plan) == "Sezona 2026/2027"
    assert plan.created_at is not None
    assert plan.updated_at is not None


def test_schedule_fields_defaults_and_skip_months_list(db):
    from apps.billing.models import MembershipPlan

    p = MembershipPlan.objects.create(name="P", season="2027")
    assert p.payment_due_day == 20
    assert p.skip_months == "7,12"
    assert p.skip_months_list == [7, 12]


def test_skip_months_list_parsing_is_tolerant(db):
    from apps.billing.models import MembershipPlan

    p = MembershipPlan.objects.create(name="P", season="2027", skip_months=" 7 , 12 ,, 13, x ")
    # whitespace tolerated; out-of-range / non-numeric dropped; sorted-unique
    assert p.skip_months_list == [7, 12]
    p2 = MembershipPlan.objects.create(name="P2", season="2027", skip_months="")
    assert p2.skip_months_list == []

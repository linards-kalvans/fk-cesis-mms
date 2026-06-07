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
    assert plan.sibling_discount_percent == Decimal("0.00")
    assert plan.is_active is False
    assert str(plan) == "Sezona 2026/2027"

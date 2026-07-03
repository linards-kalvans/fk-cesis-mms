import pytest
from decimal import Decimal
from django.db import IntegrityError

pytestmark = pytest.mark.django_db


def test_billing_record_final_amount_uses_override(active_plan, member):
    from apps.billing.models import BillingRecord

    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=Decimal("300.00"),
        is_full_price=True,
        sibling_discount_percent_applied=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
    )
    assert rec.status == BillingRecord.Status.DRAFT
    assert rec.manual_amount_override is None
    assert rec.final_amount == Decimal("300.00")


def test_one_record_per_member_per_season(active_plan, member):
    from apps.billing.models import BillingRecord

    BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), is_full_price=True,
        sibling_discount_percent_applied=Decimal("0.00"),
        discount_amount=Decimal("0.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
    )
    with pytest.raises(IntegrityError):
        BillingRecord.objects.create(
            member=member, plan=active_plan, season="2026/2027",
            base_amount=Decimal("300.00"), is_full_price=True,
            sibling_discount_percent_applied=Decimal("0.00"),
            discount_amount=Decimal("0.00"), final_amount=Decimal("300.00"),
            payment_mode=BillingRecord.PaymentMode.UPFRONT,
        )

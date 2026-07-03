"""BillingInvoice.sent_at field (set when the issue+email succeeds)."""

import pytest

pytestmark = pytest.mark.django_db


def test_sent_at_defaults_to_none(active_plan, guardian):
    from decimal import Decimal
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.CONFIRMED,
    )
    inv = BillingInvoice.objects.create(
        billing_record=rec, sequence=0, due_date=rec.created_at.date(),
        amount=Decimal("300.00"),
    )
    inv.refresh_from_db()
    assert inv.sent_at is None

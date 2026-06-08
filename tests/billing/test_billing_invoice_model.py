import pytest
from decimal import Decimal
from datetime import date

pytestmark = pytest.mark.django_db


def test_guardian_and_plan_and_record_external_fields(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    assert guardian.external_client_id == ""
    assert active_plan.external_product_id == ""
    assert rec.external_status == ""
    assert rec.external_error_code == ""


def test_billing_invoice_unique_per_sequence(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice
    from django.db import IntegrityError

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1), amount=Decimal("30.00")
    )
    with pytest.raises(IntegrityError):
        BillingInvoice.objects.create(
            billing_record=rec, sequence=1, due_date=date(2026, 10, 1), amount=Decimal("30.00")
        )


def test_payment_projection_fields_default_blank(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    bi = BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1), amount=Decimal("30.00"),
    )
    assert bi.payment_status == ""
    assert bi.paid_to_date == Decimal("0.00")
    assert bi.balance is None
    assert bi.last_payment_date is None
    assert bi.last_synced_at is None
    assert rec.payment_status == ""
    assert rec.payment_synced_at is None

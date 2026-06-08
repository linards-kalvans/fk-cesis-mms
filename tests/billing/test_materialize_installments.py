import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, payment_mode, final):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal(final),
        payment_mode=payment_mode,
    )


def test_product_key_from_season(active_plan):
    from apps.billing.services import membership_plan_product_key

    assert membership_plan_product_key(active_plan) == "biedra-maksa-2026-2027"


def test_installments_create_ten_rows(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.billing.services import materialize_installments

    rec = _record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS, "300.00")
    rows = materialize_installments(rec)
    assert len(rows) == 10
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10
    assert sum(r.amount for r in rows) == Decimal("300.00")
    assert [r.sequence for r in rows] == list(range(1, 11))


def test_upfront_creates_single_row(active_plan, guardian):
    from apps.billing.models import BillingRecord
    from apps.billing.services import materialize_installments

    rec = _record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT, "300.00")
    rows = materialize_installments(rec)
    assert len(rows) == 1
    assert rows[0].amount == Decimal("300.00")


def test_materialize_is_idempotent(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.billing.services import materialize_installments

    rec = _record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS, "300.00")
    materialize_installments(rec)
    materialize_installments(rec)
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10

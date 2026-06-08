import pytest
from datetime import date
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record_with_invoices(active_plan, guardian, statuses):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    for i, status in enumerate(statuses, start=1):
        BillingInvoice.objects.create(
            billing_record=rec, sequence=i, due_date=date(2026, 9, i),
            amount=Decimal("30.00"), payment_status=status,
        )
    return rec


def test_all_paid_rolls_up_to_paid(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["paid", "paid"])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PAID
    assert rec.payment_synced_at is not None


def test_some_paid_rolls_up_to_partial(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["paid", "unpaid"])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PARTIAL


def test_partial_invoice_rolls_up_to_partial(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["partial", "unpaid"])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PARTIAL


def test_none_paid_rolls_up_to_unpaid(active_plan, guardian):
    from apps.billing.services import roll_up_payment_status
    from apps.billing.models import PaymentStatus

    rec = _record_with_invoices(active_plan, guardian, ["unpaid", ""])
    roll_up_payment_status(rec)
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.UNPAID

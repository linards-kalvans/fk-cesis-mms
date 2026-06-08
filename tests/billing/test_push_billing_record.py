import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _confirmed_record(active_plan, guardian, payment_mode):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=payment_mode, status=BillingRecord.Status.CONFIRMED,
    )


def test_push_creates_invoices_and_marks_synced(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations.tasks import push_billing_record

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS)
    push_billing_record(rec.pk)

    rec.refresh_from_db()
    guardian.refresh_from_db()
    active_plan.refresh_from_db()
    assert rec.external_status == "synced"
    assert active_plan.external_product_id == f"stub-product-{active_plan.pk}"
    assert guardian.external_client_id == f"stub-client-{guardian.pk}"
    rows = BillingInvoice.objects.filter(billing_record=rec)
    assert rows.count() == 10
    assert all(r.external_invoice_id and r.external_status == "created" for r in rows)


def test_push_is_idempotent(active_plan, guardian):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations.tasks import push_billing_record

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS)
    push_billing_record(rec.pk)
    push_billing_record(rec.pk)
    assert BillingInvoice.objects.filter(billing_record=rec).count() == 10
    rec.refresh_from_db()
    assert rec.external_status == "synced"


def test_transient_failure_marks_failed_and_raises(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT)

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformTransientError("down")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    with pytest.raises(tasks.RetryableInvoiceError):
        tasks.push_billing_record(rec.pk)
    rec.refresh_from_db()
    assert rec.external_status == "failed"
    assert rec.external_error_code == "unavailable"


def test_terminal_failure_marks_failed_no_raise(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks

    rec = _confirmed_record(active_plan, guardian, BillingRecord.PaymentMode.UPFRONT)

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformAuthError("401")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    tasks.push_billing_record(rec.pk)  # must NOT raise
    rec.refresh_from_db()
    assert rec.external_status == "failed"
    assert rec.external_error_code == "auth_failed"

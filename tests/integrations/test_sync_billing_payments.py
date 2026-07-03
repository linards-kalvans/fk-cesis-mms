import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def _confirmed_record_with_invoices(active_plan, guardian, external_ids):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    for i, ext in enumerate(external_ids, start=1):
        BillingInvoice.objects.create(
            billing_record=rec, sequence=i, due_date=date(2026, 9, i),
            amount=Decimal("30.00"), external_invoice_id=ext,
        )
    return rec


def _payment(status="paid", paid="30.00", balance="0.00", dt=None):
    from apps.integrations.invoice_platform import PaymentResult

    return PaymentResult(
        external_invoice_id="x", payment_status=status,
        amount=Decimal("30.00"), paid_to_date=Decimal(paid),
        balance=Decimal(balance), last_payment_date=dt,
    )


def test_batch_sweep_writes_projection_and_rolls_up(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_payments
    from apps.billing.models import PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1", "inv-2"])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(dt=date(2026, 9, 12)),
    ):
        sync_billing_payments()
    rec.refresh_from_db()
    assert rec.payment_status == PaymentStatus.PAID
    assert rec.payment_synced_at is not None
    inv = rec.invoices.first()
    assert inv.payment_status == "paid"
    assert inv.paid_to_date == Decimal("30.00")
    assert inv.last_payment_date == date(2026, 9, 12)
    assert inv.last_synced_at is not None


def test_batch_sweep_skips_invoices_without_external_id(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_payments

    rec = _confirmed_record_with_invoices(active_plan, guardian, [""])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=AssertionError("should not be called"),
    ):
        sync_billing_payments()  # must not raise / not call fetch
    rec.refresh_from_db()
    assert rec.payment_synced_at is None


def test_batch_sweep_isolates_per_row_errors(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_payments
    from apps.integrations.invoice_platform import InvoicePlatformTransientError
    from apps.billing.models import PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1", "inv-2"])
    calls = {"n": 0}

    def _side_effect(external_id):
        calls["n"] += 1
        if external_id == "inv-1":
            raise InvoicePlatformTransientError("boom")
        return _payment()

    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=_side_effect,
    ):
        sync_billing_payments()  # one bad row must not abort the sweep
    rec.refresh_from_db()
    assert calls["n"] == 2
    assert rec.payment_status == PaymentStatus.PARTIAL


def test_manual_record_sync_surfaces_terminal_error(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_record_payments
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=InvoicePlatformAuthError("nope"),
    ):
        sync_billing_record_payments(rec.pk)
    rec.refresh_from_db()
    assert rec.payment_error_code == "auth_failed"


def test_manual_record_sync_retryable_raises(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_record_payments, RetryableInvoiceError
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        side_effect=InvoicePlatformTransientError("later"),
    ):
        with pytest.raises(RetryableInvoiceError):
            sync_billing_record_payments(rec.pk)


def test_manual_record_sync_success_clears_error_and_rolls_up(active_plan, guardian):
    from apps.integrations.tasks import sync_billing_record_payments
    from apps.billing.models import BillingRecord, PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    BillingRecord.objects.filter(pk=rec.pk).update(payment_error_code="auth_failed")
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(),
    ):
        sync_billing_record_payments(rec.pk)
    rec.refresh_from_db()
    assert rec.payment_error_code == ""
    assert rec.payment_status == PaymentStatus.PAID


def test_manual_record_sync_does_not_clear_push_error(active_plan, guardian):
    """A successful payment read-back must NOT erase a push-side failure signal
    (external_error_code is the push health field, not the read-back one)."""
    from apps.integrations.tasks import sync_billing_record_payments
    from apps.billing.models import BillingRecord, PaymentStatus

    rec = _confirmed_record_with_invoices(active_plan, guardian, ["inv-1"])
    BillingRecord.objects.filter(pk=rec.pk).update(
        external_status="failed", external_error_code="misconfigured"
    )
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(),
    ):
        sync_billing_record_payments(rec.pk)
    rec.refresh_from_db()
    assert rec.external_error_code == "misconfigured"  # push signal preserved
    assert rec.external_status == "failed"
    assert rec.payment_status == PaymentStatus.PAID  # read-back still worked

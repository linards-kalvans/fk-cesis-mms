"""P7 audit baseline — billing staff actions + push/send/sync failures."""

import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, status, external_status="", payment_mode=None):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    kwargs = dict(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=status, external_status=external_status,
    )
    if payment_mode is not None:
        kwargs["payment_mode"] = payment_mode
    return BillingRecord.objects.create(**kwargs)


def _admin_request():
    from django.contrib.auth import get_user_model
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    staff = get_user_model().objects.create_user(
        username="staff", email="staff@example.com", password="x", is_staff=True
    )
    request = RequestFactory().post("/admin/")
    request.user = staff
    request.session = {}
    request._messages = FallbackStorage(request)
    return request, staff


def test_push_action_records_billing_push_triggered(active_plan, guardian):
    from unittest.mock import patch
    from django.contrib.admin.sites import AdminSite
    from apps.billing.admin import BillingRecordAdmin
    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent

    confirmed = _record(active_plan, guardian, BillingRecord.Status.CONFIRMED)
    _record(active_plan, guardian, BillingRecord.Status.DRAFT)

    admin = BillingRecordAdmin(BillingRecord, AdminSite())
    request, staff = _admin_request()
    with patch("apps.integrations.tasks.enqueue_push_billing_record"):
        admin.push_to_invoice_ninja(request, BillingRecord.objects.all())

    events = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED)
    )
    assert events.count() == 1
    event = events.get()
    assert event.actor_id == staff.pk
    assert event.target_id == str(confirmed.pk)


def test_sync_payments_action_records_payment_sync_triggered(active_plan, guardian):
    from unittest.mock import patch
    from django.contrib.admin.sites import AdminSite
    from apps.billing.admin import BillingRecordAdmin
    from apps.billing.models import BillingRecord
    from apps.core.models import AuditEvent

    confirmed = _record(active_plan, guardian, BillingRecord.Status.CONFIRMED)
    _record(active_plan, guardian, BillingRecord.Status.DRAFT)

    admin = BillingRecordAdmin(BillingRecord, AdminSite())
    request, staff = _admin_request()
    with patch("apps.integrations.tasks.enqueue_sync_billing_record_payments"):
        admin.sync_payments(request, BillingRecord.objects.all())

    events = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.PAYMENT_SYNC_TRIGGERED)
    )
    assert events.count() == 1
    event = events.get()
    assert event.actor_id == staff.pk
    assert event.target_id == str(confirmed.pk)


def test_push_terminal_failure_records_invoice_push_failed(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_platform
    from apps.integrations import tasks
    from apps.core.models import AuditEvent

    rec = _record(
        active_plan, guardian, BillingRecord.Status.CONFIRMED,
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
    )

    def boom(record, billing_invoice):
        raise invoice_platform.InvoicePlatformAuthError("401")

    monkeypatch.setattr(invoice_platform, "create_invoice", boom)
    tasks.push_billing_record(rec.pk)

    events = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.INVOICE_PUSH_FAILED)
    )
    assert events.count() >= 1
    event = events.first()
    assert event.target_id == str(rec.pk)
    assert event.metadata["error_code"] == "auth_failed"


def test_payment_sync_terminal_failure_records_payment_sync_failed(active_plan, guardian, monkeypatch):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations import invoice_platform
    from apps.integrations import tasks
    from apps.core.models import AuditEvent

    rec = _record(active_plan, guardian, BillingRecord.Status.CONFIRMED)
    BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date="2026-09-01",
        amount=Decimal("30.00"), external_invoice_id="ext-1",
        external_status="created",
    )

    def boom(external_id):
        raise invoice_platform.InvoicePlatformAuthError("401")

    monkeypatch.setattr(invoice_platform, "fetch_invoice_payment", boom)
    tasks.sync_billing_record_payments(rec.pk)

    events = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.PAYMENT_SYNC_FAILED)
    )
    assert events.count() == 1
    event = events.get()
    assert event.target_id == str(rec.pk)
    assert event.metadata["error_code"] == "auth_failed"


def test_send_failure_records_invoice_send_failed(active_plan, guardian, monkeypatch, settings):
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.integrations import invoice_platform
    from apps.integrations import tasks
    from apps.core.models import AuditEvent

    settings.BILLING_AUTOSEND_ENABLED = True
    rec = _record(active_plan, guardian, BillingRecord.Status.CONFIRMED)
    inv = BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date="2026-09-01",
        amount=Decimal("30.00"), external_invoice_id="ext-1",
        external_status="created",
    )

    monkeypatch.setattr(tasks, "is_invoice_due_to_send", lambda *a, **k: True, raising=False)
    import apps.billing.services as services
    monkeypatch.setattr(services, "is_invoice_due_to_send", lambda *a, **k: True)

    def boom(external_id):
        raise invoice_platform.InvoicePlatformAuthError("401")

    monkeypatch.setattr(invoice_platform, "email_invoice", boom)
    tasks.send_due_invoices()

    events = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.INVOICE_SEND_FAILED)
    )
    assert events.count() == 1
    event = events.get()
    assert event.metadata["error_code"] == "auth_failed"
    assert event.target_id in (str(rec.pk), str(inv.pk))

"""send_due_invoices — nightly issue+email sweep."""

import datetime
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _months_ahead(d: datetime.date, n: int) -> datetime.date:
    m = d.month - 1 + n
    y = d.year + m // 12
    return datetime.date(y, m % 12 + 1, 20)


def _draft_invoice(active_plan, guardian, *, due_date, external_id="inv-1", status="created"):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.INSTALLMENTS,
        status=BillingRecord.Status.CONFIRMED, external_status="synced",
    )
    return BillingInvoice.objects.create(
        billing_record=rec, sequence=0, due_date=due_date, amount=Decimal("30.00"),
        external_invoice_id=external_id, external_status=status,
    )


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_sends_due_invoice_and_marks_sent(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-A")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == ["inv-A"]
    assert inv.external_status == "sent"
    assert inv.sent_at is not None


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_skips_future_installment(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=_months_ahead(timezone.localdate(), 2), external_id="inv-F")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == []
    assert inv.external_status == "created"


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_skips_guardian_without_email(active_plan, monkeypatch):
    from apps.members.models import Guardian
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    no_email_guardian = Guardian.objects.create(full_name="Bez Pasta", email="")
    inv = _draft_invoice(active_plan, no_email_guardian, due_date=timezone.localdate(), external_id="inv-N")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == []
    assert inv.external_status == "created"


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_records_error_and_continues_on_failure(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    def boom(eid):
        raise invoice_platform.InvoicePlatformTransientError("down")

    monkeypatch.setattr(invoice_platform, "email_invoice", boom)
    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-E")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert inv.external_status == "created"  # stays draft -> retried next run
    assert inv.external_error_code == "unavailable"


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_idempotent_does_not_resend_sent(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    calls = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: calls.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-I")
    tasks.send_due_invoices()
    tasks.send_due_invoices()  # second run

    assert calls == ["inv-I"]  # emailed once


@override_settings(BILLING_AUTOSEND_ENABLED=False)
def test_noop_when_autosend_disabled(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-D")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == []
    assert inv.external_status == "created"

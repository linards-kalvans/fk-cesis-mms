"""Confirming a billing record from the admin emits an AuditEvent."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.billing.admin import BillingRecordAdmin
from apps.billing.models import BillingRecord
from apps.core.models import AuditEvent
from apps.members.models import Member

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _draft(active_plan, guardian):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT, status=BillingRecord.Status.DRAFT,
    )


def test_confirm_emits_audit_event(active_plan, guardian):
    rec = _draft(active_plan, guardian)
    c = _staff_client()
    c.post(reverse("admin:billing_billingrecord_confirm", args=[rec.pk]))
    e = AuditEvent.objects.get(action=AuditEvent.Action.BILLING_RECORD_CONFIRMED)
    assert e.target_type == "billingrecord"
    assert e.target_id == str(rec.pk)
    assert e.actor is not None and e.actor.username == "staff"  # the acting staff user


def test_already_confirmed_confirm_emits_no_audit(active_plan, guardian):
    rec = _draft(active_plan, guardian)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save(update_fields=["status"])
    c = _staff_client()
    c.post(reverse("admin:billing_billingrecord_confirm", args=[rec.pk]))
    assert not AuditEvent.objects.filter(
        action=AuditEvent.Action.BILLING_RECORD_CONFIRMED
    ).exists()


def test_push_with_confirm_flag_confirms_audits_and_enqueues(
    active_plan, guardian
):
    """The Hub's one-click action: an explicit confirm_and_push=1 POST to
    the existing push endpoint confirms a draft, audits the confirmation
    AND the push trigger separately, and enqueues exactly one push job —
    all without touching Invoice Ninja during the request."""
    rec = _draft(active_plan, guardian)
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_push", args=[rec.pk])

    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue:
        response = c.post(url, {"confirm_and_push": "1"})

    assert response.status_code == 302
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.CONFIRMED
    enqueue.assert_called_once_with(rec.pk)
    actions = set(
        AuditEvent.objects.filter(target_id=str(rec.pk)).values_list(
            "action", flat=True
        )
    )
    assert str(AuditEvent.Action.BILLING_RECORD_CONFIRMED) in actions
    assert str(AuditEvent.Action.BILLING_PUSH_TRIGGERED) in actions


def test_save_model_dropdown_confirm_emits_audit(active_plan, guardian):
    # Confirming via the change-form status dropdown + Save (not the one-click
    # button) is also audited, via save_model.
    rec = _draft(active_plan, guardian)
    staff = User.objects.create_superuser("staff", "s@example.com", "pw")
    request = RequestFactory().post("/")
    request.user = staff
    admin_obj = BillingRecordAdmin(BillingRecord, AdminSite())
    # NB: mutate status in memory only — save_model reads was_draft from the DB
    # (still DRAFT) before saving. Do NOT rec.save() here, or the audit won't fire.
    rec.status = BillingRecord.Status.CONFIRMED
    admin_obj.save_model(request, rec, form=None, change=True)
    e = AuditEvent.objects.get(action=AuditEvent.Action.BILLING_RECORD_CONFIRMED)
    assert e.target_id == str(rec.pk)
    assert e.actor == staff


def test_save_model_no_audit_when_not_a_transition(active_plan, guardian):
    # Saving an already-confirmed record (no DRAFT→CONFIRMED transition) audits nothing.
    rec = _draft(active_plan, guardian)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save(update_fields=["status"])
    staff = User.objects.create_superuser("staff", "s@example.com", "pw")
    request = RequestFactory().post("/")
    request.user = staff
    admin_obj = BillingRecordAdmin(BillingRecord, AdminSite())
    admin_obj.save_model(request, rec, form=None, change=True)
    assert not AuditEvent.objects.filter(
        action=AuditEvent.Action.BILLING_RECORD_CONFIRMED
    ).exists()

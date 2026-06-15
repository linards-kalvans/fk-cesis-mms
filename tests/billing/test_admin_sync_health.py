"""Sync-health badges + filter on the billing admin."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.billing.models import BillingRecord
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _record(active_plan, guardian, **kw):
    name = kw.pop("name", "Bērns")
    m = Member.objects.create(full_name=name, guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, **kw,
    )


def test_failed_sync_shows_fail_badge_with_tooltip(active_plan, guardian):
    _record(active_plan, guardian, external_status="error", external_error_code="provider_unavailable")
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "fk-badge--fail" in html
    assert "title=" in html


def test_synced_record_shows_ok_badge(active_plan, guardian):
    _record(active_plan, guardian, external_status="synced", name="Sinhr")
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "fk-badge--ok" in html


def test_sync_health_filter_isolates_failed(active_plan, guardian):
    _record(active_plan, guardian, external_status="error", external_error_code="provider_unavailable", name="Fail")
    _record(active_plan, guardian, external_status="synced", name="OK")
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist") + "?sync_health=failed"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Fail" in body
    assert "OK" not in body


def test_sync_health_filter_rendered_in_sidebar(active_plan, guardian):
    _record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "sync_health" in html


def test_sync_health_filter_ok_excludes_errored_synced(active_plan, guardian):
    # A synced row that also carries an error code must NOT count as OK.
    _record(active_plan, guardian, external_status="synced", name="Clean")
    _record(active_plan, guardian, external_status="synced",
            external_error_code="rate_limited", name="Tainted")
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist") + "?sync_health=ok"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Clean" in body
    assert "Tainted" not in body


def test_sync_health_filter_none_excludes_errored(active_plan, guardian):
    # An empty-status row with an error code belongs to "failed", not "none".
    _record(active_plan, guardian, external_status="", name="Untouched")
    _record(active_plan, guardian, external_status="",
            external_error_code="provider_unavailable", name="Errored")
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist") + "?sync_health=none"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Untouched" in body
    assert "Errored" not in body


def test_payment_status_badge_paid_shows_ok(active_plan, guardian):
    _record(active_plan, guardian, payment_status="paid", name="Samaksāts")
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "fk-badge--ok" in html


def test_payment_error_shows_fail_badge_with_tooltip(active_plan, guardian):
    _record(active_plan, guardian, payment_error_code="provider_unavailable", name="Kļūda")
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert "fk-badge--fail" in html
    assert "title=" in html

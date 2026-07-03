"""Sync-health badges + filter on the billing admin."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.billing.models import BillingRecord
from apps.members.models import Member

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


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


def test_admin_badge_and_sidebar_render(active_plan, guardian):
    """One changelist render covers all the badge variants + the sync_health
    sidebar link. Behaviour-bucketed filter coverage stays in dedicated tests
    so the buckets (ok/failed/pending/none) get an isolated assertion each.
    """
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist")
    body = c.get(url).content.decode()

    # Sidebar entry for the sync_health filter is always present.
    assert "sync_health" in body

    # Seed one row per badge variant, then re-fetch the changelist and
    # confirm every expected badge class is on the page.
    _record(active_plan, guardian, external_status="error",
            external_error_code="provider_unavailable")
    _record(active_plan, guardian, external_status="synced", name="Sinhr")
    _record(active_plan, guardian, payment_status="paid", name="Samaksāts")
    _record(active_plan, guardian, payment_error_code="provider_unavailable",
            name="Kļūda")

    body = c.get(url).content.decode()
    assert "fk-badge--fail" in body, "failed/payment-error rows must render fk-badge--fail"
    assert "fk-badge--ok" in body, "synced/paid rows must render fk-badge--ok"
    # Tooltips (title=…) accompany the fail badge so the error code is visible.
    assert "title=" in body, "fail badges must carry a tooltip title attribute"


def test_sync_health_filter_isolates_failed(active_plan, guardian):
    # Distinctive member names that cannot collide with admin chrome or the
    # SyncHealthFilter sidebar labels (e.g. the literal "OK" choice label).
    _record(active_plan, guardian, external_status="error",
            external_error_code="provider_unavailable", name="FailRowSentinel")
    _record(active_plan, guardian, external_status="synced", name="SyncedRowSentinel")
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist") + "?sync_health=failed"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "FailRowSentinel" in body
    assert "SyncedRowSentinel" not in body


def test_sync_health_filter_pending_is_inflight_without_error(active_plan, guardian):
    # pending = a non-empty, non-synced status with no error code.
    _record(active_plan, guardian, external_status="queued", name="PendingSentinel")
    _record(active_plan, guardian, external_status="synced", name="SyncedSentinel")
    _record(active_plan, guardian, external_status="error",
            external_error_code="provider_unavailable", name="FailSentinel")
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_changelist") + "?sync_health=pending"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "PendingSentinel" in body
    assert "SyncedSentinel" not in body
    assert "FailSentinel" not in body


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


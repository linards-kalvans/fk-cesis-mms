"""P8: BillingAdjustment admin tests.

Covers changelist status display, retry action, and non-staff access guard.
These admin URLs do not exist yet — expected RED phase.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "staff@example.test", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _non_staff_client():
    User.objects.create_user(username="nobody", password="pw", is_staff=False)
    c = Client()
    c.login(username="nobody", password="pw")
    return c


@pytest.fixture
def adjustment(db, billing_record, billing_invoice):
    """A pending BillingAdjustment."""
    from apps.billing.models import BillingAdjustment  # noqa: F401

    return BillingAdjustment.objects.create(
        billing_record=billing_record,
        invoice=billing_invoice,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount=Decimal("30.00"),
        reason="Pārtraukta dalība",
    )


@pytest.fixture
def failed_adjustment(db, billing_record, billing_invoice):
    """A failed BillingAdjustment ready for retry."""
    from apps.billing.models import BillingAdjustment  # noqa: F401

    return BillingAdjustment.objects.create(
        billing_record=billing_record,
        invoice=billing_invoice,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount=Decimal("30.00"),
        reason="Pārtraukta dalība",
        external_status="failed",
        external_error_code="auth_failed",
    )


@pytest.fixture
def applied_adjustment(db, billing_record, billing_invoice):
    """An applied (successful) BillingAdjustment."""
    from apps.billing.models import BillingAdjustment  # noqa: F401

    return BillingAdjustment.objects.create(
        billing_record=billing_record,
        invoice=billing_invoice,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount=Decimal("30.00"),
        reason="Pārtraukta dalība",
        external_credit_id="credit-1",
        external_status="applied",
        applied_to_external_invoice_id="IN-123",
    )


# -- Admin URL exists --


def test_admin_url_resolves():
    """admin:billing_billingadjustment_changelist must resolve to a URL."""
    url = reverse("admin:billing_billingadjustment_changelist")
    assert url.startswith("/")


# -- Changelist status display --


def test_changelist_shows_pending_status(adjustment):
    """Pending adjustments show external status text on the changelist."""
    c = _staff_client()
    html = c.get(
        reverse("admin:billing_billingadjustment_changelist")
    ).content.decode()
    html_lower = html.lower()
    assert "pending" in html_lower or any(
        term in html_lower for term in ["proces", "gaid"]
    )


def test_changelist_shows_failed_status(failed_adjustment):
    """Failed adjustments show external status + error code on the changelist."""
    c = _staff_client()
    html = c.get(
        reverse("admin:billing_billingadjustment_changelist")
    ).content.decode()
    html_lower = html.lower()
    assert "failed" in html_lower or any(
        term in html_lower for term in ["neizdev", "kļūda"]
    )
    # Error code or its Latvian label should appear
    assert "auth_failed" in html_lower or any(
        term in html_lower for term in ["autentifik", "autorizācij"]
    )


def test_changelist_shows_applied_status(applied_adjustment):
    """Applied adjustments show external status on the changelist."""
    c = _staff_client()
    html = c.get(
        reverse("admin:billing_billingadjustment_changelist")
    ).content.decode()
    html_lower = html.lower()
    assert "applied" in html_lower or any(
        term in html_lower for term in ["piemērot", "apstrād"]
    )


# -- Retry action for failed credit notes --


def test_retry_action_enqueues_create_credit_note(monkeypatch, failed_adjustment):
    """Retry action must call enqueue_create_credit_note(adjustment.pk)."""
    from apps.integrations import tasks

    enqueued = []
    monkeypatch.setattr(
        tasks, "enqueue_create_credit_note", lambda pk: enqueued.append(pk)
    )

    c = _staff_client()
    url = reverse("admin:billing_billingadjustment_changelist")
    data = {
        "action": "retry_credit_note",
        "_selected_action": str(failed_adjustment.pk),
    }
    c.post(url, data, follow=True)

    assert enqueued == [failed_adjustment.pk]


def test_retry_action_only_enqueues_failed(failed_adjustment, applied_adjustment):
    """Retry action should only enqueue failed adjustments (applied should be skipped)."""
    from apps.integrations import tasks
    from unittest.mock import patch

    enqueued = []
    with patch.object(
        tasks, "enqueue_create_credit_note",
        side_effect=lambda pk: enqueued.append(pk),
    ):
        c = _staff_client()
        url = reverse("admin:billing_billingadjustment_changelist")
        data = {
            "action": "retry_credit_note",
            "_selected_action": [
                str(failed_adjustment.pk),
                str(applied_adjustment.pk),
            ],
        }
        c.post(url, data, follow=True)

    # Only the failed one should be enqueued
    assert enqueued == [failed_adjustment.pk]


# -- Non-staff access guard --


def test_non_staff_cannot_access_changelist():
    """Non-staff users must not be able to access the BillingAdjustment admin."""
    c = _non_staff_client()
    resp = c.get(reverse("admin:billing_billingadjustment_changelist"))
    assert resp.status_code in (302, 403)


def test_non_staff_cannot_access_change_view(adjustment):
    """Non-staff users must not be able to access the BillingAdjustment change view."""
    c = _non_staff_client()
    url = reverse(
        "admin:billing_billingadjustment_change", args=[adjustment.pk]
    )
    resp = c.get(url)
    assert resp.status_code in (302, 403)

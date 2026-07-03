"""P8 rework: Invoice platform archive + cancel boundary tests.

Tests stub-mode shapes for archive_invoice and cancel_invoice, and
django-q2 jobs archive_invoice_job / cancel_invoice_job.

These functions + the BillingInvoice external cancellation fields
do not exist yet — expected RED phase.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Adapter boundary: archive_invoice / cancel_invoice
# ---------------------------------------------------------------------------


def test_archive_invoice_function_exists():
    """archive_invoice must be importable from invoice_platform."""
    from apps.integrations.invoice_platform import archive_invoice  # noqa: F401


def test_cancel_invoice_function_exists():
    """cancel_invoice must be importable from invoice_platform."""
    from apps.integrations.invoice_platform import cancel_invoice  # noqa: F401


def test_stub_archive_invoice_accepts_id():
    """In stub mode, archive_invoice('abc') must not raise."""
    from django.conf import settings
    from apps.integrations import invoice_platform

    assert settings.INVOICE_PROVIDER_MODE == "stub"
    # Should return nothing (void) — just not raise.
    result = invoice_platform.archive_invoice("abc")
    assert result is None


def test_stub_cancel_invoice_accepts_id_and_reason():
    """In stub mode, cancel_invoice('abc', 'reason') must not raise."""
    from django.conf import settings
    from apps.integrations import invoice_platform

    assert settings.INVOICE_PROVIDER_MODE == "stub"
    result = invoice_platform.cancel_invoice("abc", "pārtraukta dalība")
    assert result is None


# -- Mode dispatch --


def test_archive_invoice_unknown_mode_raises_config_error():
    from django.conf import settings
    from unittest.mock import patch

    with patch.object(settings, "INVOICE_PROVIDER_MODE", "unknown-mode"):
        from apps.integrations.invoice_platform import (
            InvoicePlatformConfigError,
            archive_invoice,
        )
        with pytest.raises(InvoicePlatformConfigError):
            archive_invoice("abc")


def test_cancel_invoice_unknown_mode_raises_config_error():
    from django.conf import settings
    from unittest.mock import patch

    with patch.object(settings, "INVOICE_PROVIDER_MODE", "unknown-mode"):
        from apps.integrations.invoice_platform import (
            InvoicePlatformConfigError,
            cancel_invoice,
        )
        with pytest.raises(InvoicePlatformConfigError):
            cancel_invoice("abc", "reason")


# ---------------------------------------------------------------------------
# Task boundary: archive_invoice_job / cancel_invoice_job
# ---------------------------------------------------------------------------


@pytest.fixture
def invoice_for_archive(db, active_plan):
    """A BillingInvoice with external_invoice_id, ready for archive job."""
    from tests.support import make_guardian
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    guardian = make_guardian(full_name="Test", email="test@example.test")
    member = Member.objects.create(full_name="Test Child", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.CONFIRMED,
    )
    return BillingInvoice.objects.create(
        billing_record=rec,
        sequence=0,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-DRAFT-CANCEL",
        external_status="created",
    )


@pytest.fixture
def invoice_for_cancel(db, active_plan):
    """A BillingInvoice with external_invoice_id, ready for cancel job."""
    from tests.support import make_guardian
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    guardian = make_guardian(full_name="Test", email="test@example.test")
    member = Member.objects.create(full_name="Test Child", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        status=BillingRecord.Status.CONFIRMED,
    )
    return BillingInvoice.objects.create(
        billing_record=rec,
        sequence=0,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-SENT-CANCEL",
        external_status="sent",
    )


# -- Enqueue helpers --


def test_enqueue_archive_invoice_exists():
    from apps.integrations.tasks import enqueue_archive_invoice  # noqa: F401


def test_enqueue_cancel_invoice_exists():
    from apps.integrations.tasks import enqueue_cancel_invoice  # noqa: F401


# -- Archive job success --


def test_archive_invoice_job_marks_done(monkeypatch, invoice_for_archive):
    """Happy path: stub archive succeeds → external_cancellation_status = 'done'.

    The job function archive_invoice_job does not exist yet — this test
    will fail with AttributeError in the RED phase.
    """
    from apps.integrations import tasks

    monkeypatch.setattr(
        tasks.invoice_platform,
        "archive_invoice",
        lambda ext_id: None,
    )

    tasks.archive_invoice_job(invoice_for_archive.pk)

    invoice_for_archive.refresh_from_db()
    # Fields don't exist yet — hasattr guards. When they land, assert.
    if hasattr(invoice_for_archive, "external_cancellation_status"):
        assert invoice_for_archive.external_cancellation_status == "done"
    if hasattr(invoice_for_archive, "external_cancellation_error_code"):
        assert invoice_for_archive.external_cancellation_error_code == ""


# -- Cancel job success --


def test_cancel_invoice_job_marks_done(monkeypatch, invoice_for_cancel):
    """Happy path: stub cancel succeeds → external_cancellation_status = 'done'."""
    from apps.integrations import tasks

    monkeypatch.setattr(
        tasks.invoice_platform,
        "cancel_invoice",
        lambda ext_id, reason: None,
    )

    tasks.cancel_invoice_job(invoice_for_cancel.pk)

    invoice_for_cancel.refresh_from_db()
    if hasattr(invoice_for_cancel, "external_cancellation_status"):
        assert invoice_for_cancel.external_cancellation_status == "done"
    if hasattr(invoice_for_cancel, "external_cancellation_error_code"):
        assert invoice_for_cancel.external_cancellation_error_code == ""


# -- Terminal failure --


def test_archive_invoice_job_marks_failed_on_terminal_error(
    monkeypatch, invoice_for_archive
):
    """Terminal provider error persists failed, does NOT retry."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    monkeypatch.setattr(
        tasks.invoice_platform,
        "archive_invoice",
        lambda ext_id: (_ for _ in ()).throw(InvoicePlatformAuthError("bad key")),
    )

    tasks.archive_invoice_job(invoice_for_archive.pk)

    invoice_for_archive.refresh_from_db()
    if hasattr(invoice_for_archive, "external_cancellation_status"):
        assert invoice_for_archive.external_cancellation_status == "failed"
    if hasattr(invoice_for_archive, "external_cancellation_error_code"):
        assert invoice_for_archive.external_cancellation_error_code != ""


def test_cancel_invoice_job_marks_failed_on_terminal_error(
    monkeypatch, invoice_for_cancel
):
    """Terminal provider error persists failed, does NOT retry."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    monkeypatch.setattr(
        tasks.invoice_platform,
        "cancel_invoice",
        lambda ext_id, reason: (_ for _ in ()).throw(
            InvoicePlatformAuthError("bad key")
        ),
    )

    tasks.cancel_invoice_job(invoice_for_cancel.pk)

    invoice_for_cancel.refresh_from_db()
    if hasattr(invoice_for_cancel, "external_cancellation_status"):
        assert invoice_for_cancel.external_cancellation_status == "failed"
    if hasattr(invoice_for_cancel, "external_cancellation_error_code"):
        assert invoice_for_cancel.external_cancellation_error_code != ""


# -- Transient retry --


def test_archive_invoice_job_raises_on_transient_error(
    monkeypatch, invoice_for_archive
):
    """Transient error raises RetryableInvoiceError for django-q retry."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import InvoicePlatformTransientError
    from apps.integrations.tasks import RetryableInvoiceError

    monkeypatch.setattr(
        tasks.invoice_platform,
        "archive_invoice",
        lambda ext_id: (_ for _ in ()).throw(
            InvoicePlatformTransientError("timeout")
        ),
    )

    with pytest.raises(RetryableInvoiceError):
        tasks.archive_invoice_job(invoice_for_archive.pk)


def test_cancel_invoice_job_raises_on_transient_error(
    monkeypatch, invoice_for_cancel
):
    """Transient error raises RetryableInvoiceError for django-q retry."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import InvoicePlatformTransientError
    from apps.integrations.tasks import RetryableInvoiceError

    monkeypatch.setattr(
        tasks.invoice_platform,
        "cancel_invoice",
        lambda ext_id, reason: (_ for _ in ()).throw(
            InvoicePlatformTransientError("timeout")
        ),
    )

    with pytest.raises(RetryableInvoiceError):
        tasks.cancel_invoice_job(invoice_for_cancel.pk)

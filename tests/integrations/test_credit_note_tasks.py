"""P8: Credit note background-job tests.

Tests create_credit_note_job and enqueue_create_credit_note success,
terminal failure, and transient retry paths. These functions do not exist
yet — expected RED phase.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def adjustment(db, active_plan):
    """A pending BillingAdjustment ready for credit note creation."""
    from tests.support import make_guardian
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice, BillingAdjustment

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
    inv = BillingInvoice.objects.create(
        billing_record=rec,
        sequence=0,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-123",
        sent_at="2026-06-15T12:00:00Z",
    )

    return BillingAdjustment.objects.create(
        billing_record=rec,
        invoice=inv,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount=inv.amount,
        reason="Pārtraukta dalība",
    )


# -- Enqueue helper --


def test_enqueue_create_credit_note_exists():
    from apps.integrations.tasks import enqueue_create_credit_note  # noqa: F401


# -- Job success path --


def test_create_credit_note_job_marks_created_and_applied(
    monkeypatch, adjustment
):
    """Happy path: stub credit creation + apply both succeed."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import CreditResult, CreditApplyResult

    monkeypatch.setattr(
        tasks.invoice_platform,
        "create_credit_note",
        lambda adj: CreditResult("credit-1", "created"),
    )
    monkeypatch.setattr(
        tasks.invoice_platform,
        "apply_credit_to_invoice",
        lambda credit_id, invoice_id, amount: CreditApplyResult(True, "applied"),
    )

    tasks.create_credit_note_job(adjustment.pk)

    adjustment.refresh_from_db()
    assert adjustment.external_credit_id == "credit-1"
    assert adjustment.external_status == "applied"
    assert adjustment.applied_to_external_invoice_id == "IN-123"


def test_create_credit_note_job_audits_on_success(monkeypatch, adjustment):
    """Credit created + applied records audit events."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import CreditResult, CreditApplyResult
    from apps.core.models import AuditEvent

    monkeypatch.setattr(
        tasks.invoice_platform,
        "create_credit_note",
        lambda adj: CreditResult("credit-1", "created"),
    )
    monkeypatch.setattr(
        tasks.invoice_platform,
        "apply_credit_to_invoice",
        lambda credit_id, invoice_id, amount: CreditApplyResult(True, "applied"),
    )

    before = AuditEvent.objects.count()
    tasks.create_credit_note_job(adjustment.pk)

    events = AuditEvent.objects.filter(created_at__gt=adjustment.created_at)
    actions = {e.action for e in events}
    assert str(AuditEvent.Action.BILLING_CREDIT_CREATED) in actions
    assert str(AuditEvent.Action.BILLING_CREDIT_APPLIED) in actions


# -- Terminal failure --


def test_create_credit_note_job_marks_failed_on_terminal_error(
    monkeypatch, adjustment
):
    """Terminal provider error persists failed and audits, does NOT retry."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import InvoicePlatformAuthError
    from apps.core.models import AuditEvent

    monkeypatch.setattr(
        tasks.invoice_platform,
        "create_credit_note",
        lambda adj: (_ for _ in ()).throw(InvoicePlatformAuthError("bad key")),
    )

    before = AuditEvent.objects.count()
    tasks.create_credit_note_job(adjustment.pk)

    adjustment.refresh_from_db()
    assert adjustment.external_status == "failed"
    assert adjustment.external_error_code != ""

    # Audit event recorded
    assert AuditEvent.objects.count() > before
    events = AuditEvent.objects.filter(created_at__gt=adjustment.created_at)
    actions = {e.action for e in events}
    assert str(AuditEvent.Action.BILLING_CREDIT_FAILED) in actions


# -- Transient error --


def test_create_credit_note_job_raises_on_transient_error(
    monkeypatch, adjustment
):
    """Transient error raises RetryableInvoiceError for django-q retry."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import InvoicePlatformTransientError
    from apps.integrations.tasks import RetryableInvoiceError

    monkeypatch.setattr(
        tasks.invoice_platform,
        "create_credit_note",
        lambda adj: (_ for _ in ()).throw(
            InvoicePlatformTransientError("timeout")
        ),
    )

    with pytest.raises(RetryableInvoiceError):
        tasks.create_credit_note_job(adjustment.pk)


# -- Apply-credit unsupported fallback --


def test_create_credit_note_job_applies_fallback_when_apply_not_supported(
    monkeypatch, adjustment
):
    """When apply_credit_to_invoice returns applied=False (e.g. provider doesn't
    support it or the invoice state is unsafe), the job sets external_credit_id,
    leaves external_status as 'created', and flags requires_staff_apply=True."""
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import CreditResult, CreditApplyResult

    monkeypatch.setattr(
        tasks.invoice_platform,
        "create_credit_note",
        lambda adj: CreditResult("credit-1", "created"),
    )
    monkeypatch.setattr(
        tasks.invoice_platform,
        "apply_credit_to_invoice",
        lambda credit_id, invoice_id, amount: CreditApplyResult(
            applied=False, external_status="created"
        ),
    )

    tasks.create_credit_note_job(adjustment.pk)

    adjustment.refresh_from_db()
    assert adjustment.external_credit_id == "credit-1"
    assert adjustment.external_status == "created"
    assert adjustment.requires_staff_apply is True
    # applied_to_external_invoice_id stays empty — app not actually applied
    assert adjustment.applied_to_external_invoice_id == ""

"""Task 3 red-phase contract: DocuSeal creation cutoff and local isolation.

Pins the planned ``AGREEMENT_DOCUSEAL_CREATE_ENABLED`` cutoff (default true)
and the durable backend boundary:

* legacy rows without an ``external_id`` cannot send or confirm signing after
  the cutoff — even when a signed artifact was already uploaded — and queued or
  retried create jobs produce no state, mail, billing or HTTP change;
* the enqueue helper, worker body and provider create boundary each refuse;
* legacy rows that already have an ``external_id`` keep normal sync/completion,
  upload and external reference (a missing ID is never inferred);
* local rows never enqueue, sync, archive or enter provider creation, even
  while the cutoff is open.

Provider code is patched to fail loudly; no real DocuSeal or SMTP call occurs.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import (
    mark_agreement_sent,
    mark_agreement_signed,
    upload_signed_artifact,
)
from apps.billing.models import BillingRecord
from apps.core.models import AuditEvent
from apps.integrations import agreement_platform, tasks
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db

_FIELDS = (
    "state",
    "sent_at",
    "signed_at",
    "signing_path",
    "signed_artifact",
    "external_provider",
    "external_id",
    "external_state",
    "external_url",
    "external_error_code",
)


@pytest.fixture
def actor(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="cutoff-staff", is_staff=True)


@pytest.fixture
def cutoff(settings):
    settings.AGREEMENT_DOCUSEAL_CREATE_ENABLED = False
    return settings


@pytest.fixture
def legacy_agreement(agreement_member, active_plan):
    return Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        document_backend=Agreement.DocumentBackend.DOCUSEAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-501",
        billing_plan=active_plan,
        first_billing_month="2026-09",
    )


@pytest.fixture
def local_agreement(agreement_member, active_plan):
    return Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        document_backend=Agreement.DocumentBackend.LOCAL,
        generated_at=timezone.now(),
        agreement_number="FKC-2026-502",
        billing_plan=active_plan,
        first_billing_month="2026-09",
    )


def _application_for(agreement):
    member = agreement.member
    guardian = member.guardian
    return RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        parent_account=guardian.parent_account,
        guardian=guardian,
        approved_member=member,
        member_full_name=member.full_name,
        member_personal_id=member.personal_id,
        member_birth_date=member.birth_date,
        preferred_agreement_signing=agreement.signing_path,
    )


def _upload_signed_pdf(agreement, actor):
    upload_signed_artifact(
        agreement,
        SimpleUploadedFile(
            "signed.pdf", b"%PDF-1.7\nsigned artifact\n", content_type="application/pdf"
        ),
        actor,
    )
    agreement.refresh_from_db()
    return agreement


def _snapshot(agreement):
    agreement.refresh_from_db()
    values = (
        Agreement.objects.filter(pk=agreement.pk)
        .values(*_FIELDS)
        .get()
    )
    return {
        "agreement": values,
        "mail": len(mail.outbox),
        "audit": AuditEvent.objects.count(),
        "billing": BillingRecord.objects.count(),
    }


@contextmanager
def _no_provider_calls():
    with patch(
        "apps.integrations.agreement_platform.create_submission",
        side_effect=AssertionError("provider create must not run"),
    ), patch(
        "apps.integrations.agreement_platform.sync_submission",
        side_effect=AssertionError("provider sync must not run"),
    ), patch(
        "apps.integrations.agreement_platform.archive_submission",
        side_effect=AssertionError("provider archive must not run"),
    ):
        yield


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_cutoff_setting_defaults_to_enabled(settings):
    assert getattr(settings, "AGREEMENT_DOCUSEAL_CREATE_ENABLED", None) is True


# ---------------------------------------------------------------------------
# Legacy no-ID rows are blocked after the cutoff
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("uploaded", [False, True])
def test_legacy_no_id_send_is_blocked_after_cutoff(
    legacy_agreement, actor, cutoff, uploaded
):
    if uploaded:
        _upload_signed_pdf(legacy_agreement, actor)
    mail.outbox.clear()
    before = _snapshot(legacy_agreement)

    with _no_provider_calls(), patch(
        "apps.integrations.tasks.async_task"
    ) as enqueue:
        with pytest.raises(ValueError):
            mark_agreement_sent(legacy_agreement, actor)

    enqueue.assert_not_called()
    assert _snapshot(legacy_agreement) == before


@pytest.mark.parametrize("uploaded", [False, True])
def test_legacy_no_id_signing_confirmation_is_blocked_after_cutoff(
    legacy_agreement, actor, cutoff, uploaded
):
    legacy_agreement.state = Agreement.State.SENT
    legacy_agreement.sent_at = timezone.now()
    legacy_agreement.save(update_fields=["state", "sent_at"])
    if uploaded:
        _upload_signed_pdf(legacy_agreement, actor)
    mail.outbox.clear()
    before = _snapshot(legacy_agreement)

    with _no_provider_calls():
        with pytest.raises(ValueError):
            mark_agreement_signed(legacy_agreement, actor)

    assert _snapshot(legacy_agreement) == before


@pytest.mark.admin_view
def test_admin_retry_is_blocked_after_cutoff_for_no_id_legacy(
    staff_client, legacy_agreement, actor, cutoff
):
    legacy_agreement.external_state = "failed"
    legacy_agreement.external_error_code = "unavailable"
    legacy_agreement.save(
        update_fields=["external_state", "external_error_code"]
    )
    _upload_signed_pdf(legacy_agreement, actor)
    application = _application_for(legacy_agreement)
    before = _snapshot(legacy_agreement)
    url = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application.id],
    )

    with _no_provider_calls(), patch(
        "apps.integrations.tasks.async_task"
    ) as enqueue:
        response = staff_client.post(url, {"action": "retry_docuseal"})

    assert response.status_code == 302
    enqueue.assert_not_called()
    assert _snapshot(legacy_agreement) == before


def test_enqueue_create_is_a_noop_after_cutoff_for_no_id_legacy(
    legacy_agreement, cutoff
):
    with patch("apps.integrations.tasks.async_task") as enqueue:
        tasks.enqueue_create_agreement_submission(legacy_agreement.id)

    enqueue.assert_not_called()


def test_worker_create_is_a_noop_after_cutoff_for_no_id_legacy(
    legacy_agreement, cutoff
):
    before = _snapshot(legacy_agreement)

    with _no_provider_calls():
        tasks.create_agreement_submission(legacy_agreement.id)

    assert _snapshot(legacy_agreement) == before


def test_provider_create_boundary_refuses_after_cutoff_for_no_id_legacy(
    settings, legacy_agreement, cutoff
):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"

    with patch("apps.integrations.docuseal.create_submission") as provider:
        with pytest.raises(
            (agreement_platform.AgreementPlatformError, ValueError)
        ):
            agreement_platform.create_submission(legacy_agreement)

    provider.assert_not_called()


# ---------------------------------------------------------------------------
# Issued legacy sessions keep working after the cutoff
# ---------------------------------------------------------------------------


def test_issued_legacy_session_syncs_and_uploads_after_cutoff(
    settings, legacy_agreement, actor, cutoff
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    legacy_agreement.external_id = "issued-submission-1"
    legacy_agreement.external_state = "pending"
    legacy_agreement.save(update_fields=["external_id", "external_state"])
    _upload_signed_pdf(legacy_agreement, actor)
    artifact_name = legacy_agreement.signed_artifact.name
    billing_before = BillingRecord.objects.count()
    mail.outbox.clear()

    with patch(
        "apps.integrations.agreement_platform.create_submission",
        side_effect=AssertionError("no new provider create"),
        create=True,
    ):
        tasks.sync_agreement_submission(legacy_agreement.id)

    legacy_agreement.refresh_from_db()
    assert legacy_agreement.state == Agreement.State.SIGNED
    assert legacy_agreement.signed_at is not None
    assert legacy_agreement.external_id == "issued-submission-1"
    assert legacy_agreement.signed_artifact.name == artifact_name
    assert BillingRecord.objects.count() == billing_before + 1


def test_issued_legacy_session_keeps_external_reference_on_sync_failure(
    settings, legacy_agreement, cutoff
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    legacy_agreement.external_id = "issued-submission-2"
    legacy_agreement.external_state = "pending"
    legacy_agreement.save(update_fields=["external_id", "external_state"])
    before = _snapshot(legacy_agreement)

    with patch(
        "apps.integrations.agreement_platform.sync_submission",
        side_effect=agreement_platform.AgreementPlatformTransientError("5xx"),
    ):
        with pytest.raises(tasks.RetryableAgreementError):
            tasks.sync_agreement_submission(legacy_agreement.id)

    legacy_agreement.refresh_from_db()
    assert legacy_agreement.external_id == "issued-submission-2"
    assert legacy_agreement.external_state == "failed"
    assert legacy_agreement.state == before["agreement"]["state"]


# ---------------------------------------------------------------------------
# Local rows never enter the provider pipeline, cutoff open or closed
# ---------------------------------------------------------------------------


def test_local_row_never_enqueues_create_even_with_cutoff_open(
    settings, local_agreement
):
    assert getattr(
        settings, "AGREEMENT_DOCUSEAL_CREATE_ENABLED", None
    ) is True

    with patch("apps.integrations.tasks.async_task") as enqueue:
        tasks.enqueue_create_agreement_submission(local_agreement.id)

    enqueue.assert_not_called()


def test_local_row_worker_jobs_never_call_provider(settings, local_agreement):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    local_agreement.external_id = "local-row-must-not-sync"
    local_agreement.external_state = "pending"
    local_agreement.save(update_fields=["external_id", "external_state"])
    before = _snapshot(local_agreement)

    with _no_provider_calls(), patch(
        "apps.integrations.tasks.async_task"
    ) as enqueue:
        tasks.create_agreement_submission(local_agreement.id)
        tasks.sync_agreement_submission(local_agreement.id)
        tasks.enqueue_create_agreement_submission(local_agreement.id)

    enqueue.assert_not_called()
    assert _snapshot(local_agreement) == before


def test_local_row_cannot_enter_provider_create_with_cutoff_open(
    settings, local_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"

    with pytest.raises((agreement_platform.AgreementPlatformError, ValueError)):
        agreement_platform.create_submission(local_agreement)


def test_local_row_with_cutoff_open_has_no_provider_reference(
    settings, local_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    before = _snapshot(local_agreement)

    with _no_provider_calls():
        tasks.create_agreement_submission(local_agreement.id)

    assert _snapshot(local_agreement) == before
    assert local_agreement.external_provider == ""
    assert local_agreement.external_id == ""


# ---------------------------------------------------------------------------
# Review fix: webhook lookup is legacy-only
# ---------------------------------------------------------------------------


def test_webhook_ignores_local_row_with_stray_external_id(
    settings, local_agreement, actor
):
    import hashlib
    import json

    from django.core.files.base import ContentFile
    from django.test import Client

    from apps.agreements.models import GeneratedAgreementDocument

    settings.AGREEMENT_PROVIDER_MODE = "stub"
    data = b"%PDF-1.7\nlocal webhook fixture\n"
    document = GeneratedAgreementDocument.objects.create(
        agreement=local_agreement,
        status=GeneratedAgreementDocument.Status.READY,
        template_version="v1-2026-11",
        signing_path=local_agreement.signing_path,
        snapshot={},
        provenance={"template_version": "v1-2026-11"},
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        ready_at=timezone.now(),
    )
    document.file.save("ready.pdf", ContentFile(data), save=True)
    _upload_signed_pdf(local_agreement, actor)

    local_agreement.state = Agreement.State.SENT
    local_agreement.sent_at = timezone.now()
    local_agreement.external_id = "stray-local-webhook"
    local_agreement.external_state = "pending"
    local_agreement.save(
        update_fields=["state", "sent_at", "external_id", "external_state"]
    )
    before = _snapshot(local_agreement)

    response = Client().post(
        reverse("agreements:docuseal-webhook"),
        data=json.dumps(
            {
                "event_type": "submission.completed",
                "data": {"id": "stray-local-webhook"},
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert _snapshot(local_agreement) == before

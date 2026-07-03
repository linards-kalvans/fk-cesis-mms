"""Jobs for the agreement-platform pipeline (stub mode + classified failures)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.integrations import agreement_platform as ap
from apps.integrations import tasks


pytestmark = pytest.mark.django_db


@pytest.fixture
def electronic_agreement(agreement_member, default_membership_plan):
    return Agreement.objects.create(
        member=agreement_member,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        state=Agreement.State.SENT,
        generated_at=timezone.now(),
        billing_plan=default_membership_plan,
        first_billing_month="2026-09",
    )


def test_create_job_stores_external_fields(settings, electronic_agreement):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    tasks.create_agreement_submission(electronic_agreement.id)
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.external_provider == "docuseal"
    assert electronic_agreement.external_id == f"stub-{electronic_agreement.id}"
    assert electronic_agreement.external_url.endswith(str(electronic_agreement.id))
    assert electronic_agreement.external_state == "pending"
    assert electronic_agreement.external_error_code == ""


def test_create_job_missing_agreement_is_noop(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    tasks.create_agreement_submission(999999)  # no raise


def test_create_job_auth_failure_marks_failed_no_retry(settings, electronic_agreement):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    with patch(
        "apps.integrations.tasks.agreement_platform.create_submission",
        side_effect=ap.AgreementPlatformAuthError("bad key"),
    ):
        tasks.create_agreement_submission(electronic_agreement.id)  # no raise
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.external_state == "failed"
    assert electronic_agreement.external_error_code == "auth_failed"


def test_create_job_transient_failure_marks_failed_and_raises(
    settings, electronic_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    with patch(
        "apps.integrations.tasks.agreement_platform.create_submission",
        side_effect=ap.AgreementPlatformTransientError("5xx"),
    ):
        with pytest.raises(tasks.RetryableAgreementError):
            tasks.create_agreement_submission(electronic_agreement.id)
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.external_state == "failed"
    assert electronic_agreement.external_error_code == "unavailable"


def test_sync_job_completed_drives_signed(settings, electronic_agreement):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    electronic_agreement.external_id = f"stub-{electronic_agreement.id}"
    electronic_agreement.save(update_fields=["external_id"])
    tasks.sync_agreement_submission(electronic_agreement.id)
    electronic_agreement.refresh_from_db()
    assert electronic_agreement.state == Agreement.State.SIGNED


def test_sync_job_skips_signing_when_already_signed_in_db(
    settings, electronic_agreement
):
    """A racing webhook can sign the row while sync holds a stale in-memory
    state. Refreshing state from the DB before the signed-check prevents a
    double-sign that would clobber signed_at."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    electronic_agreement.external_id = f"stub-{electronic_agreement.id}"
    electronic_agreement.save(update_fields=["external_id"])
    signed_at = timezone.now()

    def _sign_in_db(external_id):
        Agreement.objects.filter(pk=electronic_agreement.id).update(
            state=Agreement.State.SIGNED, signed_at=signed_at
        )
        return ap.SubmissionResult(
            external_id=external_id,
            external_url="",
            external_state="completed",
        )

    with patch(
        "apps.integrations.tasks.agreement_platform.sync_submission",
        side_effect=_sign_in_db,
    ):
        with patch("apps.integrations.tasks.mark_agreement_signed") as spy:
            tasks.sync_agreement_submission(electronic_agreement.id)
    spy.assert_not_called()


def test_archive_job_calls_provider(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    with patch(
        "apps.integrations.tasks.agreement_platform.archive_submission"
    ) as spy:
        tasks.archive_agreement_submission("stub-1")
    spy.assert_called_once_with("stub-1")


def test_enqueue_helpers_call_async_task():
    with patch("apps.integrations.tasks.async_task") as spy:
        tasks.enqueue_create_agreement_submission(1)
        tasks.enqueue_sync_agreement_submission(2)
        tasks.enqueue_archive_agreement_submission("x")
    assert spy.call_count == 3

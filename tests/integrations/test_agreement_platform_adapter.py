"""Boundary-level tests for the agreement-platform adapter (stub mode +
exception taxonomy). Real-provider HTTP behavior is tested separately in
test_docuseal_provider.py."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.integrations import agreement_platform as ap


pytestmark = pytest.mark.django_db


class _FakeAgreement:
    id = 42


def test_stub_create_submission_is_deterministic(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    result = ap.create_submission(_FakeAgreement())
    assert result.external_id == "stub-42"
    assert result.external_url == "https://stub.invalid/42"
    assert result.external_state == "pending"


def test_stub_sync_submission_returns_completed(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    result = ap.sync_submission("stub-42")
    assert result.external_id == "stub-42"
    assert result.external_state == "completed"


def test_stub_archive_submission_is_noop(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    assert ap.archive_submission("stub-42") is None


def test_unknown_mode_raises_config_error(settings):
    settings.AGREEMENT_PROVIDER_MODE = "bogus"
    with pytest.raises(ap.AgreementPlatformConfigError):
        ap.create_submission(_FakeAgreement())


def test_docuseal_mode_dispatches_to_provider(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    fake = ap.SubmissionResult(
        external_id="ds-1", external_url="https://sign/x", external_state="pending"
    )
    with patch(
        "apps.integrations.docuseal.create_submission", return_value=fake
    ) as spy:
        result = ap.create_submission(_FakeAgreement())
    assert result is fake
    spy.assert_called_once()


def test_exception_hierarchy():
    assert issubclass(ap.AgreementPlatformConfigError, ap.AgreementPlatformError)
    assert issubclass(ap.AgreementPlatformAuthError, ap.AgreementPlatformError)
    assert issubclass(ap.AgreementPlatformNotFoundError, ap.AgreementPlatformError)
    assert issubclass(ap.AgreementPlatformTransientError, ap.AgreementPlatformError)

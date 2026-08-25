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


# ---------------------------------------------------------------------------
# DocumentStream + stream_submission_document (boundary)
# ---------------------------------------------------------------------------


def test_document_stream_dataclass_shape():
    ds = ap.DocumentStream(
        filename="a.pdf",
        content_type="application/pdf",
        chunks=iter([b"%PDF-"]),
    )
    assert ds.filename == "a.pdf"
    assert ds.content_type == "application/pdf"
    assert b"".join(ds.chunks).startswith(b"%PDF-")


def test_document_stream_is_frozen():
    from dataclasses import FrozenInstanceError

    ds = ap.DocumentStream(
        filename="a.pdf",
        content_type="application/pdf",
        chunks=iter([b"%PDF-"]),
    )
    with pytest.raises(FrozenInstanceError):
        ds.filename = "b.pdf"


def test_stub_stream_submission_document_yields_pdf_bytes(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    stream = ap.stream_submission_document("stub-42")
    assert stream.content_type == "application/pdf"
    assert b"".join(stream.chunks).startswith(b"%PDF-")


def test_docuseal_mode_stream_dispatches_to_provider(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    fake = ap.DocumentStream(
        filename="a.pdf",
        content_type="application/pdf",
        chunks=iter([b"%PDF-"]),
    )
    with patch(
        "apps.integrations.docuseal.stream_submission_document", return_value=fake
    ) as spy:
        result = ap.stream_submission_document("ds-1")
    assert result is fake
    spy.assert_called_once_with("ds-1")


def test_stub_create_submission_accepts_send_email(settings):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    result = ap.create_submission(_FakeAgreement(), send_email=False)
    assert result.external_id == "stub-42"


def test_create_submission_dispatches_send_email_to_provider(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    fake = ap.SubmissionResult(
        external_id="ds-1", external_url="https://sign/x", external_state="pending"
    )
    with patch(
        "apps.integrations.docuseal.create_submission", return_value=fake
    ) as spy:
        ap.create_submission(_FakeAgreement(), send_email=False)
    assert spy.call_args.kwargs.get("send_email") is False

"""Real-mode DocuSeal provider tests with monkeypatched HTTP transport.

Follows the repo convention (see test_tiny_idp_post_document.py): patch the
module's `requests` attribute and return a MagicMock response."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock

import pytest

from apps.integrations import agreement_platform as ap
from apps.integrations import docuseal


pytestmark = [pytest.mark.django_db, pytest.mark.external_contract]


@pytest.fixture
def docuseal_settings(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = "https://sign.example/api"
    settings.DOCUSEAL_API_KEY = "secret-key"
    settings.DOCUSEAL_TEMPLATE_ID = "7"
    settings.DOCUSEAL_WEBHOOK_SECRET = "whsecret"
    return settings


class _FakeGuardian:
    full_name = "Anna Bērziņa"
    personal_id = "111111-11111"
    email = "anna@example.test"
    phone = "+37120000000"
    address = "Rīgas iela 1"


class _FakeDate:
    @staticmethod
    def strftime(fmt):
        return "10.12.2015"


class _FakeSourceApplication:
    member_actual_address = "Sporta iela 1, Cēsis"


class _FakeMember:
    id = 5
    full_name = "Jānis Bērziņš"
    personal_id = "151210-22222"
    birth_date = _FakeDate()
    guardian = _FakeGuardian()
    source_application = _FakeSourceApplication()


class _GeneratedAt:
    @staticmethod
    def date():
        class _D:
            @staticmethod
            def isoformat():
                return "2026-05-29"

        return _D()


class _FakeAgreement:
    id = 42
    member = _FakeMember()
    generated_at = _GeneratedAt()
    agreement_number = "FKC-2026-001"


def _mock_response(status_code, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    resp.text = json.dumps(payload) if payload is not None else ""
    return resp


def test_create_submission_request_shape_and_normalization(
    docuseal_settings, monkeypatch
):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = kwargs.get("json")
        return _mock_response(
            201,
            [
                {
                    "id": 2001,
                    "submission_id": 1001,
                    "slug": "abc",
                    "status": "sent",
                    "embed_src": "https://sign.example/s/abc",
                }
            ],
        )

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    result = docuseal.create_submission(_FakeAgreement())
    assert isinstance(result, ap.SubmissionResult)
    assert result.external_id == "1001"  # submission_id, not the submitter id
    assert result.external_state == "pending"  # "sent" normalizes to pending
    assert result.external_url == "https://sign.example/s/abc"

    assert captured["method"] == "POST"
    assert captured["url"] == "https://sign.example/api/submissions"
    assert captured["headers"]["X-Auth-Token"] == "secret-key"
    body = captured["json"]
    assert body["template_id"] == 7
    submitter = body["submitters"][0]
    assert submitter["email"] == "anna@example.test"
    # No role sent: the template owns the role name; DocuSeal rejects a
    # mismatching role once values are present.
    assert "role" not in submitter
    # Prefill goes through the submitter `fields` array as readonly entries
    # (not a `values` map): readonly fields are non-interactive, so the signer
    # skips field re-confirmation and goes straight to the signatures.
    assert "values" not in submitter
    fields = submitter["fields"]
    by_name = {f["name"]: f for f in fields}
    assert {
        "agreement_number",
        "child_name",
        "child_address",
        "guardian_name",
        "guardian_email",
        "guardian_phone",
    } <= set(by_name)
    assert by_name["agreement_number"]["default_value"] == "FKC-2026-001"
    assert by_name["child_address"]["default_value"] == "Sporta iela 1, Cēsis"
    assert by_name["guardian_email"]["default_value"] == "anna@example.test"
    assert by_name["guardian_phone"]["default_value"] == "+37120000000"
    assert all(f["readonly"] is True for f in fields)
    assert "training_group" not in by_name
    # agreement_date is auto-filled by the DocuSeal template (current date),
    # so we no longer send it.
    assert "agreement_date" not in by_name
    # Fields live on the submitter, never as a top-level array.
    assert "fields" not in body


def test_create_submission_auth_error(docuseal_settings, monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request",
        lambda *a, **kw: _mock_response(401, {"error": "unauthorized"}),
    )
    with pytest.raises(ap.AgreementPlatformAuthError):
        docuseal.create_submission(_FakeAgreement())


def test_create_submission_transient_on_5xx(docuseal_settings, monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request",
        lambda *a, **kw: _mock_response(502, {"error": "boom"}),
    )
    with pytest.raises(ap.AgreementPlatformTransientError):
        docuseal.create_submission(_FakeAgreement())


def test_create_submission_config_error_when_unconfigured(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_API_URL = ""
    settings.DOCUSEAL_API_KEY = ""
    with pytest.raises(ap.AgreementPlatformConfigError):
        docuseal.create_submission(_FakeAgreement())


def test_sync_submission_not_found(docuseal_settings, monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request",
        lambda *a, **kw: _mock_response(404, {"error": "not found"}),
    )
    with pytest.raises(ap.AgreementPlatformNotFoundError):
        docuseal.sync_submission("ds-9")


def test_sync_submission_normalizes_completed(docuseal_settings, monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request",
        lambda *a, **kw: _mock_response(200, {"id": "ds-9", "status": "completed"}),
    )
    result = docuseal.sync_submission("ds-9")
    assert result.external_state == "completed"


def test_verify_webhook_signature_accepts_valid(docuseal_settings):
    body = b'{"event_type":"submission.completed"}'
    ts = str(int(time.time()))
    sig = hmac.new(b"whsecret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert docuseal.verify_webhook_signature(body, f"{ts}.{sig}") is True


def test_verify_webhook_signature_rejects_tampered(docuseal_settings):
    body = b'{"event_type":"submission.completed"}'
    assert docuseal.verify_webhook_signature(body, "deadbeef") is False


def test_verify_webhook_signature_rejects_stale_timestamp(docuseal_settings):
    body = b'{"event_type":"submission.completed"}'
    ts = str(int(time.time()) - 400)
    sig = hmac.new(b"whsecret", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert docuseal.verify_webhook_signature(body, f"{ts}.{sig}") is False


def test_verify_webhook_signature_rejects_empty_header(docuseal_settings):
    assert docuseal.verify_webhook_signature(b"x", "") is False


def test_create_submission_requires_agreement_number(docuseal_settings):
    class MissingNumberAgreement(_FakeAgreement):
        agreement_number = ""

    with pytest.raises(ap.AgreementPlatformConfigError, match="agreement number"):
        docuseal.create_submission(MissingNumberAgreement())


def test_list_submission_documents_parses_pdf_documents(docuseal_settings, monkeypatch):
    """list_submission_documents must GET /submissions/{id}/documents with
    auth header and parse the response into DocumentResult instances."""
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return _mock_response(
            200,
            {
                "documents": [
                    {
                        "id": 501,
                        "filename": "agreement.pdf",
                        "content_type": "application/pdf",
                        "url": "https://sign.example/docs/501.pdf",
                    },
                    {
                        "id": 502,
                        "filename": "attachment.png",
                        "content_type": "image/png",
                        "url": "https://sign.example/docs/502.png",
                    },
                ]
            },
        )

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    from apps.integrations.agreement_platform import DocumentResult

    results = docuseal.list_submission_documents("1001")

    assert captured["method"] == "GET"
    assert captured["url"] == "https://sign.example/api/submissions/1001/documents"
    assert captured["headers"]["X-Auth-Token"] == "secret-key"

    assert len(results) == 2
    assert isinstance(results[0], DocumentResult)
    assert results[0].filename == "agreement.pdf"
    assert results[0].url == "https://sign.example/docs/501.pdf"
    assert results[0].content_type == "application/pdf"
    assert results[1].filename == "attachment.png"
    assert results[1].url == "https://sign.example/docs/502.png"
    assert results[1].content_type == "image/png"

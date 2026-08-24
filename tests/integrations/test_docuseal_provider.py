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
    display_name = "Anna Bērziņa"
    first_name = "Anna"
    family_name = "Bērziņa"
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
    # P13 cleanup: submitter name uses guardian.display_name (not full_name).
    assert submitter["name"] == "Anna Bērziņa"
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
    # P13 cleanup: guardian_name field uses guardian.display_name.
    assert by_name["guardian_name"]["default_value"] == "Anna Bērziņa"
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


def test_list_submission_documents_invalid_json_raises_config_error(
    docuseal_settings, monkeypatch
):
    """A 200 whose body is not valid JSON must raise the agreement-platform
    taxonomy (config error) — never leak a raw ValueError out of the adapter."""

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "not json"
        resp.json.side_effect = ValueError("invalid JSON")
        return resp

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    with pytest.raises(ap.AgreementPlatformConfigError):
        docuseal.list_submission_documents("1001")


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


# ---------------------------------------------------------------------------
# stream_submission_document — document streaming (P-something DocuSeal preview)
# ---------------------------------------------------------------------------


def _doc_stream_response(chunk=b"%PDF-1.7 fake bytes", url=""):
    resp = MagicMock()
    resp.status_code = 200
    resp.iter_content = lambda chunk_size: iter([chunk])
    resp.close = MagicMock()
    resp.url = url
    return resp


def test_stream_submission_document_selects_pdf_first_and_streams(
    docuseal_settings, monkeypatch
):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["stream"] = kwargs.get("stream")
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "agreement.pdf",
                            "content_type": "application/pdf",
                            "url": "https://sign.example/docs/501.pdf",
                        },
                        {
                            "filename": "attachment.png",
                            "content_type": "image/png",
                            "url": "https://sign.example/docs/502.png",
                        },
                    ]
                },
            )
        resp = _doc_stream_response()
        captured["response"] = resp
        return resp

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    stream = docuseal.stream_submission_document("1001")

    assert stream.filename == "agreement.pdf"
    assert stream.content_type == "application/pdf"
    assert b"".join(stream.chunks).startswith(b"%PDF-")
    assert captured["url"] == "https://sign.example/docs/501.pdf"
    assert captured["stream"] is True
    captured["response"].close.assert_called_once()


def test_stream_submission_document_falls_back_to_first_item_without_pdf(
    docuseal_settings, monkeypatch
):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "attachment.png",
                            "content_type": "image/png",
                            "url": "https://sign.example/docs/502.png",
                        }
                    ]
                },
            )
        captured["url"] = url
        resp = _doc_stream_response(chunk=b"PNG")
        captured["response"] = resp
        return resp

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    stream = docuseal.stream_submission_document("1001")
    assert stream.filename == "attachment.png"
    assert stream.content_type == "image/png"
    assert captured["url"] == "https://sign.example/docs/502.png"
    assert b"".join(stream.chunks) == b"PNG"
    captured["response"].close.assert_called_once()


def test_stream_submission_document_empty_documents_raises_not_found(
    docuseal_settings, monkeypatch
):
    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request",
        lambda *a, **kw: _mock_response(200, {"documents": []}),
    )
    with pytest.raises(ap.AgreementPlatformNotFoundError):
        docuseal.stream_submission_document("1001")


def test_stream_submission_document_fetch_404_raises_not_found(
    docuseal_settings, monkeypatch
):
    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "agreement.pdf",
                            "content_type": "application/pdf",
                            "url": "https://sign.example/docs/501.pdf",
                        }
                    ]
                },
            )
        return _mock_response(404, {"error": "gone"})

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )
    with pytest.raises(ap.AgreementPlatformNotFoundError):
        docuseal.stream_submission_document("1001")


def test_stream_submission_document_fetch_5xx_raises_transient(
    docuseal_settings, monkeypatch
):
    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "agreement.pdf",
                            "content_type": "application/pdf",
                            "url": "https://sign.example/docs/501.pdf",
                        }
                    ]
                },
            )
        return _mock_response(502, {"error": "boom"})

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )
    with pytest.raises(ap.AgreementPlatformTransientError):
        docuseal.stream_submission_document("1001")


def test_stream_submission_document_fetch_401_raises_auth(
    docuseal_settings, monkeypatch
):
    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "agreement.pdf",
                            "content_type": "application/pdf",
                            "url": "https://sign.example/docs/501.pdf",
                        }
                    ]
                },
            )
        return _mock_response(401, {"error": "unauthorized"})

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )
    with pytest.raises(ap.AgreementPlatformAuthError):
        docuseal.stream_submission_document("1001")


def test_stream_submission_document_timeout_raises_transient(
    docuseal_settings, monkeypatch
):
    import requests

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "agreement.pdf",
                            "content_type": "application/pdf",
                            "url": "https://sign.example/docs/501.pdf",
                        }
                    ]
                },
            )
        raise requests.Timeout("slow")

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )
    with pytest.raises(ap.AgreementPlatformTransientError):
        docuseal.stream_submission_document("1001")


def test_stream_submission_document_closes_response_on_iteration_error(
    docuseal_settings, monkeypatch
):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        if url.endswith("/documents"):
            return _mock_response(
                200,
                {
                    "documents": [
                        {
                            "filename": "agreement.pdf",
                            "content_type": "application/pdf",
                            "url": "https://sign.example/docs/501.pdf",
                        }
                    ]
                },
            )
        resp = MagicMock()
        resp.status_code = 200

        def boom(chunk_size):
            raise RuntimeError("mid-stream")

        resp.iter_content = boom
        resp.close = MagicMock()
        captured["response"] = resp
        return resp

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    with pytest.raises(RuntimeError):
        list(docuseal.stream_submission_document("1001").chunks)
    captured["response"].close.assert_called_once()


# ---------------------------------------------------------------------------
# create_submission send_email flag
# ---------------------------------------------------------------------------


def test_create_submission_defaults_send_email_true(
    docuseal_settings, monkeypatch
):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["json"] = kwargs.get("json")
        return _mock_response(
            201,
            [
                {
                    "submission_id": 1001,
                    "status": "sent",
                    "embed_src": "https://sign.example/s/abc",
                }
            ],
        )

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    docuseal.create_submission(_FakeAgreement())
    assert captured["json"]["send_email"] is True


def test_create_submission_passes_send_email_false(
    docuseal_settings, monkeypatch
):
    captured = {}

    def fake_request(method, url, headers=None, timeout=None, **kwargs):
        captured["json"] = kwargs.get("json")
        return _mock_response(
            201,
            [
                {
                    "submission_id": 1001,
                    "status": "sent",
                    "embed_src": "https://sign.example/s/abc",
                }
            ],
        )

    monkeypatch.setattr(
        "apps.integrations.docuseal.requests.request", fake_request
    )

    docuseal.create_submission(_FakeAgreement(), send_email=False)
    assert captured["json"]["send_email"] is False

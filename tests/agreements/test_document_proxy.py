"""Tests for apps.agreements.document_proxy.build_agreement_document_response.

The proxy builds a ``StreamingHttpResponse`` from the agreement-platform
document stream (stub mode in tests yields deterministic ``%PDF-`` bytes).
It must default to ``application/pdf`` content type, fall back to the
``līgums.pdf`` filename when the stream supplies none, and only accept
``inline`` / ``attachment`` dispositions (anything else → Http404).

The proxy is expected to read the platform stream through the shared
``apps.integrations.agreement_platform.stream_submission_document`` boundary
(the module is imported as ``agreement_platform``, matching the repo's
members/admin.py + registrations/admin.py convention).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.http import Http404, StreamingHttpResponse

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member

pytestmark = pytest.mark.django_db


@pytest.fixture
def agreement_with_external_id(agreement_member):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.external_id = "stub-1"
    a.save(update_fields=["external_id"])
    return a


def _build(agreement, disposition):
    from apps.agreements.document_proxy import build_agreement_document_response

    return build_agreement_document_response(agreement, disposition=disposition)


def test_returns_streaming_response(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    resp = _build(agreement_with_external_id, "inline")
    assert isinstance(resp, StreamingHttpResponse)
    assert resp.status_code == 200


def test_streams_stub_pdf_bytes(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    resp = _build(agreement_with_external_id, "inline")
    body = b"".join(resp.streaming_content)
    assert body.startswith(b"%PDF-")


def test_content_type_defaults_to_application_pdf(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    resp = _build(agreement_with_external_id, "inline")
    assert resp["Content-Type"] == "application/pdf"


def test_inline_disposition(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    resp = _build(agreement_with_external_id, "inline")
    assert "inline" in resp["Content-Disposition"]


def test_attachment_disposition_sets_filename(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    resp = _build(agreement_with_external_id, "attachment")
    assert "attachment" in resp["Content-Disposition"]
    assert "filename" in resp["Content-Disposition"]


def test_invalid_disposition_raises_http404(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    with pytest.raises(Http404):
        _build(agreement_with_external_id, "bogus")


def test_uses_platform_stream_with_external_id(settings, agreement_with_external_id):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    from apps.integrations import agreement_platform as ap

    fake = ap.DocumentStream(
        filename="a.pdf",
        content_type="application/pdf",
        chunks=iter([b"%PDF-1"]),
    )
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        return_value=fake,
    ) as spy:
        _build(agreement_with_external_id, "inline")
    spy.assert_called_once_with("stub-1")


def test_fallback_filename_and_content_type_when_stream_empty(
    settings, agreement_with_external_id
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    from apps.integrations import agreement_platform as ap

    fake = ap.DocumentStream(filename="", content_type="", chunks=iter([b"%PDF-1"]))
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        return_value=fake,
    ):
        resp = _build(agreement_with_external_id, "attachment")
    assert (
        resp["Content-Disposition"]
        == "attachment; filename*=utf-8''l%C4%ABgums.pdf"
    )
    assert resp["Content-Type"] == "application/pdf"


def test_fallback_filename_serializes_to_ascii_safe_attachment_header(
    settings, agreement_with_external_id
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    from apps.integrations import agreement_platform as ap

    fake = ap.DocumentStream(filename="", content_type="", chunks=iter([b"%PDF-1"]))
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        return_value=fake,
    ):
        resp = _build(agreement_with_external_id, "attachment")
    # WSGI headers must be latin-1 encodable: the RFC 6266 ``filename*``
    # form carries the Latvian diacritic percent-encoded, so serialization
    # must succeed instead of raising UnicodeEncodeError.
    serialized = resp.serialize_headers()
    assert b"filename*=utf-8''l%C4%ABgums.pdf" in serialized


def test_fallback_filename_serializes_to_ascii_safe_inline_header(
    settings, agreement_with_external_id
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    from apps.integrations import agreement_platform as ap

    fake = ap.DocumentStream(filename="", content_type="", chunks=iter([b"%PDF-1"]))
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        return_value=fake,
    ):
        resp = _build(agreement_with_external_id, "inline")
    serialized = resp.serialize_headers()
    assert b"inline; filename*=utf-8''l%C4%ABgums.pdf" in serialized

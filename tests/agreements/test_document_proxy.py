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


# The fixture's member is "Jānis Bērziņš" on an electronic agreement numbered
# FKC-2026-001, so the shipped filename carries three Latvian diacritics —
# which is what makes these header-serialization assertions worth having.
EXPECTED_ENCODED_NAME = (
    "j%C4%81nis-b%C4%93rzi%C5%86%C5%A1-electronic-fkc-2026-001.pdf"
)


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


def test_an_empty_provider_stream_still_gets_our_filename_and_a_pdf_type(
    settings, agreement_with_external_id
):
    """The filename no longer comes from the provider — it is built from the
    agreement (``<member>-<sign-type>-<number>.pdf``), so blanking the
    provider's own name cannot change it. The *content type* fallback this
    test also guarded is still real and still checked.

    Previously this asserted the generic ``līgums.pdf`` fallback, which the
    provider-name path used to reach; that path is gone. The fallback itself
    is covered as a unit at ``test_download_filename_falls_back_when_nothing_is_usable``
    — it is unreachable through the response path, because an Agreement
    always has a member.
    """
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    from apps.integrations import agreement_platform as ap

    fake = ap.DocumentStream(filename="", content_type="", chunks=iter([b"%PDF-1"]))
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        return_value=fake,
    ):
        resp = _build(agreement_with_external_id, "attachment")
    assert resp["Content-Type"] == "application/pdf"
    assert (
        resp["Content-Disposition"]
        == f"attachment; filename*=utf-8''{EXPECTED_ENCODED_NAME}"
    )


def test_filename_with_diacritics_serializes_to_an_ascii_safe_attachment_header(
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
    assert f"filename*=utf-8''{EXPECTED_ENCODED_NAME}".encode() in serialized


def test_filename_with_diacritics_serializes_to_an_ascii_safe_inline_header(
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
    assert (
        f"inline; filename*=utf-8''{EXPECTED_ENCODED_NAME}".encode() in serialized
    )


def test_download_filename_is_member_signtype_number():
    """<member-name>-<sign-type>-<number>.pdf, so a folder of downloads says
    whose agreement each one is — the provider's own name is an opaque
    agreement-<external id>.pdf."""
    from apps.agreements.document_proxy import download_filename

    class _Member:
        full_name = "Jānis Kalējs"

    class _Agreement:
        member_id = 1
        member = _Member()
        signing_path = "paper"
        agreement_number = "FKC-2026-021"

    assert download_filename(_Agreement()) == "jānis-kalējs-paper-fkc-2026-021.pdf"


def test_download_filename_drops_a_missing_number():
    """A freshly generated agreement has no number yet: the part is dropped
    rather than rendered as an empty segment."""
    from apps.agreements.document_proxy import download_filename

    class _Member:
        full_name = "Marta Zariņa"

    class _Agreement:
        member_id = 1
        member = _Member()
        signing_path = "electronic"
        agreement_number = ""

    assert download_filename(_Agreement()) == "marta-zariņa-electronic.pdf"


def test_download_filename_falls_back_when_nothing_is_usable():
    from apps.agreements.document_proxy import download_filename

    class _Agreement:
        member_id = None
        signing_path = ""
        agreement_number = ""

    assert download_filename(_Agreement()) == "līgums.pdf"

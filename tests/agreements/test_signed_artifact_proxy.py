"""P16-A: pure signed-artifact response proxy tests.

Covers the wishful ``apps.agreements.signed_artifact_proxy
.build_signed_artifact_response(agreement, *, disposition)`` contract:

* returns a ``FileResponse`` streaming the private ``FieldFile``;
* PDF may be inline (staff) or attachment; every ``.edoc`` response is
  forced attachment even when ``inline`` is requested;
* blank artifact / unknown disposition raises ``Http404``;
* original filename reaches ``Content-Disposition``;
* the helper never calls a provider and never touches DocuSeal/OCR/billing.

Red-phase discipline: the proxy module is not implemented yet, so it is
imported lazily and asserted to exist before every use.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.db.models.fields.files import FieldFile
from django.http import FileResponse, Http404
from django.utils import timezone

from apps.agreements import services as agreements_services
from apps.agreements.models import Agreement

pytestmark = pytest.mark.django_db


def _proxy_build():
    """Lazy import of the wishful helper — None while P16-A is absent."""
    try:
        from apps.agreements.signed_artifact_proxy import (
            build_signed_artifact_response,
        )
    except ImportError:
        return None
    return build_signed_artifact_response


def _proxy_outcome(agreement, disposition):
    """Run the helper and explicitly map the two intended outcomes.

    Returns ``http404`` when the helper raises ``Http404`` and ``ok`` for a
    streamable ``FileResponse``. The one relevant defect (dangling storage
    object leaking a raw ``FileNotFoundError``) is mapped to
    ``file_not_found_leak`` so the red phase reports a clean assertion
    failure instead of an unhandled error — nothing else is swallowed.
    """
    build = _proxy_build()
    from django.http import FileResponse, Http404

    if build is None:
        return "missing_proxy"
    try:
        response = build(agreement, disposition=disposition)
    except Http404:
        return "http404"
    except FileNotFoundError:
        return "file_not_found_leak"
    if not isinstance(response, FileResponse):
        return type(response).__name__
    try:
        b"".join(response.streaming_content)
    except FileNotFoundError:
        return "file_not_found_leak"
    return "ok"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agreement(agreement_member):
    return agreements_services.create_agreement_for_member(
        agreement_member, Agreement.SigningPath.PAPER
    )


def _store(agreement, filename, body, content_type):
    agreement.signed_artifact.save(filename, ContentFile(body), save=False)
    agreement.signed_artifact_original_filename = filename
    agreement.signed_artifact_content_type = content_type
    agreement.signed_artifact_file_size = len(body)
    now = timezone.now()
    agreement.signed_artifact_uploaded_at = agreement.signed_artifact_uploaded_at or now
    agreement.signed_artifact_updated_at = now
    agreement.save(
        update_fields=[
            "signed_artifact",
            "signed_artifact_original_filename",
            "signed_artifact_content_type",
            "signed_artifact_file_size",
            "signed_artifact_uploaded_at",
            "signed_artifact_updated_at",
            "updated_at",
        ]
    )
    agreement.refresh_from_db()
    return agreement


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_staff_pdf_can_be_inline(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    response = build(agreement, disposition="inline")
    assert isinstance(response, FileResponse)
    assert response["Content-Type"] == "application/pdf"
    assert "inline" in response["Content-Disposition"]
    assert b"%PDF-1.7\n" == b"".join(response.streaming_content)


def test_edoc_is_forced_attachment_even_when_inline(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.edoc", b"EDOC-2026", "")

    response = build(agreement, disposition="inline")
    assert "attachment" in response["Content-Disposition"]
    assert response["Content-Type"] == "application/octet-stream"


def test_pdf_attachment_disposition(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    response = build(agreement, disposition="attachment")
    assert "attachment" in response["Content-Disposition"]


def test_blank_artifact_is_404(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    # No artifact stored on this agreement.
    with pytest.raises(Http404):
        build(agreement, disposition="attachment")


def test_unknown_disposition_is_404(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    with pytest.raises(Http404):
        build(agreement, disposition="bogus")


def test_original_filename_reaches_content_disposition(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.PDF", b"%PDF-1.7\n", "application/pdf")

    response = build(agreement, disposition="attachment")
    assert "signed.PDF" in response["Content-Disposition"]


def test_source_is_private_field_file_and_no_provider_call(agreement):
    build = _proxy_build()
    assert build is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    assert isinstance(agreement.signed_artifact, FieldFile)

    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        create=True,
    ) as stream_spy:
        response = build(agreement, disposition="attachment")
    stream_spy.assert_not_called()
    assert b"".join(response.streaming_content) == b"%PDF-1.7\n"
    # The byte source is the private storage object, not a provider stream.
    assert response["Content-Type"] == "application/pdf"


def test_dangling_storage_object_yields_http404(agreement):
    """When the Agreement DB field names a private object that no longer
    exists in storage, serving must surface Http404 — never an unhandled
    FileNotFoundError."""
    assert _proxy_build() is not None
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "gone.pdf", b"%PDF-1.7\n", "application/pdf")
    name = agreement.signed_artifact.name
    agreement.signed_artifact.storage.delete(name)
    # DB field still names the object; the storage object is gone.
    assert agreement.signed_artifact.name == name
    assert agreement.signed_artifact.storage.exists(name) is False

    outcome = _proxy_outcome(agreement, "attachment")
    assert outcome == "http404", f"expected Http404, got {outcome!r}"
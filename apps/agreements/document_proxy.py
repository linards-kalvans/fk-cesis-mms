"""Shared server-side document proxy for the agreements app.

Serves an ``Agreement``'s document as a ``StreamingHttpResponse`` with the
requested ``Content-Disposition``. Routing is durable per row:

* ``local`` rows stream the immutable private PDF published by the local
  generation worker — verified size/hash, never a provider call and never an
  on-demand render;
* ``docuseal`` rows keep the existing server-side provider proxy (the DocuSeal
  document URL is fetched once on the server and never exposed in the rendered
  HTML or persisted in the database).

Three admin surfaces share this helper:

Three admin surfaces share this helper:

* Family hub (``GuardianAdmin.family_hub_docuseal_document_view``) —
  default disposition: ``attachment``.
* Registration admin
  (``RegistrationApplicationAdmin.docuseal_document_view``) — default
  disposition: ``attachment``.
* Agreement admin (``AgreementAdmin.docuseal_document_view``) — default
  disposition: ``inline`` (the change page embeds the PDF in an iframe).

The proxy is the only place that knows about ``Content-Disposition``; the
integration boundary stays disposition-agnostic.
"""

from __future__ import annotations

from typing import Literal

from django.http import Http404, StreamingHttpResponse
from django.http.response import content_disposition_header
from django.utils.text import slugify

from apps.agreements.models import Agreement
from apps.integrations import agreement_platform

_FALLBACK_FILENAME = "līgums.pdf"
_FALLBACK_CONTENT_TYPE = "application/pdf"

def download_filename(agreement: Agreement) -> str:
    """``<member-name>-<sign-type>-<number>.pdf`` for one agreement.

    The provider's own stream filename is an opaque
    ``agreement-<external id>.pdf``, which tells a reviewer holding a folder
    of downloads nothing about whose agreement it is. Each part is slugified
    with ``allow_unicode=True`` so a Latvian name survives: the header goes
    out through ``content_disposition_header``, which percent-encodes
    non-ASCII into the RFC 6266 ``filename*`` form, so diacritics are safe
    here (see this module's response docstring).

    A missing part is dropped rather than rendered as an empty segment - a
    freshly generated agreement has no number yet - and an agreement with no
    usable part at all falls back to the generic name.
    """
    parts = (
        agreement.member.full_name if agreement.member_id else "",
        agreement.signing_path or "",
        agreement.agreement_number or "",
    )
    slugs = [
        slug
        for slug in (slugify(part, allow_unicode=True) for part in parts)
        if slug
    ]
    if not slugs:
        return _FALLBACK_FILENAME
    return "-".join(slugs) + ".pdf"


_Disposition = Literal["inline", "attachment"]
_ALLOWED_DISPOSITIONS = ("inline", "attachment")


def audit_local_document_access(
    agreement: Agreement, *, request, disposition: str
) -> None:
    """Record one redacted staff view of a locally generated PDF.

    ``inline`` is a preview, ``attachment`` is a download — mirroring the
    documents-admin audit split. Only identifiers, backend and disposition
    are stored — never the stored filename, frozen snapshot, personal data or
    document contents.
    """
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent

    action = (
        AuditEvent.Action.DOCUMENT_PREVIEWED
        if disposition == "inline"
        else AuditEvent.Action.DOCUMENT_DOWNLOADED
    )
    record_audit_event(
        action=str(action),
        request=request,
        target=agreement,
        metadata={"document_backend": "local", "disposition": disposition},
    )


def _build_local_document_response(
    agreement: Agreement, *, disposition: _Disposition
) -> StreamingHttpResponse:
    """Stream a ready local PDF from private storage.

    Missing, unverifiable or corrupt bytes raise ``ValueError``; the caller
    must surface that as an error. This path never calls a provider and never
    triggers regeneration.
    """
    # Imported lazily: the generation module pulls in the worker/rendering
    # stack, which the provider proxy does not need.
    from apps.agreements.document_generation import (
        get_ready_document,
        read_ready_document_bytes,
    )

    document = get_ready_document(agreement)
    data = read_ready_document_bytes(document)

    response = StreamingHttpResponse(iter((data,)), content_type=_FALLBACK_CONTENT_TYPE)
    response["Content-Disposition"] = content_disposition_header(
        disposition == "attachment", download_filename(agreement)
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    # Inline preview is intentionally embeddable only by this same origin
    # (the admin change page iframe). A forced download never needs framing.
    response["X-Frame-Options"] = (
        "SAMEORIGIN" if disposition == "inline" else "DENY"
    )
    return response


def build_agreement_document_response(
    agreement: Agreement,
    *,
    disposition: _Disposition,
) -> StreamingHttpResponse:
    """Return a streaming response for the agreement's document.

    ``disposition`` must be one of ``"inline"`` (iframe) or ``"attachment"``
    (forced download); any other value raises ``Http404`` so a typo'd query
    string cannot accidentally stream the PDF as plain ``text/html``.

    Local rows serve the immutable private PDF and fail closed on missing or
    corrupt bytes. Legacy ``docuseal`` rows keep the provider stream as their
    single source of bytes; a stray local ``external_id`` never reaches the
    provider because routing is decided by ``document_backend``.

    The fallback filename ``līgums.pdf`` is the only place where the
    Latvian diacritic lives outside the database, so the
    ``Content-Disposition`` header is built via Django's
    ``content_disposition_header`` helper, which emits the RFC 6266
    ``filename*=utf-8''…`` percent-encoded form. Writing the raw
    ``filename="līgums.pdf"`` through ``response["Content-Disposition"]``
    would instead route through ``ResponseHeaders`` and end up encoded
    as ``=?utf-8?q?...?=`` MIME words; the helper keeps the value
    ASCII-safe so WSGI serialization (``response.serialize_headers``)
    succeeds and the browser receives a well-formed response.
    """
    if disposition not in _ALLOWED_DISPOSITIONS:
        raise Http404

    if agreement.document_backend == Agreement.DocumentBackend.LOCAL:
        return _build_local_document_response(
            agreement, disposition=disposition
        )

    stream = agreement_platform.stream_submission_document(agreement.external_id)
    # Our own descriptive name, not the provider's agreement-<external id>.pdf.
    filename = download_filename(agreement)
    content_type = stream.content_type or _FALLBACK_CONTENT_TYPE

    response = StreamingHttpResponse(stream.chunks, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(
        disposition == "attachment", filename
    )
    return response

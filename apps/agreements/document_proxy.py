"""Shared server-side document proxy for the agreements app.

Converts an ``Agreement``'s DocuSeal-generated PDF into a
``StreamingHttpResponse`` with the requested ``Content-Disposition``. The
platform stream is the only source of bytes — the DocuSeal document URL is
fetched once on the server and never exposed in the rendered HTML or
persisted in the database.

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

from apps.agreements.models import Agreement
from apps.integrations import agreement_platform


_FALLBACK_FILENAME = "līgums.pdf"
_FALLBACK_CONTENT_TYPE = "application/pdf"

_Disposition = Literal["inline", "attachment"]
_ALLOWED_DISPOSITIONS = ("inline", "attachment")


def build_agreement_document_response(
    agreement: Agreement,
    *,
    disposition: _Disposition,
) -> StreamingHttpResponse:
    """Return a streaming response for the agreement's generated PDF.

    ``disposition`` must be one of ``"inline"`` (iframe) or ``"attachment"``
    (forced download); any other value raises ``Http404`` so a typo'd query
    string cannot accidentally stream the PDF as plain ``text/html``.

    The platform stream is the single source of bytes. The DocuSeal URL
    never reaches the browser: ``stream_submission_document`` fetches the
    selected document server-side and yields ``%PDF-`` chunks through
    Django. The HTTP fallback (empty stream filename / content type) only
    fires when the provider returns a malformed ``DocumentStream``; in
    practice both fields are populated by the real provider.

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

    stream = agreement_platform.stream_submission_document(agreement.external_id)
    filename = stream.filename or _FALLBACK_FILENAME
    content_type = stream.content_type or _FALLBACK_CONTENT_TYPE

    response = StreamingHttpResponse(stream.chunks, content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(
        disposition == "attachment", filename
    )
    return response

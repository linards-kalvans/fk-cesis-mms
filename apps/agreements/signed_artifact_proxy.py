"""Pure streaming helper for an Agreement's private signed artifact.

Converts an already-authorized ``Agreement``'s ``signed_artifact``
``FieldFile`` into a ``FileResponse`` with the requested
``Content-Disposition``. The helper performs no authorization and no provider
call — surface-specific views own authorization and pass only owned rows.

Rules:

* blank artifact or unknown disposition -> ``Http404``;
* PDF may be ``inline`` (staff preview) or ``attachment``;
* every ``.edoc`` response is forced ``attachment`` even when ``inline`` was
  requested;
* ``Content-Disposition`` carries the original uploaded filename;
* the byte source is the private storage ``FieldFile`` — ``FieldFile.url``,
  DocuSeal, OCR, and billing are never touched.
"""

from __future__ import annotations

from typing import Literal

from django.http import FileResponse, Http404

from apps.agreements.models import Agreement

_Disposition = Literal["inline", "attachment"]
_ALLOWED_DISPOSITIONS = ("inline", "attachment")


def build_signed_artifact_response(
    agreement: Agreement,
    *,
    disposition: _Disposition,
) -> FileResponse:
    """Return a ``FileResponse`` streaming the agreement's signed artifact.

    ``disposition`` must be one of ``"inline"`` or ``"attachment"``; any other
    value (or a blank artifact) raises ``Http404`` so a typo'd query string
    cannot accidentally stream the private file.
    """
    if disposition not in _ALLOWED_DISPOSITIONS or not agreement.signed_artifact:
        raise Http404
    is_pdf = str(agreement.signed_artifact_original_filename).lower().endswith(
        ".pdf"
    )
    as_attachment = disposition == "attachment" or not is_pdf
    try:
        agreement.signed_artifact.open("rb")
    except FileNotFoundError:
        # DB names a private object that no longer exists in storage —
        # surface the same 404 the blank-artifact path uses, never a raw
        # FileNotFoundError.
        raise Http404
    return FileResponse(
        agreement.signed_artifact,
        as_attachment=as_attachment,
        filename=agreement.signed_artifact_original_filename,
        content_type="application/pdf" if is_pdf else "application/octet-stream",
    )
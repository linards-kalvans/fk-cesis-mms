"""Document access service — admin authorization + file response."""

from django.http import FileResponse, Http404

from apps.documents.models import Document


def get_admin_accessible_document(*, document_id: int, user) -> Document:
    """Return an active document accessible by an admin user.

    Raises ``Http404`` when the user is not authenticated, is not staff,
    or the document does not exist / is soft-deleted / has no file.
    """
    if not user.is_authenticated or not user.is_staff:
        raise Http404

    document = (
        Document.objects.filter(
            pk=document_id,
            deleted_at__isnull=True,
        )
        .exclude(file="")
        .first()
    )
    if document is None:
        raise Http404
    return document  # type: ignore[no-any-return]


def _is_trusted_pdf(document: Document) -> bool:
    """True only when both the filename extension and MIME type are PDF.

    This is deliberately narrow: the Admin Hub embeds only genuinely labelled
    PDFs. An image renamed to ``.pdf`` (or a PDF sent with a non-PDF MIME
    type) keeps the default ``X-Frame-Options: DENY``.
    """
    filename = document.original_filename or document.file.name or ""
    extension_is_pdf = (
        "." in filename and filename.rsplit(".", 1)[1].lower() == "pdf"
    )
    content_type = (document.content_type or "").split(";", 1)[0].strip().lower()
    return extension_is_pdf and content_type == "application/pdf"


def build_document_response(*, document: Document, disposition: str) -> FileResponse:
    """Build a streaming ``FileResponse`` for *document*.

    Parameters
    ----------
    disposition : "inline" or "attachment"
    """
    if disposition not in {"inline", "attachment"}:
        raise ValueError("disposition must be inline or attachment")

    try:
        document.file.open("rb")
    except FileNotFoundError:
        raise Http404("Document file missing from storage")
    response = FileResponse(
        document.file,
        as_attachment=disposition == "attachment",
        filename=document.original_filename,
        content_type=document.content_type or "application/octet-stream",
    )
    if disposition == "inline":
        response.headers["Content-Disposition"] = (
            f'inline; filename="{document.original_filename}"'
        )
        # The Admin Hub renders a trusted PDF in a same-origin <iframe>. The
        # clickjacking middleware keeps DENY for every other upload; only this
        # narrow, verified PDF + inline case opts in to same-origin framing.
        # Authorization, auditing and the attachment path are unchanged.
        if _is_trusted_pdf(document):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

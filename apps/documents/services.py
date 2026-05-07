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
    return response

"""Protected document preview/download views."""

from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from apps.documents.services import build_document_response, get_admin_accessible_document


def admin_document_preview(request: HttpRequest, document_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))
    document = get_admin_accessible_document(document_id=document_id, user=request.user)
    return build_document_response(document=document, disposition="inline")


def admin_document_download(request: HttpRequest, document_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), reverse("admin:login"))
    document = get_admin_accessible_document(document_id=document_id, user=request.user)
    return build_document_response(document=document, disposition="attachment")

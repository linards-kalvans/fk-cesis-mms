"""Protected document endpoint routes."""

from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("<int:document_id>/preview/", views.admin_document_preview, name="admin-document-preview"),
    path("<int:document_id>/download/", views.admin_document_download, name="admin-document-download"),
]

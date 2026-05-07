"""Django admin — Document registration with preview/download links."""

from typing import Any

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.documents.models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "kind",
        "uploaded_by_parent_at",
        "access_links",
    )
    readonly_fields = (
        "application",
        "kind",
        "original_filename",
        "content_type",
        "file_size",
        "ocr_status",
        "uploaded_by_parent_at",
        "deleted_at",
        "access_links",
    )
    fields = readonly_fields

    def access_links(self, obj: Document) -> Any:
        if not obj.file:
            return "\u2014"
        preview_url = reverse("documents:admin-document-preview", args=[obj.pk])
        download_url = reverse("documents:admin-document-download", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Preview</a> | '
            '<a href="{}">Download</a>',
            preview_url,
            download_url,
        )

    access_links.short_description = "Access"  # type: ignore[attr-defined]

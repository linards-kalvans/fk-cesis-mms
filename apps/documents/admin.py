"""Django admin — Document registration with preview/download links."""

from typing import Any

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.documents.models import Document
from apps.integrations.ocr import OCR_SUPPORTED_KINDS
from apps.integrations.tasks import enqueue_ocr_job


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "application",
        "kind",
        "ocr_status",
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
        "ocr_error_code",
        "uploaded_by_parent_at",
        "deleted_at",
        "access_links",
    )
    fields = readonly_fields
    actions = ["re_run_ocr"]

    def access_links(self, obj: Document) -> Any:
        if not obj.file:
            return "—"
        preview_url = reverse("documents:admin-document-preview", args=[obj.pk])
        download_url = reverse("documents:admin-document-download", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">Preview</a> | '
            '<a href="{}">Download</a>',
            preview_url,
            download_url,
        )

    access_links.short_description = "Access"  # type: ignore[attr-defined]

    @admin.action(description="Re-run OCR on selected documents")
    def re_run_ocr(self, request: Any, queryset: Any) -> None:
        enqueued = 0
        skipped = 0
        for document in queryset:
            if document.kind not in OCR_SUPPORTED_KINDS:
                skipped += 1
                continue
            document.ocr_status = Document.OcrStatus.PENDING
            document.ocr_error_code = ""
            document.save(update_fields=["ocr_status", "ocr_error_code", "updated_at"])
            enqueue_ocr_job(document.id)
            enqueued += 1
        if enqueued:
            self.message_user(request, f"Enqueued OCR for {enqueued} document(s).")
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} document(s) outside OCR scope.",
                level="warning",
            )

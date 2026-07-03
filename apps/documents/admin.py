"""Django admin — Document registration with preview/download links."""

from typing import Any

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.core.admin_badges import status_badge
from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent
from apps.documents.models import Document
from apps.integrations.ocr import OCR_SUPPORTED_KINDS
from apps.integrations.tasks import enqueue_ocr_job


class DocumentStateFilter(admin.SimpleListFilter):
    title = "Stāvoklis"
    parameter_name = "state"

    def lookups(self, request, model_admin):
        return [("active", "Aktīvs"), ("replaced", "Vēsturisks (aizstāts)")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "active":
            return queryset.filter(deleted_at__isnull=True)
        if value == "replaced":
            return queryset.filter(deleted_at__isnull=False)
        return queryset


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ["admin/fk_badges.css"]}

    list_display = (
        "id",
        "application",
        "kind",
        "state_badge",
        "ocr_status",
        "uploaded_by_parent_at",
        "access_links",
    )
    search_fields = ("application__member_full_name", "kind")
    list_filter = ("kind", "ocr_status", DocumentStateFilter)
    date_hierarchy = "uploaded_by_parent_at"
    ordering = ("-uploaded_by_parent_at",)
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

    @admin.display(description="Stāvoklis")
    def state_badge(self, obj: Document) -> Any:
        if obj.is_active:
            return status_badge("Aktīvs", "ok")
        return status_badge("Vēsturisks", "muted")

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

    def delete_model(self, request: Any, obj: Document) -> None:
        record_audit_event(
            action=str(AuditEvent.Action.DOCUMENT_DELETED),
            actor=request.user,
            target=obj,
            request=request,
            metadata={"kind": obj.kind, "reason": "admin_delete"},
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request: Any, queryset: Any) -> None:
        for obj in queryset:
            record_audit_event(
                action=str(AuditEvent.Action.DOCUMENT_DELETED),
                actor=request.user,
                target=obj,
                request=request,
                metadata={"kind": obj.kind, "reason": "admin_delete"},
            )
        super().delete_queryset(request, queryset)

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

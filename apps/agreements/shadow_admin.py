"""Read-only, staff-only shadow comparison; never changes the primary agreement."""

import logging

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, HttpResponseNotAllowed, StreamingHttpResponse
from django.http.response import content_disposition_header
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse

from apps.agreements.models import AgreementPDFShadow
from apps.agreements.shadow import primary_identity_matches, retry_pdf_shadow
from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent
from apps.integrations import agreement_platform

logger = logging.getLogger(__name__)


@admin.register(AgreementPDFShadow)
class AgreementPDFShadowAdmin(admin.ModelAdmin):
    list_display = ("id", "agreement", "status", "signing_path", "created_at")
    list_filter = ("status", "signing_path")
    list_select_related = ("agreement",)
    readonly_fields = ("agreement", "primary_external_id", "template_version", "signing_path",
                       "status", "error_code", "file_size", "sha256", "provenance",
                       "created_at", "completed_at")
    fields = readonly_fields
    change_form_template = "admin/agreements/agreementpdfshadow/change_form.html"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def get_urls(self):
        return [
            path("<int:object_id>/pdf/<str:source>/", self.admin_site.admin_view(self.pdf_view),
                 name="agreements_agreementpdfshadow_pdf"),
            path("<int:object_id>/retry/", self.admin_site.admin_view(self.retry_view),
                 name="agreements_agreementpdfshadow_retry"),
        ] + super().get_urls()

    def _row(self, request, object_id):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return get_object_or_404(AgreementPDFShadow, pk=object_id)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        row = self._row(request, object_id)
        context = dict(extra_context or {})
        context.update({
            "shadow": row,
            "shadow_pdf_url": reverse("admin:agreements_agreementpdfshadow_pdf", args=[row.pk, "local"]),
            "primary_pdf_url": reverse("admin:agreements_agreementpdfshadow_pdf", args=[row.pk, "primary"]),
            "shadow_retry_url": reverse("admin:agreements_agreementpdfshadow_retry", args=[row.pk]),
            "shadow_enabled": getattr(settings, "AGREEMENT_PDF_SHADOW_ENABLED", False),
        })
        return super().change_view(request, object_id, form_url, context)

    def pdf_view(self, request, object_id, source):
        if request.method not in {"GET", "HEAD"}:
            return HttpResponseNotAllowed(["GET", "HEAD"])
        row = self._row(request, object_id)
        disposition = request.GET.get("disposition", "inline")
        if disposition not in {"inline", "attachment"} or source not in {"local", "primary"}:
            raise Http404
        filename = f"agreement-{source}-comparison-{row.pk}.pdf"
        if source == "local":
            if row.status != "ready" or not row.file:
                raise Http404
            try:
                row.file.open("rb")
            except OSError:
                raise Http404
            response = FileResponse(row.file, content_type="application/pdf",
                                    as_attachment=disposition == "attachment", filename=filename)
        else:
            if not primary_identity_matches(row.provenance):
                raise Http404
            try:
                stream = agreement_platform.stream_submission_document(row.primary_external_id)
            except Exception:
                logger.warning("Primary agreement comparison document unavailable")
                raise Http404
            response = StreamingHttpResponse(stream.chunks, content_type="application/pdf")
            response["Content-Disposition"] = content_disposition_header(disposition == "attachment", filename)
        if disposition == "inline":
            # Paired comparison iframes are same-origin and staff-authorized.
            # Attachments keep the project-wide DENY default.
            response["X-Frame-Options"] = "SAMEORIGIN"
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["X-Content-Type-Options"] = "nosniff"
        record_audit_event(
            action=str(AuditEvent.Action.DOCUMENT_DOWNLOADED if disposition == "attachment"
                       else AuditEvent.Action.DOCUMENT_PREVIEWED),
            request=request, target=row, metadata={"source": source, "comparison_only": True},
        )
        return response

    def retry_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        row = self._row(request, object_id)
        try:
            retry_pdf_shadow(row, request.user)
        except ValueError:
            messages.error(request, "Salīdzinājumu pašlaik nevar atkārtot. Pārbaudiet statusu un iestatījumus.")
        else:
            messages.info(request, "Salīdzinājuma sagatavošana pieprasīta.")
        return redirect("admin:agreements_agreementpdfshadow_change", row.pk)

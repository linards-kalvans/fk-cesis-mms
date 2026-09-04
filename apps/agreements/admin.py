"""Django admin for the agreements app — read-only listing."""

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import path
from django.utils.html import format_html

from apps.agreements.document_proxy import build_agreement_document_response
from apps.agreements.messages import get_agreement_error_message
from apps.agreements.models import Agreement
from apps.agreements.presentation import build_agreement_document_links
from apps.agreements.signed_artifact_proxy import build_signed_artifact_response
from apps.core.admin_badges import status_badge
from apps.core.admin_links import admin_link, admin_links
from apps.integrations import agreement_platform


class AgreementSyncHealthFilter(admin.SimpleListFilter):
    title = "Sinhronizācijas stāvoklis"
    parameter_name = "sync_health"

    def lookups(self, request, model_admin):
        return [("failed", "Neizdevās"), ("ok", "OK"), ("none", "Nav sinhronizēts")]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "failed":
            return queryset.exclude(external_error_code="")
        if value == "ok":
            return queryset.exclude(external_state="").filter(external_error_code="")
        if value == "none":
            return queryset.filter(external_state="", external_error_code="")
        return queryset


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    class Media:
        css = {
            "all": [
                "admin/fk_badges.css",
                "admin/css/agreement_document.css",
            ]
        }

    list_display = ("member", "state", "sync_health_badge", "signing_path", "billing_plan", "first_billing_month", "is_current", "updated_at")
    list_filter = ("state", "signing_path", "is_current", AgreementSyncHealthFilter)
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)
    search_fields = ("member__full_name", "member__personal_id")
    # The DocuSeal ``external_url`` is intentionally absent from the change
    # form: it is a time-limited signing link, not a row the user should
    # bookmark, and the spec forbids rendering it on the admin page. The
    # ``fields`` declaration below mirrors ``readonly_fields`` minus
    # ``external_url`` so the field is never rendered.
    readonly_fields = (
        "related_records",
        "member",
        "is_current",
        "state",
        "signing_path",
        "billing_plan",
        "first_billing_month",
        "generated_at",
        "sent_at",
        "signed_at",
        "voided_at",
        "void_reason",
        "external_provider",
        "external_id",
        "external_state",
        "external_error_code",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields
    change_form_template = "admin/agreements/agreement/change_form.html"

    @admin.display(description="Sinhronizācija")
    def sync_health_badge(self, obj):
        if obj.external_error_code:
            return status_badge("Neizdevās", "fail", tooltip=get_agreement_error_message(obj.external_error_code))
        if obj.external_state:
            return status_badge(obj.external_state, "ok")
        return status_badge("—", "muted")

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        member = obj.member
        source_application = getattr(member, "source_application", None)
        billing_records = list(obj.billing_records.order_by("-created_at")) if obj.pk else []
        return format_html(
            "<strong>Biedrs:</strong> {}<br>"
            "<strong>Vecāks:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_link(member),
            admin_link(member.guardian),
            admin_link(source_application),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        # Read-only change page access for any signed-in staff. Edit / create
        # stay locked via has_change_permission / has_add_permission.
        return bool(request.user.is_authenticated and request.user.is_staff)

    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/docuseal-document/",
                self.admin_site.admin_view(self.docuseal_document_view),
                name="agreements_agreement_docuseal_document",
            ),
            path(
                "<int:object_id>/signed-artifact/",
                self.admin_site.admin_view(self.signed_artifact_view),
                name="agreements_agreement_signed_artifact",
            ),
        ]
        return custom + super().get_urls()

    def docuseal_document_view(self, request, object_id):
        """Stream the generated agreement PDF through the shared proxy.

        Default disposition is ``inline`` (the change page embeds the PDF
        in an iframe). ``?disposition=attachment`` switches to a forced
        download. Invalid disposition values return ``Http404`` (handled
        by the proxy); missing ``external_id`` and provider errors render
        a Latvian admin message + redirect to the change page.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        disposition = request.GET.get("disposition", "inline")
        agreement = get_object_or_404(Agreement, pk=object_id)
        if not agreement.external_id:
            self.message_user(
                request,
                "DocuSeal sūtījums vēl nav izveidots.",
                level="error",
            )
            return redirect(
                "admin:agreements_agreement_change", agreement.pk
            )
        try:
            return build_agreement_document_response(
                agreement, disposition=disposition
            )
        except Http404:
            raise
        except agreement_platform.AgreementPlatformError:
            # Latvian generic error — never the raw provider exception text.
            self.message_user(
                request,
                "Radās kļūda saziņā ar DocuSeal.",
                level="error",
            )
            return redirect(
                "admin:agreements_agreement_change", agreement.pk
            )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        """Inject the document-link list so the change template can render
        the inline iframe + attachment download for the current row."""
        from django.urls import reverse

        extra_context = extra_context or {}
        agreement = self.get_object(request, object_id)
        if agreement is not None and agreement.external_id:

            def _url_builder(_a):
                return str(
                    reverse(
                        "admin:agreements_agreement_docuseal_document",
                        args=[agreement.pk],
                    )
                )

            extra_context["document_links"] = build_agreement_document_links(
                [agreement], url_builder=_url_builder
            )
        # P16-A: only when a signed artifact exists — the change template
        # renders the panel conditionally, never a raw storage URL.
        if agreement is not None and agreement.signed_artifact:
            extra_context["signed_artifact_url"] = str(
                reverse(
                    "admin:agreements_agreement_signed_artifact",
                    args=[agreement.pk],
                )
            )
        return super().change_view(
            request, object_id, form_url, extra_context
        )

    def signed_artifact_view(self, request, object_id):
        """Stream the signed PDF/.edoc artifact through the shared proxy.

        Staff with view permission only. Default disposition is ``inline``
        (the change page embeds the PDF in an iframe);
        ``?disposition=attachment`` forces a download. Missing agreement,
        blank artifact, and invalid disposition values are 404.
        """
        if not self.has_view_permission(request):
            raise PermissionDenied
        disposition = request.GET.get("disposition", "inline")
        if disposition not in {"inline", "attachment"}:
            raise Http404
        agreement = get_object_or_404(Agreement, pk=object_id)
        return build_signed_artifact_response(
            agreement, disposition=disposition
        )

"""Django admin for registrations app."""

from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.agreements.services import sync_application_signing_path_to_agreement
from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.registrations.exports import application_columns, application_row
from apps.registrations.models import RegistrationApplication


@admin.register(RegistrationApplication)
class RegistrationApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "member_full_name",
        "guardian_contact_email",
        "status",
        "submitted_at",
        "review_link",
    )
    list_filter = ("status",)
    search_fields = ("member_full_name", "parent_account__email", "guardian__full_name")
    readonly_fields = (
        "status",
        "submitted_at",
        "review_message",
        "reviewed_by",
        "reviewed_at",
        "approved_member",
        # Consent stamps are gate-controlled (P4 Slice C). Never editable in admin.
        "personal_data_consent_at",
        "personal_data_consent_version",
        "created_at",
        "updated_at",
    )

    actions = ["export_csv", "export_csv_with_sensitive"]

    def get_queryset(self, request):
        # guardian_contact_email (list_display) traverses parent_account, and
        # guardian__full_name is searched — select_related avoids a changelist N+1.
        return super().get_queryset(request).select_related("guardian", "parent_account")

    def _export_applications(self, request, queryset, *, sensitive: bool):
        # Self-sufficient: the guardian accessors traverse guardian + parent_account,
        # so apply select_related here (don't rely on the admin's get_queryset — the
        # method may be called with a bare queryset).
        queryset = queryset.select_related("guardian", "parent_account")
        rows = [application_row(a, sensitive=sensitive) for a in queryset]
        record_audit_event(
            action=str(AuditEvent.Action.DATA_EXPORTED),
            actor=request.user, request=request,
            target_type="registrationapplication",
            target_repr=f"registration export ({len(rows)} rows)",
            metadata={"count": len(rows), "sensitive": sensitive, "format": "csv"},
        )
        ts = timezone.localtime().strftime("%Y%m%d-%H%M")
        return csv_response(
            filename=f"registrations-{ts}.csv",
            columns=application_columns(sensitive=sensitive),
            rows=rows,
        )

    @admin.action(description="Eksportēt CSV (bez sensitīviem datiem)")
    def export_csv(self, request, queryset):
        return self._export_applications(request, queryset, sensitive=False)

    @admin.action(description="Eksportēt CSV ar sensitīviem datiem")
    def export_csv_with_sensitive(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, "Nepieciešamas superlietotāja tiesības.", level=messages.ERROR)
            return None
        return self._export_applications(request, queryset, sensitive=True)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("export_csv_with_sensitive", None)
        return actions

    def review_link(self, obj) -> str:  # type: ignore[override]
        """Link to the custom review detail page."""
        if obj.pk:
            url = reverse("registrations:admin-review-detail", args=[obj.pk])
            return format_html('<a href="{}">Review</a>', url)  # type: ignore[return-value,no-any-return]
        return "-"

    review_link.short_description = "Review"  # type: ignore[assignment,attr-defined]
    review_link.admin_order_field = "pk"  # type: ignore[assignment,attr-defined]

    def save_model(self, request, obj, form, change):
        """Persist the application, then sync preferred_agreement_signing to
        the active agreement when it is still in `generated` state."""
        super().save_model(request, obj, form, change)
        sync_application_signing_path_to_agreement(obj)

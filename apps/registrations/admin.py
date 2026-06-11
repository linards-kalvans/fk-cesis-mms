"""Django admin for registrations app."""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from apps.agreements.services import sync_application_signing_path_to_agreement
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

    def get_queryset(self, request):
        # guardian_contact_email (list_display) traverses parent_account, and
        # guardian__full_name is searched — select_related avoids a changelist N+1.
        return super().get_queryset(request).select_related("guardian", "parent_account")

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

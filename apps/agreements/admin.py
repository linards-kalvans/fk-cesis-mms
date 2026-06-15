"""Django admin for the agreements app — read-only listing."""

from django.contrib import admin
from django.utils.html import format_html

from apps.agreements.models import Agreement
from apps.core.admin_links import admin_link, admin_links


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ("member", "state", "signing_path", "is_current", "updated_at")
    list_filter = ("state", "signing_path", "is_current")
    search_fields = ("member__full_name", "member__personal_id")
    readonly_fields = (
        "related_records",
        "member",
        "is_current",
        "state",
        "signing_path",
        "generated_at",
        "sent_at",
        "signed_at",
        "voided_at",
        "void_reason",
        "external_provider",
        "external_id",
        "external_state",
        "external_url",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        member = obj.member
        source_application = getattr(member, "source_application", None)
        billing_records = list(obj.billing_records.all()) if obj.pk else []
        return format_html(
            "<strong>Biedrs:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_link(member),
            admin_link(source_application),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

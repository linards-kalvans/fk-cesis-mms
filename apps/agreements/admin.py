"""Django admin for the agreements app — read-only listing."""

from django.contrib import admin

from apps.agreements.models import Agreement


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ("member", "state", "signing_path", "is_current", "updated_at")
    list_filter = ("state", "signing_path", "is_current")
    search_fields = ("member__full_name", "member__personal_id")
    readonly_fields = (
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

"""Read-only admin viewer for the AuditEvent log."""

from django.contrib import admin

from apps.core.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_label", "target_type", "target_repr", "ip_address")
    list_filter = ("action", "target_type", "created_at")
    search_fields = ("actor_label", "target_repr", "target_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

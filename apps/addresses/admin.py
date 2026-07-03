from __future__ import annotations

from django.contrib import admin

from apps.addresses.models import AddressImportRun


@admin.register(AddressImportRun)
class AddressImportRunAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "started_at", "finished_at", "region_codes", "group_count", "entry_count")
    list_filter = ("status", "source", "started_at")
    search_fields = ("source", "region_codes", "error_message")
    readonly_fields = (
        "source",
        "started_at",
        "finished_at",
        "status",
        "region_codes",
        "group_count",
        "entry_count",
        "error_message",
        "source_modified_at",
    )
    date_hierarchy = "started_at"
    ordering = ("-started_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)

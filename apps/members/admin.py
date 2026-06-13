"""Django admin for members app."""

from django.contrib import admin, messages
from django.utils import timezone

from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.members.exports import member_columns, member_row
from apps.members.models import Guardian, KitSizeOption, Member, TrainingGroup


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "phone")
    search_fields = ("full_name", "email", "personal_id")


@admin.register(TrainingGroup)
class TrainingGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "guardian", "birth_date", "training_group")
    list_filter = ("training_group",)
    search_fields = ("full_name", "personal_id")
    actions = ["export_csv", "export_csv_with_sensitive"]

    def _export_members(self, request, queryset, *, sensitive: bool):
        qs = queryset.select_related("guardian", "training_group")
        rows = [member_row(m, sensitive=sensitive) for m in qs]
        record_audit_event(
            action=str(AuditEvent.Action.DATA_EXPORTED),
            actor=request.user, request=request,
            target_type="member", target_repr=f"member export ({len(rows)} rows)",
            metadata={"count": len(rows), "sensitive": sensitive, "format": "csv"},
        )
        ts = timezone.localtime().strftime("%Y%m%d-%H%M")
        return csv_response(filename=f"members-{ts}.csv", columns=member_columns(sensitive=sensitive), rows=rows)

    @admin.action(description="Eksportēt CSV (bez sensitīviem datiem)")
    def export_csv(self, request, queryset):
        return self._export_members(request, queryset, sensitive=False)

    @admin.action(description="Eksportēt CSV ar sensitīviem datiem")
    def export_csv_with_sensitive(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, "Nepieciešamas superlietotāja tiesības.", level=messages.ERROR)
            return None
        return self._export_members(request, queryset, sensitive=True)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("export_csv_with_sensitive", None)
        return actions


@admin.register(KitSizeOption)
class KitSizeOptionAdmin(admin.ModelAdmin):
    list_display = ("kind", "label", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("label",)

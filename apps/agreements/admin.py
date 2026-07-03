"""Django admin for the agreements app — read-only listing."""

from django.contrib import admin
from django.utils.html import format_html

from apps.agreements.messages import get_agreement_error_message
from apps.agreements.models import Agreement
from apps.core.admin_badges import status_badge
from apps.core.admin_links import admin_link, admin_links


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
        css = {"all": ["admin/fk_badges.css"]}

    list_display = ("member", "state", "sync_health_badge", "signing_path", "billing_plan", "first_billing_month", "is_current", "updated_at")
    list_filter = ("state", "signing_path", "is_current", AgreementSyncHealthFilter)
    date_hierarchy = "generated_at"
    ordering = ("-generated_at",)
    search_fields = ("member__full_name", "member__personal_id")
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
        "external_url",
        "external_error_code",
        "created_at",
        "updated_at",
    )

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

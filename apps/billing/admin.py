"""Django admin for the billing app — plan config + draft-record review."""

from django.contrib import admin, messages

from apps.billing.models import BillingRecord, MembershipPlan
from apps.billing.services import recompute_billing_record


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name", "season", "annual_amount", "sibling_discount_percent",
        "installment_count", "first_installment_month", "is_active",
    )
    list_filter = ("season", "is_active")


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = (
        "member", "guardian_name", "season", "final_amount",
        "is_full_price", "payment_mode", "status", "external_status",
    )
    list_filter = ("season", "status", "payment_mode", "is_full_price", "external_status")
    search_fields = ("member__full_name", "member__guardian__full_name")
    readonly_fields = (
        "member", "plan", "agreement", "season", "base_amount", "is_full_price",
        "sibling_discount_percent_applied", "discount_amount", "final_amount",
        "payment_mode", "full_price_opt_out", "external_status", "external_error_code",
        "created_at", "updated_at",
    )
    fields = readonly_fields + (
        "manual_amount_override", "manual_override_reason", "status",
    )
    actions = ("recompute_from_plan", "push_to_invoice_ninja")

    @admin.display(description="Vecāks")
    def guardian_name(self, obj):
        return obj.member.guardian.full_name

    @admin.action(description="Pārrēķināt no plāna")
    def recompute_from_plan(self, request, queryset):
        count = 0
        for record in queryset:
            if record.status == BillingRecord.Status.DRAFT:
                recompute_billing_record(record)
                count += 1
        self.message_user(request, f"Pārrēķināti {count} ieraksti.")

    @admin.action(description="Izrakstīt rēķinus (Invoice Ninja)")
    def push_to_invoice_ninja(self, request, queryset):
        from apps.integrations.tasks import enqueue_push_billing_record

        pushed = 0
        skipped = 0
        for record in queryset:
            if record.status != BillingRecord.Status.CONFIRMED:
                skipped += 1
                continue
            enqueue_push_billing_record(record.pk)
            pushed += 1
        if skipped:
            self.message_user(
                request,
                f"Izrakstīti {pushed} rēķini. Izlaisti {skipped} (vispirms apstipriniet).",
                level=messages.WARNING,
            )
        else:
            self.message_user(request, f"Izrakstīti {pushed} rēķini.")

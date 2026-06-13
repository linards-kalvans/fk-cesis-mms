"""Django admin for the billing app — plan config + draft-record review."""

from django.contrib import admin, messages

from apps.billing.models import BillingInvoice, BillingRecord, MembershipPlan
from apps.billing.services import recompute_billing_record
from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name", "season", "annual_amount", "sibling_discount_percent",
        "installment_count", "first_installment_month", "payment_due_day", "is_active",
    )
    list_filter = ("season", "is_active")


class BillingInvoiceInline(admin.TabularInline):
    model = BillingInvoice
    extra = 0
    can_delete = False
    fields = (
        "sequence", "due_date", "amount", "external_invoice_id", "external_status",
        "payment_status", "paid_to_date", "balance", "last_payment_date", "last_synced_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = (
        "member", "guardian_name", "season", "final_amount",
        "is_full_price", "payment_mode", "status", "external_status",
        "payment_status", "payment_synced_at",
    )
    list_filter = (
        "season", "status", "payment_mode", "is_full_price",
        "external_status", "payment_status",
    )
    search_fields = ("member__full_name", "member__guardian__full_name")
    readonly_fields = (
        "member", "plan", "agreement", "season", "base_amount", "is_full_price",
        "sibling_discount_percent_applied", "discount_amount", "final_amount",
        "payment_mode", "full_price_opt_out", "external_status", "external_error_code",
        "payment_status", "payment_synced_at", "payment_error_code",
        "created_at", "updated_at",
    )
    fields = readonly_fields + (
        "manual_amount_override", "manual_override_reason", "status",
    )
    inlines = (BillingInvoiceInline,)
    actions = ("recompute_from_plan", "push_to_invoice_ninja", "sync_payments")

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
        unconfirmed = 0
        already = 0
        for record in queryset:
            if record.status != BillingRecord.Status.CONFIRMED:
                unconfirmed += 1
                continue
            if record.external_status == "synced":
                already += 1
                continue
            enqueue_push_billing_record(record.pk)
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_PUSH_TRIGGERED),
                actor=request.user, request=request, target=record,
            )
            pushed += 1
        parts = [f"Izrakstīti {pushed} rēķini."]
        if already:
            parts.append(f"Jau izrakstīti: {already}.")
        if unconfirmed:
            parts.append(f"Izlaisti {unconfirmed} (vispirms apstipriniet).")
        level = messages.WARNING if unconfirmed else messages.INFO
        self.message_user(request, " ".join(parts), level=level)

    @admin.action(description="Pārbaudīt maksājumus (Invoice Ninja)")
    def sync_payments(self, request, queryset):
        from apps.integrations.tasks import enqueue_sync_billing_record_payments

        synced = 0
        unconfirmed = 0
        for record in queryset:
            if record.status != BillingRecord.Status.CONFIRMED:
                unconfirmed += 1
                continue
            enqueue_sync_billing_record_payments(record.pk)
            record_audit_event(
                action=str(AuditEvent.Action.PAYMENT_SYNC_TRIGGERED),
                actor=request.user, request=request, target=record,
            )
            synced += 1
        parts = [f"Pieprasīta maksājumu pārbaude: {synced}."]
        if unconfirmed:
            parts.append(f"Izlaisti {unconfirmed} (vispirms apstipriniet).")
        level = messages.WARNING if unconfirmed else messages.INFO
        self.message_user(request, " ".join(parts), level=level)

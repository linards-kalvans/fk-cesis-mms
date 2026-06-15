"""Django admin for the billing app — plan config + draft-record review."""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme

from apps.billing.models import BillingInvoice, BillingRecord, MembershipPlan
from apps.billing.services import recompute_billing_record
from apps.core.admin_links import admin_link
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
        "member", "guardian_link", "agreement_link", "season", "final_amount",
        "is_full_price", "payment_mode", "status", "confirm_action",
        "external_status", "payment_status", "payment_synced_at",
    )
    change_form_template = "admin/billing/billingrecord/change_form.html"
    list_filter = (
        "season", "status", "payment_mode", "is_full_price",
        "external_status", "payment_status",
    )
    search_fields = ("member__full_name", "member__guardian__full_name")
    readonly_fields = (
        "related_records",
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

    def get_queryset(self, request):
        self._request = request  # confirm_action needs it for a per-row CSRF token
        # select_related: the guardian_link/agreement_link columns touch these per row.
        return super().get_queryset(request).select_related(
            "member", "member__guardian", "agreement"
        )

    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/confirm/",
                self.admin_site.admin_view(self.confirm_view),
                name="billing_billingrecord_confirm",
            ),
        ]
        return custom + super().get_urls()

    def confirm_view(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        record = get_object_or_404(BillingRecord, pk=object_id)
        if request.method != "POST":
            return self._safe_redirect(request, object_id)
        if record.status == BillingRecord.Status.DRAFT:
            record.status = BillingRecord.Status.CONFIRMED
            record.save(update_fields=["status", "updated_at"])
            self.message_user(request, "Ieraksts apstiprināts.")
        else:
            self.message_user(request, "Ieraksts jau ir apstiprināts.", level=messages.INFO)
        return self._safe_redirect(request, object_id)

    def _safe_redirect(self, request, object_id):
        nxt = request.POST.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(nxt)
        return redirect("admin:billing_billingrecord_change", object_id)

    @admin.display(description="Vecāks")
    def guardian_link(self, obj):
        return admin_link(obj.member.guardian)

    @admin.display(description="Līgums")
    def agreement_link(self, obj):
        return admin_link(obj.agreement)

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        source_application = getattr(obj.member, "source_application", None)
        return format_html(
            "<strong>Biedrs:</strong> {}<br>"
            "<strong>Vecāks:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Līgums:</strong> {}",
            admin_link(obj.member),
            admin_link(obj.member.guardian),
            admin_link(source_application),
            admin_link(obj.agreement),
        )  # type: ignore[return-value,no-any-return]

    @admin.display(description="Apstiprināt")
    def confirm_action(self, obj):
        if obj.status != BillingRecord.Status.DRAFT:
            return format_html("<span>✓ {}</span>", obj.get_status_display())
        confirm_url = reverse("admin:billing_billingrecord_confirm", args=[obj.pk])
        changelist_url = reverse("admin:billing_billingrecord_changelist")
        return format_html(  # type: ignore[return-value,no-any-return]
            '<form method="post" action="{}" style="display:inline">'
            '<input type="hidden" name="csrfmiddlewaretoken" value="{}">'
            '<input type="hidden" name="next" value="{}">'
            '<button type="submit" class="button">Apstiprināt</button>'
            "</form>",
            confirm_url, get_token(self._request), changelist_url,
        )

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

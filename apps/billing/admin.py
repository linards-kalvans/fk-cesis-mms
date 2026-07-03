"""Django admin for the billing app — plan config + draft-record review."""

from urllib.parse import urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme

from apps.billing.messages import get_invoice_error_message
from apps.billing.models import BillingAdjustment, BillingInvoice, BillingRecord, MembershipPlan
from apps.billing.services import (
    parse_first_billing_month,
    reassign_draft_billing_record,
    recompute_billing_record,
)
from apps.core.admin_badges import status_badge
from apps.core.admin_links import admin_link
from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name", "season", "annual_amount", "sibling_discount_percent",
        "installment_count", "first_installment_month", "payment_due_day",
        "is_default", "billing_start_cutoff_day", "is_active",
    )
    list_filter = ("season", "is_active", "is_default")
    search_fields = ("name", "season")


class BillingInvoiceInline(admin.TabularInline):
    model = BillingInvoice
    extra = 0
    can_delete = False
    fields = (
        "sequence", "due_date", "amount", "external_invoice_id", "external_status",
        "payment_status", "paid_to_date", "balance", "last_payment_date", "last_synced_at",
        "cancelled_at", "cancellation_reason",
        "external_cancellation_action", "external_cancellation_status", "external_cancellation_error_code",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class SyncHealthFilter(admin.SimpleListFilter):
    title = "Sinhronizācijas stāvoklis"
    parameter_name = "sync_health"

    def lookups(self, request, model_admin):
        return [
            ("ok", "OK"),
            ("failed", "Neizdevās"),
            ("pending", "Procesā"),
            ("none", "Nav sinhronizēts"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "ok":
            return queryset.filter(external_status="synced", external_error_code="")
        if value == "failed":
            return queryset.exclude(external_error_code="")
        if value == "pending":
            return queryset.exclude(external_status="").exclude(external_status="synced").filter(external_error_code="")
        if value == "none":
            return queryset.filter(external_status="", external_error_code="")
        return queryset


@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = (
        "member", "guardian_link", "agreement_link", "season", "final_amount",
        "is_full_price", "payment_mode", "status", "confirm_action",
        "external_status_badge", "payment_status_badge", "payment_synced_at",
    )
    change_form_template = "admin/billing/billingrecord/change_form.html"
    list_filter = (
        "season", "status", "payment_mode", "is_full_price",
        SyncHealthFilter, "payment_status", "plan",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    search_fields = ("member__full_name", "member__guardian__full_name")

    class Media:
        css = {"all": ["admin/fk_badges.css"]}
    readonly_fields = (
        "related_records",
        "reassign_link",
        "member", "plan", "agreement", "season",
        "first_billing_month",
        "base_amount", "is_full_price",
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

    def has_add_permission(self, request):
        # Billing records are created by the billing service, never hand-added in
        # admin (all fields are readonly; the add form would crash on obj.member).
        return False

    def get_queryset(self, request):
        # select_related: the guardian_link/agreement_link columns touch these per row.
        return super().get_queryset(request).select_related(
            "member", "member__guardian", "agreement"
        )

    def save_model(self, request, obj, form, change):
        # Audit a DRAFT→CONFIRMED transition made via the change form's status
        # dropdown + Save (the one-click buttons go through confirm_view instead).
        was_draft = bool(
            change
            and obj.pk
            and BillingRecord.objects.filter(
                pk=obj.pk, status=BillingRecord.Status.DRAFT
            ).exists()
        )
        super().save_model(request, obj, form, change)
        if was_draft and obj.status == BillingRecord.Status.CONFIRMED:
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
                actor=request.user, request=request, target=obj,
            )

    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/confirm/",
                self.admin_site.admin_view(self.confirm_view),
                name="billing_billingrecord_confirm",
            ),
            path(
                "<int:object_id>/reassign/",
                self.admin_site.admin_view(self.reassign_view),
                name="billing_billingrecord_reassign",
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
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
                actor=request.user, request=request, target=record,
            )
            self.message_user(request, "Ieraksts apstiprināts.")
        else:
            self.message_user(request, "Ieraksts jau ir apstiprināts.", level=messages.INFO)
        return self._safe_redirect(request, object_id)

    def reassign_view(self, request, object_id):
        """Two-step reassignment of a draft BillingRecord to a new plan + first
        billing month. GET renders a confirmation form; POST commits through
        the service. The service is the source of truth for guards (DRAFT
        only, no pushed/sent invoices)."""
        if not self.has_change_permission(request):
            raise PermissionDenied
        record = get_object_or_404(BillingRecord, pk=object_id)
        plans = MembershipPlan.objects.filter(is_active=True).order_by(
            "season", "name"
        )
        if request.method == "POST":
            raw_plan = request.POST.get("billing_plan", "").strip()
            if not raw_plan:
                self.message_user(
                    request, "Lūdzu izvēlieties norēķinu plānu.", level=messages.ERROR
                )
            else:
                plan = MembershipPlan.objects.filter(
                    pk=raw_plan, is_active=True
                ).first()
                if plan is None:
                    self.message_user(
                        request, "Nezināms norēķinu plāns.", level=messages.ERROR
                    )
                else:
                    first_billing_month = request.POST.get("first_billing_month", "").strip()
                    try:
                        if first_billing_month:
                            parse_first_billing_month(first_billing_month)
                        reassign_draft_billing_record(
                            record,
                            plan,
                            first_billing_month=first_billing_month,
                            actor=request.user,
                        )
                        self.message_user(request, "Norēķinu ieraksts pārpiešķirts.")
                        return redirect(
                            "admin:billing_billingrecord_change", object_id
                        )
                    except ValueError as exc:
                        raw = str(exc)
                        if "first billing month" in raw:
                            latvian = "Pirmajam mēnesim jābūt formātā GGGG-MM."
                        else:
                            latvian = raw
                        self.message_user(request, latvian, level=messages.ERROR)
        context = {
            **self.admin_site.each_context(request),
            "title": "Pārpiešķirt norēķinu ierakstu",
            "record": record,
            "plans": plans,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/billing/billingrecord/reassign_confirm.html",
            context,
        )

    def _safe_redirect(self, request, object_id):
        # The one-click buttons pass `next` in the formaction query string (GET);
        # keep POST support for any direct callers.
        nxt = request.POST.get("next") or request.GET.get("next", "")
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

    @admin.display(description="Pārpiešķiršana")
    def reassign_link(self, obj):
        """Surface a one-click button to the reassignment form for draft
        records with no pushed or sent invoices. Confirmed/locked records
        show '—' because the service refuses the reassign anyway."""
        if obj.status != BillingRecord.Status.DRAFT:
            return "—"
        if obj.invoices.exclude(external_invoice_id="").exists():
            return "—"
        if obj.invoices.filter(sent_at__isnull=False).exists():
            return "—"
        url = reverse("admin:billing_billingrecord_reassign", args=[obj.pk])
        return format_html(  # type: ignore[return-value,no-any-return]
            '<a class="button" href="{}">Pārpiešķirt melnrakstu</a>', url
        )

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
        formaction = f"{confirm_url}?{urlencode({'next': changelist_url})}"
        # A bare button (NOT a nested <form>): it rides the changelist's own POST
        # form + CSRF via formaction/formmethod. A nested <form> is invalid HTML —
        # the browser drops it and the button would submit the outer form instead.
        return format_html(  # type: ignore[return-value,no-any-return]
            '<button type="submit" class="button" formaction="{}" formmethod="post">'
            "Apstiprināt</button>",
            formaction,
        )

    @admin.display(description="IN statuss")
    def external_status_badge(self, obj):
        if obj.external_error_code:
            return status_badge("Neizdevās", "fail", tooltip=get_invoice_error_message(obj.external_error_code))
        if obj.external_status == "synced":
            return status_badge("Sinhronizēts", "ok")
        if obj.external_status:
            return status_badge(obj.external_status, "pending")
        return status_badge("—", "muted")

    @admin.display(description="Maksājums")
    def payment_status_badge(self, obj):
        if obj.payment_error_code:
            return status_badge("Kļūda", "fail", tooltip=get_invoice_error_message(obj.payment_error_code))
        if obj.payment_status == "paid":
            return status_badge(obj.get_payment_status_display(), "ok")
        if obj.payment_status == "partial":
            return status_badge(obj.get_payment_status_display(), "pending")
        if obj.payment_status:
            return status_badge(obj.get_payment_status_display(), "muted")
        return status_badge("—", "muted")

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


@admin.register(BillingAdjustment)
class BillingAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        "member_link",
        "invoice_link",
        "amount",
        "external_status_badge",
        "requires_staff_apply",
        "created_at",
    )
    list_filter = ("kind", "external_status", "requires_staff_apply")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "billing_record", "invoice", "agreement_event", "kind", "amount", "reason",
        "external_credit_id", "external_status", "external_error_code",
        "applied_to_external_invoice_id", "requires_staff_apply", "created_by",
        "created_at", "updated_at",
    )
    actions = ["retry_credit_note"]

    class Media:
        css = {"all": ["admin/fk_badges.css"]}

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "billing_record__member__guardian",
            "invoice__billing_record",
        )

    @admin.display(description="Biedrs")
    def member_link(self, obj):
        return admin_link(obj.billing_record.member)

    @admin.display(description="Rēķins")
    def invoice_link(self, obj):
        return admin_link(obj.invoice)

    @admin.display(description="Statuss")
    def external_status_badge(self, obj):
        if obj.external_error_code:
            return status_badge(
                "Neizdevās",
                "fail",
                tooltip=get_invoice_error_message(obj.external_error_code),
            )
        if obj.external_status == "applied":
            return status_badge("Piemērots", "ok")
        if obj.external_status:
            return status_badge(obj.external_status, "pending")
        return status_badge("—", "muted")

    @admin.action(description="Mēģināt vēlreiz izveidot kredītrēķini")
    def retry_credit_note(self, request, queryset):
        from apps.integrations.tasks import enqueue_create_credit_note

        enqueued = 0
        skipped = 0
        for adjustment in queryset:
            if adjustment.external_status != "failed":
                skipped += 1
                continue
            enqueue_create_credit_note(adjustment.pk)
            enqueued += 1
        parts = [f"Ielikti rindā {enqueued} kredītrēķini."]
        if skipped:
            parts.append(f"Izlaisti {skipped} (neizdevušies tikai).")
        self.message_user(request, " ".join(parts))

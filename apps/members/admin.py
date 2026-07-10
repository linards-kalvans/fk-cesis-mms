"""Django admin for members app."""

import datetime

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email
from apps.agreements.models import Agreement
from apps.agreements.services import (
    get_current_agreement,
    mark_agreement_sent,
    mark_agreement_signed,
    record_minor_amendment,
    regenerate_agreement,
    set_billing_setup,
    start_material_amendment,
    void_agreement,
)
from apps.billing.models import BillingRecord, MembershipPlan
from apps.billing.services import (
    DiscontinuationInvoiceError,
    PaidInvoiceSelected,
    parse_first_billing_month,
    renew_member_billing,
)
from apps.core.admin_links import admin_link, admin_links
from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.integrations import agreement_platform
from apps.integrations.tasks import (
    enqueue_create_agreement_submission,
    enqueue_push_billing_record,
    enqueue_sync_agreement_submission,
    enqueue_sync_billing_record_payments,
)
from apps.members.exports import member_columns, member_row
from apps.members.family_hub import (
    _row_for_guardian,
    build_family_hub_context,
    build_family_queue_rows,
)
from apps.members.models import Guardian, KitSizeOption, Member, TrainingGroup
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    reject_application,
    request_application_fix,
)


class GuardianAdminForm(forms.ModelForm):
    email = forms.EmailField(label="E-pasts (pieslēgšanās)", required=True)
    phone = forms.CharField(label="Tālrunis", max_length=20, required=False)
    is_active = forms.BooleanField(label="Konts aktīvs", required=False)

    class Meta:
        model = Guardian
        fields = ("full_name", "personal_id", "address")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        account = getattr(self.instance, "parent_account", None)
        if account is not None:
            self.fields["email"].initial = account.email
            self.fields["phone"].initial = account.phone
            self.fields["is_active"].initial = account.is_active

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        account = getattr(self.instance, "parent_account", None)
        clash = ParentAccount.objects.filter(email__iexact=email)
        if account is not None:
            clash = clash.exclude(pk=account.pk)
        if clash.exists():
            raise forms.ValidationError("E-pasts jau pieder citam kontam.")
        return email


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    form = GuardianAdminForm
    list_display = (
        "full_name",
        "email",
        "phone",
        "next_family_action",
        "family_hub_link",
    )
    search_fields = ("full_name", "parent_account__email", "personal_id")
    readonly_fields = ("related_records",)
    fields = ("related_records", "full_name", "personal_id", "address",
              "email", "phone", "is_active")

    class Media:
        css = {"all": ["admin/fk_badges.css", "admin/family_hub.css"]}

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Prefetch relations so next_family_action and related_records do not
        # issue per-guardian queries on the changelist.
        qs = qs.prefetch_related(
            "applications",
            "members__training_group",
            "members__billing_records",
            "members__agreements",
        )
        # Action-needed families first; the rest fall back to name + pk.
        needs_review_app = RegistrationApplication.objects.filter(
            guardian=OuterRef("pk"),
            status__in=(
                RegistrationApplication.Status.SUBMITTED,
                RegistrationApplication.Status.FIX_REQUESTED,
            ),
        )
        needs_review_agreement = Agreement.objects.filter(
            member__guardian=OuterRef("pk"),
            is_current=True,
        ).filter(
            Q(state__in=(Agreement.State.GENERATED, Agreement.State.SENT))
            | Q(external_state="failed")
            | (~Q(external_error_code="") & Q(external_error_code__isnull=False))
        )
        needs_review_billing = BillingRecord.objects.filter(
            member__guardian=OuterRef("pk"),
        ).filter(
            Q(status=BillingRecord.Status.DRAFT)
            | Q(
                status=BillingRecord.Status.CONFIRMED,
                external_status__in=("", "failed"),
            )
            | (~Q(external_error_code="") & Q(external_error_code__isnull=False))
        )
        action_priority = Case(
            When(Exists(needs_review_app), then=Value(3)),
            When(Exists(needs_review_agreement), then=Value(2)),
            When(Exists(needs_review_billing), then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
        return qs.annotate(action_priority=action_priority).order_by(
            "-action_priority", "full_name", "pk"
        )

    def get_urls(self):
        custom = [
            path(
                "family-hub/",
                self.admin_site.admin_view(self.family_queue_view),
                name="members_guardian_family_queue",
            ),
            path(
                "<int:guardian_id>/family-hub/",
                self.admin_site.admin_view(self.family_hub_view),
                name="members_guardian_family_hub",
            ),
            path(
                "<int:guardian_id>/family-hub/action/",
                self.admin_site.admin_view(self.family_hub_action_view),
                name="members_guardian_family_hub_action",
            ),
            path(
                "<int:guardian_id>/family-hub/agreement/<int:agreement_id>/docuseal-document/",
                self.admin_site.admin_view(self.family_hub_docuseal_document_view),
                name="members_guardian_docuseal_document",
            ),
        ]
        return custom + super().get_urls()

    @admin.display(description="Nākamā darbība")
    def next_family_action(self, obj):
        """Next action the staff user must take for this family.

        Reuses the same lane logic as the family hub / queue. Returns a link
        to the family hub when an action is needed, "—" otherwise. Reads
        prefetched relations populated by ``get_queryset`` — no per-row
        queries.
        """
        if obj.pk is None:
            return "—"
        row = _row_for_guardian(obj)
        next_action = row["next_action"] if row is not None else "—"
        if not next_action or next_action == "—":
            return "—"
        url = reverse("admin:members_guardian_family_hub", args=[obj.pk])
        return format_html(
            '<a href="{}">{}</a>', url, next_action
        )  # type: ignore[return-value,no-any-return]

    @admin.display(description="Ģimenes centrs")
    def family_hub_link(self, obj):
        if obj.pk is None:
            return "—"
        url = reverse("admin:members_guardian_family_hub", args=[obj.pk])
        return format_html(
            '<a href="{}">Atvērt centru →</a>', url
        )  # type: ignore[return-value,no-any-return]

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        members = list(obj.members.prefetch_related("billing_records")) if obj.pk else []
        applications = list(obj.applications.all()) if obj.pk else []
        billing_records = [br for m in members for br in m.billing_records.all()]
        return format_html(
            "<strong>Biedri:</strong> {}<br>"
            "<strong>Pieteikumi:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_links(members),
            admin_links(applications),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        account = obj.parent_account
        new_phone = form.cleaned_data.get("phone", "")
        new_active = form.cleaned_data.get("is_active", False)
        if account.phone != new_phone or account.is_active != new_active:
            account.phone = new_phone
            account.is_active = new_active
            account.save(update_fields=["phone", "is_active", "updated_at"])
        new_email = form.cleaned_data.get("email", "")
        if new_email and new_email != account.email.lower():
            change_parent_email(account, new_email)

    # ------------------------------------------------------------------
    # Family hub views
    # ------------------------------------------------------------------

    def family_queue_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        context = {
            **self.admin_site.each_context(request),
            "title": "Ģimenes darbību centrs",
            "rows": build_family_queue_rows(),
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/members/guardian/family_queue.html", context
        )

    def family_hub_view(self, request, guardian_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        guardian = get_object_or_404(
            Guardian.objects.select_related("parent_account"), pk=guardian_id
        )
        context = {
            **self.admin_site.each_context(request),
            "title": f"Ģimenes centrs — {guardian.full_name or guardian.pk}",
            "guardian": guardian,
            "action_url": reverse(
                "admin:members_guardian_family_hub_action", args=[guardian.pk]
            ),
            "hub": build_family_hub_context(guardian),
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/members/guardian/family_hub.html", context
        )

    def family_hub_docuseal_document_view(self, request, guardian_id, agreement_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        guardian = get_object_or_404(
            Guardian.objects.select_related("parent_account"), pk=guardian_id
        )
        agreement = self._get_guardian_agreement(guardian, agreement_id)
        if not agreement.external_id:
            self.message_user(
                request,
                "DocuSeal sūtījums vēl nav izveidots.",
                level=messages.ERROR,
            )
            return self._family_hub_redirect(guardian.pk)
        try:
            docs = agreement_platform.list_submission_documents(agreement.external_id)
        except agreement_platform.AgreementPlatformError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return self._family_hub_redirect(guardian.pk)
        selected = next(
            (d for d in docs if d.content_type == "application/pdf"),
            docs[0] if docs else None,
        )
        if selected is None:
            self.message_user(
                request,
                "DocuSeal dokuments nav atrasts.",
                level=messages.ERROR,
            )
            return self._family_hub_redirect(guardian.pk)
        return HttpResponseRedirect(selected.url)

    def family_hub_action_view(self, request, guardian_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if request.method != "POST":
            return self._family_hub_redirect(guardian_id)
        guardian = get_object_or_404(
            Guardian.objects.select_related("parent_account"), pk=guardian_id
        )
        action = request.POST.get("action", "").strip()
        handler = getattr(self, f"_family_hub_handle_{action}", None)
        if handler is None:
            self.message_user(
                request, f"Nezināma darbība: {action or '—'}.",
                level=messages.ERROR,
            )
            return self._family_hub_redirect(guardian.pk)
        try:
            handler(request, guardian)
        except PermissionDenied:
            raise
        except Http404:
            raise
        except Exception as exc:  # surface unexpected as admin error message
            self.message_user(request, str(exc), level=messages.ERROR)
        return self._family_hub_redirect(guardian.pk)

    def _family_hub_redirect(self, guardian_id):
        return redirect("admin:members_guardian_family_hub", guardian_id)

    def _get_guardian_application(self, guardian, application_id):
        return get_object_or_404(
            RegistrationApplication.objects.select_related("guardian"),
            pk=application_id,
            guardian=guardian,
        )

    def _get_guardian_agreement(self, guardian, agreement_id):
        from apps.agreements.models import Agreement

        return get_object_or_404(
            Agreement.objects.select_related("member__guardian"),
            pk=agreement_id,
            member__guardian=guardian,
        )

    def _get_guardian_member(self, guardian, member_id):
        return get_object_or_404(Member, pk=member_id, guardian=guardian)

    def _get_guardian_billing_record(self, guardian, billing_record_id):
        return get_object_or_404(
            BillingRecord.objects.select_related("member__guardian"),
            pk=billing_record_id,
            member__guardian=guardian,
        )

    def _resolve_training_group(self, request, raw):
        if not raw:
            return None
        try:
            return TrainingGroup.objects.get(pk=int(raw))
        except (TrainingGroup.DoesNotExist, ValueError, TypeError):
            self.message_user(
                request, "Nezināma treniņu grupa.", level=messages.ERROR
            )
            return None

    # ------------------------------------------------------------------
    # Action handlers (one per `action` value)
    # ------------------------------------------------------------------

    def _family_hub_handle_approve_application(self, request, guardian):
        application = self._get_guardian_application(
            guardian, request.POST.get("application_id", "")
        )
        selected_group = self._resolve_training_group(
            request, request.POST.get("training_group", "")
        )
        try:
            approve_application(
                application, request.user, training_group=selected_group
            )
        except ValueError as exc:
            raw = str(exc)
            if "inactive" in raw:
                latvian = "Nevar piešķirt neaktīvu treniņu grupu apstiprināšanas brīdī."
            elif "submitted" in raw:
                latvian = "Var apstiprināt tikai iesniegtus pieteikumus."
            else:
                latvian = raw
            self.message_user(request, latvian, level=messages.ERROR)
            return
        self.message_user(request, "Pieteikums apstiprināts.")

    def _family_hub_handle_request_fix(self, request, guardian):
        application = self._get_guardian_application(
            guardian, request.POST.get("application_id", "")
        )
        message = request.POST.get("review_message", "").strip()
        try:
            request_application_fix(application, request.user, message)
        except ValueError:
            self.message_user(
                request, "Labojuma ziņojums ir obligāts.", level=messages.ERROR
            )
            return
        self.message_user(request, "Pieprasīts labojums.")

    def _family_hub_handle_reject(self, request, guardian):
        application = self._get_guardian_application(
            guardian, request.POST.get("application_id", "")
        )
        message = request.POST.get("review_message", "").strip()
        try:
            reject_application(application, request.user, message)
        except ValueError:
            self.message_user(
                request, "Noraidīšanas ziņojums ir obligāts.", level=messages.ERROR
            )
            return
        self.message_user(request, "Pieteikums noraidīts.")

    def _family_hub_handle_mark_agreement_sent(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        try:
            mark_agreement_sent(agreement, request.user)
        except ValueError as exc:
            raw = str(exc)
            if "cannot mark sent from state" in raw:
                latvian = "Līgumu nevar atzīmēt kā nosūtītu šajā stāvoklī."
            else:
                latvian = raw
            self.message_user(request, latvian, level=messages.ERROR)
            return
        self.message_user(request, "Līgums atzīmēts kā nosūtīts.")

    def _family_hub_handle_mark_agreement_signed(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        try:
            mark_agreement_signed(agreement, request.user)
        except ValueError as exc:
            raw = str(exc)
            if raw == "billing plan required":
                latvian = "Pirms parakstīšanas jāizvēlas norēķinu plāns."
            else:
                latvian = raw
            self.message_user(request, latvian, level=messages.ERROR)
            return
        self.message_user(request, "Līgums atzīmēts kā parakstīts.")

    def _family_hub_handle_set_billing_setup(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        raw_plan = request.POST.get("billing_plan", "").strip()
        if not raw_plan:
            self.message_user(
                request, "Lūdzu izvēlieties norēķinu plānu.", level=messages.ERROR
            )
            return
        try:
            plan = MembershipPlan.objects.filter(
                pk=int(raw_plan), is_active=True
            ).first()
        except (ValueError, TypeError):
            plan = None
        if plan is None:
            self.message_user(
                request, "Nezināms norēķinu plāns.", level=messages.ERROR
            )
            return
        first_billing_month = request.POST.get("first_billing_month", "").strip()
        try:
            set_billing_setup(
                agreement,
                plan,
                first_billing_month=first_billing_month,
                actor=request.user,
            )
        except ValueError as exc:
            raw = str(exc)
            if "first billing month" in raw:
                latvian = "Pirmajam mēnesim jābūt formātā GGGG-MM."
            else:
                latvian = raw
            self.message_user(request, latvian, level=messages.ERROR)
            return
        self.message_user(request, "Norēķinu plāns saglabāts.")

    def _family_hub_handle_retry_docuseal(self, request, guardian):

        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        if agreement.external_state != "failed":
            self.message_user(
                request,
                "Atkārtot var tikai neizdevušos sūtījumu.",
                level=messages.ERROR,
            )
            return
        enqueue_create_agreement_submission(agreement.id)
        self.message_user(request, "DocuSeal izsūtīšana ielikta rindā.")

    def _family_hub_handle_sync_docuseal(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        enqueue_sync_agreement_submission(agreement.id)
        self.message_user(request, "DocuSeal statusa pārbaude ielikta rindā.")

    def _family_hub_handle_void_agreement(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        reason = request.POST.get("void_reason", "").strip()
        void_agreement(agreement, request.user, reason)
        self.message_user(request, "Līgums atcelts.")

    def _family_hub_handle_regenerate_agreement(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        try:
            regenerate_agreement(
                agreement.member,
                signing_path=agreement.signing_path,
                actor=request.user,
            )
        except ValueError as exc:
            raw = str(exc)
            if "active agreement cannot be replaced" in raw:
                latvian = "Aktīvo līgumu nedrīkst aizvietot."
            else:
                latvian = raw
            self.message_user(request, latvian, level=messages.ERROR)
            return
        self.message_user(request, "Līgums sagatavots no jauna.")

    def _family_hub_handle_minor_amendment(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        note = request.POST.get("note", "").strip()
        try:
            record_minor_amendment(agreement, request.user, note)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, "Neliels labojums pievienots.")

    def _family_hub_handle_material_amendment(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        note = request.POST.get("note", "").strip()
        try:
            start_material_amendment(agreement, request.user, note)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, "Sākta būtisku izmaiņu procedūra.")

    def _family_hub_handle_discontinue_member(self, request, guardian):
        agreement = self._get_guardian_agreement(
            guardian, request.POST.get("agreement_id", "")
        )
        effective_date_raw = request.POST.get("effective_date", "").strip()
        reason = request.POST.get("reason", "").strip()
        selected_invoices = request.POST.getlist("selected_invoices")
        if not effective_date_raw or not reason:
            self.message_user(
                request,
                "Norādiet spēkā stāšanās datumu un iemeslu.",
                level=messages.ERROR,
            )
            return
        try:
            effective_date = datetime.date.fromisoformat(effective_date_raw)
        except ValueError:
            self.message_user(
                request,
                "Nederīgs spēkā stāšanās datums.",
                level=messages.ERROR,
            )
            return
        try:
            from apps.agreements.services import discontinue_agreement

            discontinue_agreement(
                agreement,
                request.user,
                effective_date=effective_date,
                reason=reason,
                selected_invoice_ids=[int(i) for i in selected_invoices if i],
            )
        except PaidInvoiceSelected:
            self.message_user(
                request,
                "Atlasīts apmaksāts rēķins. Pirms turpināt, atmaksājiet to Invoice Ninja.",
                level=messages.ERROR,
            )
            return
        except DiscontinuationInvoiceError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, "Dalība pārtraukta.")

    def _family_hub_handle_confirm_billing(self, request, guardian):
        record = self._get_guardian_billing_record(
            guardian, request.POST.get("billing_record_id", "")
        )
        if record.status == BillingRecord.Status.DRAFT:
            record.status = BillingRecord.Status.CONFIRMED
            record.save(update_fields=["status", "updated_at"])
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
                actor=request.user, request=request, target=record,
            )
            self.message_user(request, "Norēķinu ieraksts apstiprināts.")
        else:
            self.message_user(
                request, "Ieraksts jau ir apstiprināts.", level=messages.INFO
            )

    def _family_hub_handle_push_billing(self, request, guardian):
        record = self._get_guardian_billing_record(
            guardian, request.POST.get("billing_record_id", "")
        )
        if record.status != BillingRecord.Status.CONFIRMED:
            self.message_user(
                request,
                "Vispirms apstipriniet ierakstu.",
                level=messages.ERROR,
            )
            return
        enqueue_push_billing_record(record.pk)
        self.message_user(request, "Rēķinu izsūtīšana ielikta rindā.")

    def _family_hub_handle_sync_billing_payments(self, request, guardian):
        record = self._get_guardian_billing_record(
            guardian, request.POST.get("billing_record_id", "")
        )
        enqueue_sync_billing_record_payments(record.pk)
        self.message_user(request, "Maksājumu pārbaude ielikta rindā.")


@admin.register(TrainingGroup)
class TrainingGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    actions = ["merge_training_groups"]

    @admin.action(description="Apvienot atlasītās grupas")
    def merge_training_groups(self, request, queryset):
        # Destructive (deletes groups) — gate on delete permission, not just change.
        if not self.has_delete_permission(request):
            self.message_user(
                request, "Nav tiesību dzēst grupas.", level=messages.ERROR
            )
            return None
        groups = list(queryset.order_by("name"))
        if len(groups) < 2:
            self.message_user(
                request,
                "Apvienošanai atlasiet vismaz divas grupas.",
                level=messages.WARNING,
            )
            return None
        if request.POST.get("apply") == "1":
            # The target must be one of the selected groups (the POST param is
            # otherwise attacker-controlled and could reparent to an arbitrary group).
            group_ids = {str(g.pk) for g in groups}
            if request.POST.get("target") not in group_ids:
                self.message_user(
                    request, "Atlasiet derīgu mērķa grupu.", level=messages.ERROR
                )
                return None
            target = get_object_or_404(TrainingGroup, pk=request.POST.get("target"))
            others = [g for g in groups if g.pk != target.pk]
            other_count = len(others)
            merged_ids = [g.pk for g in others]
            merged_names = [g.name for g in others]
            with transaction.atomic():
                reparented = Member.objects.filter(
                    training_group__in=others
                ).update(training_group=target)
                TrainingGroup.objects.filter(pk__in=merged_ids).delete()
            record_audit_event(
                action=str(AuditEvent.Action.TRAINING_GROUPS_MERGED),
                actor=request.user, request=request, target=target,
                metadata={
                    "merged_group_ids": merged_ids,
                    "merged_names": merged_names,
                    "members_reparented": reparented,
                },
            )
            self.message_user(
                request,
                f"Apvienotas {other_count} grupas grupā “{target.name}”; "
                f"pārvietoti {reparented} biedri.",
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": "Apvienot treniņu grupas",
            "groups": groups,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/members/traininggroup/merge_confirm.html", context
        )


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ("full_name", "guardian", "birth_date", "training_group")
    list_filter = ("training_group",)
    search_fields = ("full_name", "personal_id")
    actions = ["export_csv", "export_csv_with_sensitive", "renew_billing"]
    readonly_fields = ("related_records",)

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        source_application = getattr(obj, "source_application", None)
        agreement = get_current_agreement(obj) if obj.pk else None
        billing_records = list(obj.billing_records.order_by("-created_at")) if obj.pk else []
        return format_html(
            "<strong>Vecāks:</strong> {}<br>"
            "<strong>Pieteikums:</strong> {}<br>"
            "<strong>Līgums:</strong> {}<br>"
            "<strong>Rēķini:</strong> {}",
            admin_link(obj.guardian),
            admin_link(source_application),
            admin_link(agreement),
            admin_links(billing_records),
        )  # type: ignore[return-value,no-any-return]

    def _export_members(self, request, queryset, *, sensitive: bool):
        qs = queryset.select_related("guardian__parent_account", "training_group")
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

    @admin.action(description="Atjaunot norēķinus atlasītajiem biedriem")
    def renew_billing(self, request, queryset):
        """Two-step renewal: first POST shows a confirmation page (plan + first
        billing month picker); the second POST (``apply=1``) creates missing
        draft BillingRecord rows through the service, skipping discontinued
        members and any member that already has a record for the plan's season.

        Auditing is delegated to the service; this action only reports counts.
        """
        members = list(queryset.select_related("guardian", "source_application"))
        if request.POST.get("apply") == "1":
            raw_plan = request.POST.get("billing_plan", "").strip()
            plan = None
            if raw_plan:
                plan = MembershipPlan.objects.filter(
                    pk=raw_plan, is_active=True
                ).first()
            if plan is None:
                self.message_user(
                    request, "Nezināms norēķinu plāns.", level=messages.ERROR
                )
                return None
            first_billing_month = request.POST.get("first_billing_month", "").strip()
            try:
                if first_billing_month:
                    parse_first_billing_month(first_billing_month)
            except ValueError:
                self.message_user(
                    request,
                    "Pirmajam mēnesim jābūt formātā GGGG-MM.",
                    level=messages.ERROR,
                )
                return None
            created = skipped_existing = skipped_discontinued = 0
            for member in members:
                if member.status == Member.Status.DISCONTINUED:
                    skipped_discontinued += 1
                    continue
                if BillingRecord.objects.filter(
                    member=member, season=plan.season
                ).exists():
                    skipped_existing += 1
                    continue
                if (
                    renew_member_billing(
                        member,
                        plan,
                        first_billing_month=first_billing_month,
                        actor=request.user,
                    )
                    is not None
                ):
                    created += 1
            self.message_user(
                request,
                (
                    f"Izveidoti {created} norēķinu ieraksti. "
                    f"Esoši: {skipped_existing}. "
                    f"Pārtraukti: {skipped_discontinued}."
                ),
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": "Atjaunot norēķinus",
            "members": members,
            "plans": MembershipPlan.objects.filter(is_active=True).order_by(
                "season", "name"
            ),
            "opts": self.model._meta,
            "action_name": "renew_billing",
        }
        return TemplateResponse(
            request, "admin/members/member/renew_billing_confirm.html", context
        )


@admin.register(KitSizeOption)
class KitSizeOptionAdmin(admin.ModelAdmin):
    list_display = ("kind", "label", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("label",)

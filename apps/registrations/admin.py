"""Django admin for registrations app."""

import datetime
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import url_has_allowed_host_and_scheme

from apps.agreements.document_proxy import build_agreement_document_response
from apps.agreements.models import Agreement
from apps.agreements.signed_artifact_proxy import build_signed_artifact_response
from apps.integrations import agreement_platform
from apps.agreements.services import (
    discontinue_agreement,
    get_current_agreement,
    mark_agreement_sent,
    mark_agreement_signed,
    record_minor_amendment,
    regenerate_agreement,
    set_billing_setup,
    set_signing_path,
    start_material_amendment,
    sync_application_signing_path_to_agreement,
    upload_signed_artifact,
    void_agreement,
)
from apps.billing.models import MembershipPlan
from apps.billing.services import DiscontinuationInvoiceError, PaidInvoiceSelected
from apps.core.admin_links import admin_link
from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.integrations.tasks import (
    enqueue_create_agreement_submission,
    enqueue_sync_agreement_submission,
)
from apps.members.models import TrainingGroup
from apps.members.services import assign_training_group
from apps.registrations.exports import application_columns, application_row
from apps.registrations.models import (
    RegistrationApplication,
    RegistrationSubmissionDigestSettings,
)
from apps.registrations.services import (
    approve_application,
    reject_application,
    request_application_fix,
)


@admin.register(RegistrationApplication)
class RegistrationApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "member_full_name",
        "guardian_contact_email",
        "status",
        "submitted_at",
        "member_link",
        "agreement_status",
        "quick_actions",
    )
    list_filter = ("status", "preferred_agreement_signing")
    date_hierarchy = "submitted_at"
    ordering = ("-submitted_at",)
    search_fields = (
        "member_full_name",
        "parent_account__email",
        "guardian__first_name",
        "guardian__family_name",
    )
    readonly_fields = (
        "status",
        "submitted_at",
        "review_message",
        "reviewed_by",
        "reviewed_at",
        "approved_member",
        # Consent stamps are gate-controlled (P4 Slice C). Never editable in admin.
        "personal_data_consent_at",
        "personal_data_consent_version",
        "created_at",
        "updated_at",
    )

    actions = ["export_csv", "export_csv_with_sensitive"]

    change_form_template = "admin/registrations/registrationapplication/change_form.html"

    class Media:
        css = {"all": ["admin/css/review.css"]}
        js = ["admin/js/doc_lightbox.js"]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        from django.contrib.admin.utils import unquote

        from apps.registrations.admin_panels import build_review_context

        extra_context = extra_context or {}
        app = self.get_object(request, unquote(object_id))
        if app is not None:
            extra_context.update(build_review_context(app))
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        from django.urls import path

        custom = [
            path(
                "<int:object_id>/review-action/",
                self.admin_site.admin_view(self.review_action_view),
                name="registrations_registrationapplication_review-action",
            ),
            path(
                "<int:object_id>/approve/",
                self.admin_site.admin_view(self.approve_view),
                name="registrations_registrationapplication_approve",
            ),
            path(
                "<int:object_id>/agreement/<int:agreement_id>/docuseal-document/",
                self.admin_site.admin_view(self.docuseal_document_view),
                name="registrations_registrationapplication_docuseal_document",
            ),
            path(
                "<int:object_id>/agreement/<int:agreement_id>/signed-artifact/upload/",
                self.admin_site.admin_view(self.signed_artifact_upload_view),
                name="registrations_registrationapplication_signed_artifact_upload",
            ),
            path(
                "<int:object_id>/agreement/<int:agreement_id>/signed-artifact/",
                self.admin_site.admin_view(self.signed_artifact_view),
                name="registrations_registrationapplication_signed_artifact",
            ),
        ]
        return custom + super().get_urls()

    def _change_redirect(self, object_id):
        return redirect(
            "admin:registrations_registrationapplication_change", object_id
        )

    def _changelist_redirect(self):
        return redirect("admin:registrations_registrationapplication_changelist")

    def _after_review_redirect(self, request, object_id):
        """Honor a validated `next` (set by the changelist quick-action buttons so
        a list-triggered action returns to the list), else the change page."""
        nxt = request.GET.get("next") or request.POST.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(
            nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(nxt)
        return self._change_redirect(object_id)

    def docuseal_document_view(self, request, object_id, agreement_id):
        """Stream the generated agreement PDF through the shared proxy.

        Authorization chain: ``has_change_permission`` on the application,
        then ownership of the agreement is enforced by the
        ``member_id=application.approved_member_id`` filter — a request for
        a foreign agreement is a deterministic 404. Default disposition is
        ``attachment`` (matches the family-hub link contract); ``inline`` is
        supported for iframe embeds; anything else is a 404.

        Latvian admin messages cover two error paths:

        * blank ``external_id`` — submission still pending;
        * ``AgreementPlatformError`` — provider failure surfaced as a
          fixed Latvian copy (never the raw provider exception text).

        Both paths redirect to the application's change page (the staff
        surface where the agreement actions already live).
        """
        if not self.has_change_permission(request):
            raise PermissionDenied
        application = get_object_or_404(RegistrationApplication, pk=object_id)
        # Ownership guard: the agreement must belong to the application's
        # approved member, otherwise a cross-application guess of the
        # agreement pk is a deterministic 404.
        agreement = get_object_or_404(
            Agreement,
            pk=agreement_id,
            member_id=application.approved_member_id,
        )
        disposition = request.GET.get("disposition", "attachment")
        if disposition not in {"inline", "attachment"}:
            raise Http404
        if not agreement.external_id:
            self.message_user(
                request,
                "DocuSeal sūtījums vēl nav izveidots.",
                level=messages.ERROR,
            )
            return self._change_redirect(object_id)
        try:
            return build_agreement_document_response(
                agreement, disposition=disposition
            )
        except Http404:
            raise
        except agreement_platform.AgreementPlatformError:
            self.message_user(
                request,
                "Radās kļūda saziņā ar DocuSeal.",
                level=messages.ERROR,
            )
            return self._change_redirect(object_id)

    def signed_artifact_upload_view(self, request, object_id, agreement_id):
        """Sole upload surface for a signed PDF/.edoc artifact (P16-A).

        Authorization chain: ``has_change_permission`` on the application,
        then the agreement must belong to the application's approved member
        (foreign -> deterministic 404). POST-only; non-POST redirects to the
        change page. Service ``ValueError`` maps to a Latvian admin message;
        success shows a Latvian confirmation and redirects to the change page.
        """
        if not self.has_change_permission(request):
            raise PermissionDenied
        application = get_object_or_404(RegistrationApplication, pk=object_id)
        if request.method != "POST":
            return self._change_redirect(object_id)
        agreement = get_object_or_404(
            Agreement,
            pk=agreement_id,
            member_id=application.approved_member_id,
        )
        file_upload = request.FILES.get("signed_artifact")
        if file_upload is None:
            self.message_user(
                request,
                "Lūdzu izvēlieties parakstītā līguma failu.",
                level=messages.ERROR,
            )
            return self._change_redirect(object_id)
        try:
            upload_signed_artifact(agreement, file_upload, request.user)
        except ValueError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return self._change_redirect(object_id)
        self.message_user(request, "Parakstītais līgums augšupielādēts.")
        return self._change_redirect(object_id)

    def signed_artifact_view(self, request, object_id, agreement_id):
        """Stream a source-member signed artifact through the shared proxy.

        Same ownership chain as the upload view. Default disposition is
        ``attachment``; ``inline`` is allowed for staff PDF previews; any
        other value (or blank/missing artifact) is a 404.
        """
        if not self.has_change_permission(request):
            raise PermissionDenied
        application = get_object_or_404(RegistrationApplication, pk=object_id)
        agreement = get_object_or_404(
            Agreement,
            pk=agreement_id,
            member_id=application.approved_member_id,
        )
        disposition = request.GET.get("disposition", "attachment")
        if disposition not in {"inline", "attachment"}:
            raise Http404
        return build_signed_artifact_response(
            agreement, disposition=disposition
        )

    def review_action_view(self, request, object_id):
        """Port of admin_review_detail's POST dispatch (every action except approve)."""
        if not self.has_change_permission(request):
            raise PermissionDenied
        application = get_object_or_404(RegistrationApplication, pk=object_id)
        if request.method != "POST":
            return self._change_redirect(object_id)

        agreement = None
        if application.approved_member_id is not None:
            agreement = get_current_agreement(application.approved_member)

        # The disclosure forms POST `action` in the body; the changelist quick
        # actions ride the changelist form and pass `action` via the formaction
        # query string (the body's own `action` select is empty there).
        action = request.POST.get("action") or request.GET.get("action", "")

        if action == "request_fix":
            message = request.POST.get("review_message", "").strip()
            try:
                request_application_fix(application, request.user, message)
            except ValueError:
                self.message_user(
                    request, "Labojuma ziņojums ir obligāts.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

        elif action == "reject":
            message = request.POST.get("review_message", "").strip()
            try:
                reject_application(application, request.user, message)
            except ValueError:
                self.message_user(
                    request, "Noraidīšanas ziņojums ir obligāts.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            return self._changelist_redirect()

        elif action == "assign_training_group":
            if application.approved_member_id is None:
                self.message_user(
                    request,
                    "Var piešķirt grupu tikai apstiprinātam pieteikumam.",
                    level=messages.ERROR,
                )
                return self._change_redirect(object_id)
            raw_group = request.POST.get("training_group", "").strip()
            selected_group = None
            if raw_group:
                try:
                    selected_group = TrainingGroup.objects.get(pk=int(raw_group))
                except (TrainingGroup.DoesNotExist, ValueError):
                    self.message_user(
                        request, "Nezināma treniņu grupa.", level=messages.ERROR
                    )
                    return self._change_redirect(object_id)
            assign_training_group(
                application.approved_member, selected_group, request.user
            )
            return self._change_redirect(object_id)

        elif action == "mark_agreement_sent":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._after_review_redirect(request, object_id)
            try:
                mark_agreement_sent(agreement, request.user)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._after_review_redirect(request, object_id)
            return self._after_review_redirect(request, object_id)

        elif action == "mark_agreement_signed":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._after_review_redirect(request, object_id)
            try:
                mark_agreement_signed(agreement, request.user)
            except ValueError as exc:
                raw = str(exc)
                if raw == "billing plan required":
                    latvian = "Pirms parakstīšanas jāizvēlas norēķinu plāns."
                elif raw == "next year plan required":
                    latvian = "Nākamajam gadam izvēlieties aktīvu norēķinu plānu."
                elif raw == "first billing month required":
                    latvian = "Pirmais rēķina mēnesis ir obligāts."
                elif raw == "billing plan inactive":
                    latvian = "Izvēlētais norēķinu plāns nav aktīvs."
                else:
                    latvian = raw
                self.message_user(request, latvian, level=messages.ERROR)
                return self._after_review_redirect(request, object_id)
            return self._after_review_redirect(request, object_id)

        elif action == "set_billing_setup":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._after_review_redirect(request, object_id)
            raw_plan = request.POST.get("billing_plan", "").strip()
            if not raw_plan:
                self.message_user(
                    request, "Lūdzu izvēlieties norēķinu plānu.", level=messages.ERROR
                )
                return self._after_review_redirect(request, object_id)
            first_billing_month = request.POST.get("first_billing_month", "").strip()
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
                return self._after_review_redirect(request, object_id)
            try:
                set_billing_setup(
                    agreement,
                    plan,
                    first_billing_month=first_billing_month,
                    actor=request.user,
                )
            except ValueError as exc:
                raw = str(exc)
                if raw == "next year plan required":
                    latvian = "Nākamajam gadam izvēlieties aktīvu norēķinu plānu."
                elif raw == "first billing month required":
                    latvian = "Pirmais rēķina mēnesis ir obligāts."
                elif raw == "billing plan inactive":
                    latvian = "Izvēlētais norēķinu plāns nav aktīvs."
                elif "first billing month must use YYYY-MM" in raw:
                    latvian = "Pirmajam mēnesim jābūt formātā GGGG-MM."
                elif "cannot be before cutoff-derived default" in raw:
                    latvian = (
                        "Izvēlētais mēnesis ir pirms pirmā pieejamā rēķina mēneša."
                    )
                else:
                    latvian = raw
                self.message_user(request, latvian, level=messages.ERROR)
                return self._after_review_redirect(request, object_id)
            return self._after_review_redirect(request, object_id)

        elif action == "set_signing_path":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            new_path = request.POST.get("signing_path", "").strip()
            if new_path not in {value for value, _label in Agreement.SigningPath.choices}:
                self.message_user(
                    request, "Nezināms parakstīšanas veids.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            set_signing_path(agreement, new_path, request.user)
            return self._change_redirect(object_id)

        elif action == "void_agreement":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            reason = request.POST.get("void_reason", "").strip()
            void_agreement(agreement, request.user, reason)
            return self._change_redirect(object_id)

        elif action == "regenerate_agreement":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            try:
                regenerate_agreement(
                    application.approved_member,
                    signing_path=agreement.signing_path,
                    actor=request.user,
                )
            except ValueError as exc:
                msg = str(exc)
                if "active agreement cannot be replaced" in msg:
                    latvian = "Aktīvo līgumu nedrīkst aizvietot."
                else:
                    latvian = msg
                self.message_user(request, latvian, level=messages.ERROR)
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

        elif action == "retry_docuseal":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            if agreement.external_state != "failed":
                self.message_user(
                    request,
                    "Atkārtot var tikai neizdevušos sūtījumu.",
                    level=messages.ERROR,
                )
                return self._change_redirect(object_id)
            enqueue_create_agreement_submission(
                agreement.id,
                send_email=(
                    agreement.signing_path == Agreement.SigningPath.ELECTRONIC
                ),
            )
            return self._change_redirect(object_id)

        elif action == "sync_docuseal":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            enqueue_sync_agreement_submission(agreement.id)
            return self._change_redirect(object_id)

        elif action == "minor_amendment":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            note = request.POST.get("note", "").strip()
            try:
                record_minor_amendment(agreement, request.user, note)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

        elif action == "material_amendment":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            note = request.POST.get("note", "").strip()
            try:
                start_material_amendment(agreement, request.user, note)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

        elif action == "discontinue_member":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            effective_date_raw = request.POST.get("effective_date", "").strip()
            reason = request.POST.get("reason", "").strip()
            selected_invoices = request.POST.getlist("selected_invoices")
            if not effective_date_raw or not reason:
                self.message_user(
                    request,
                    "Norādiet spēkā stāšanās datumu un iemeslu.",
                    level=messages.ERROR,
                )
                return self._change_redirect(object_id)
            try:
                effective_date = datetime.date.fromisoformat(effective_date_raw)
            except ValueError:
                self.message_user(
                    request,
                    "Nederīgs spēkā stāšanās datums.",
                    level=messages.ERROR,
                )
                return self._change_redirect(object_id)
            try:
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
                return self._change_redirect(object_id)
            except DiscontinuationInvoiceError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._change_redirect(object_id)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

        return self._change_redirect(object_id)

    def approve_view(self, request, object_id):
        """Confirm-then-commit approval (port of the views.py approve branch)."""
        if not self.has_change_permission(request):
            raise PermissionDenied
        application = get_object_or_404(RegistrationApplication, pk=object_id)

        if request.method != "POST":
            active_training_groups = list(
                TrainingGroup.objects.filter(is_active=True).order_by("name")
            )
            context = {
                "title": "Apstiprināt pieteikumu",
                "original": application,
                "active_training_groups": active_training_groups,
                "opts": self.model._meta,
                **self.admin_site.each_context(request),
            }
            return render(
                request,
                "admin/registrations/registrationapplication/approve_confirm.html",
                context,
            )

        raw_group = request.POST.get("training_group", "").strip()
        selected_group = None
        if raw_group:
            try:
                selected_group = TrainingGroup.objects.get(pk=int(raw_group))
            except (TrainingGroup.DoesNotExist, ValueError):
                self.message_user(
                    request, "Nezināma treniņu grupa.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
        try:
            approve_application(
                application, request.user, training_group=selected_group
            )
        except ValueError as exc:
            message = str(exc)
            if "inactive" in message:
                latvian = "Nevar piešķirt neaktīvu treniņu grupu apstiprināšanas brīdī."
            elif "submitted" in message:
                latvian = "Var apstiprināt tikai iesniegtus pieteikumus."
            else:
                latvian = "Pieteikumu nevarēja apstiprināt."
            self.message_user(request, latvian, level=messages.ERROR)
            return self._change_redirect(object_id)
        self.message_user(request, "Pieteikums apstiprināts.")
        return self._change_redirect(object_id)

    def get_queryset(self, request):
        # guardian_contact_email (list_display) traverses parent_account, and
        # guardian__first_name/family_name is searched — select_related avoids a changelist N+1.
        # approved_member is select_related so the quick_actions agreement lookup
        # doesn't re-fetch the member per row; the per-row get_current_agreement
        # query itself is acceptable for the modest review-queue size.
        return (
            super()
            .get_queryset(request)
            .select_related("guardian", "parent_account", "approved_member")
        )

    def _export_applications(self, request, queryset, *, sensitive: bool):
        # Self-sufficient: the guardian accessors traverse guardian + parent_account,
        # so apply select_related here (don't rely on the admin's get_queryset — the
        # method may be called with a bare queryset).
        queryset = queryset.select_related("guardian", "parent_account")
        rows = [application_row(a, sensitive=sensitive) for a in queryset]
        record_audit_event(
            action=str(AuditEvent.Action.DATA_EXPORTED),
            actor=request.user, request=request,
            target_type="registrationapplication",
            target_repr=f"registration export ({len(rows)} rows)",
            metadata={"count": len(rows), "sensitive": sensitive, "format": "csv"},
        )
        ts = timezone.localtime().strftime("%Y%m%d-%H%M")
        return csv_response(
            filename=f"registrations-{ts}.csv",
            columns=application_columns(sensitive=sensitive),
            rows=rows,
        )

    @admin.action(description="Eksportēt CSV (bez sensitīviem datiem)")
    def export_csv(self, request, queryset):
        return self._export_applications(request, queryset, sensitive=False)

    @admin.action(description="Eksportēt CSV ar sensitīviem datiem")
    def export_csv_with_sensitive(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, "Nepieciešamas superlietotāja tiesības.", level=messages.ERROR)
            return None
        return self._export_applications(request, queryset, sensitive=True)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("export_csv_with_sensitive", None)
        return actions

    @admin.display(description="Biedrs")
    def member_link(self, obj):
        # Fixed label (not the name) — the name is already in the member_full_name column.
        if obj.approved_member_id is None:
            return "—"
        return admin_link(obj.approved_member, label="Atvērt →")

    @admin.display(description="Līguma statuss")
    def agreement_status(self, obj):
        if obj.approved_member_id:
            agreement = get_current_agreement(obj.approved_member)
            if agreement is not None:
                return agreement.get_state_display()
        return "—"

    def quick_actions(self, obj) -> str:  # type: ignore[override]
        """Status-aware per-row quick actions on the changelist.

        The safe agreement transitions are real one-click POSTs to the
        review-action endpoint via bare ``formaction`` buttons that ride the
        changelist's own form + CSRF (the action rides the query string), plus
        an always-present open link.
        """
        if not obj.pk:
            return "-"
        change_url = reverse(
            "admin:registrations_registrationapplication_change", args=[obj.pk]
        )
        changelist_url = reverse(
            "admin:registrations_registrationapplication_changelist"
        )
        agreement_action = ""
        if obj.approved_member_id:
            agreement = get_current_agreement(obj.approved_member)
            label = action = ""
            if agreement and agreement.state == Agreement.State.GENERATED:
                label, action = "Atzīmēt nosūtītu", "mark_agreement_sent"
            elif agreement and agreement.state == Agreement.State.SENT:
                label, action = "Atzīmēt parakstītu", "mark_agreement_signed"
            if label:
                action_url = reverse(
                    "admin:registrations_registrationapplication_review-action",
                    args=[obj.pk],
                )
                formaction = (
                    f"{action_url}?{urlencode({'action': action, 'next': changelist_url})}"
                )
                # Bare button (no nested <form>, which the browser would drop): it
                # rides the changelist's own POST form + CSRF. `action` rides the
                # formaction query string to avoid colliding with the changelist's
                # own bulk-`action` <select>; `next` returns staff to the list.
                agreement_action = format_html(
                    '<button type="submit" class="button" formaction="{}" '
                    'formmethod="post">{} →</button> ',
                    formaction,
                    label,
                )
        return format_html(  # type: ignore[return-value,no-any-return]
            '{}<a href="{}">Atvērt →</a>', agreement_action, change_url
        )

    quick_actions.short_description = "Darbības"  # type: ignore[assignment,attr-defined]
    quick_actions.admin_order_field = "pk"  # type: ignore[assignment,attr-defined]

    def save_model(self, request, obj, form, change):
        """Persist the application, then sync preferred_agreement_signing to
        the active agreement when it is still in `generated` state."""
        super().save_model(request, obj, form, change)
        sync_application_signing_path_to_agreement(obj)


@admin.register(RegistrationSubmissionDigestSettings)
class RegistrationSubmissionDigestSettingsAdmin(admin.ModelAdmin):
    """Singleton digest settings — superuser-only, last success is readonly."""

    readonly_fields = ("last_successful_at",)
    filter_horizontal = ("recipients",)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        User = get_user_model()

        if db_field.name == "recipients":
            field = super().formfield_for_manytomany(db_field, request, **kwargs)
            field.queryset = User.objects.filter(is_active=True, is_staff=True)
            field.label_from_instance = lambda user: user.email
            return field
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

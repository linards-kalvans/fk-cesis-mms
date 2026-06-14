"""Django admin for registrations app."""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.agreements.models import Agreement
from apps.agreements.services import (
    get_current_agreement,
    mark_agreement_sent,
    mark_agreement_signed,
    regenerate_agreement,
    set_signing_path,
    sync_application_signing_path_to_agreement,
    void_agreement,
)
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
from apps.registrations.models import RegistrationApplication
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
        "review_link",
    )
    list_filter = ("status",)
    search_fields = ("member_full_name", "parent_account__email", "guardian__full_name")
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
        ]
        return custom + super().get_urls()

    def _change_redirect(self, object_id):
        return redirect(
            "admin:registrations_registrationapplication_change", object_id
        )

    def _changelist_redirect(self):
        return redirect("admin:registrations_registrationapplication_changelist")

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

        action = request.POST.get("action", "")

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
                return self._change_redirect(object_id)
            try:
                mark_agreement_sent(agreement, request.user)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

        elif action == "mark_agreement_signed":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            try:
                mark_agreement_signed(agreement, request.user)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
                return self._change_redirect(object_id)
            return self._change_redirect(object_id)

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
            enqueue_create_agreement_submission(agreement.id)
            return self._change_redirect(object_id)

        elif action == "sync_docuseal":
            if agreement is None:
                self.message_user(
                    request, "Līgums nav sagatavots.", level=messages.ERROR
                )
                return self._change_redirect(object_id)
            enqueue_sync_agreement_submission(agreement.id)
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
        return self._changelist_redirect()

    def get_queryset(self, request):
        # guardian_contact_email (list_display) traverses parent_account, and
        # guardian__full_name is searched — select_related avoids a changelist N+1.
        return super().get_queryset(request).select_related("guardian", "parent_account")

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

    def review_link(self, obj) -> str:  # type: ignore[override]
        """Link to the custom review detail page."""
        if obj.pk:
            url = reverse("registrations:admin-review-detail", args=[obj.pk])
            return format_html('<a href="{}">Review</a>', url)  # type: ignore[return-value,no-any-return]
        return "-"

    review_link.short_description = "Review"  # type: ignore[assignment,attr-defined]
    review_link.admin_order_field = "pk"  # type: ignore[assignment,attr-defined]

    def save_model(self, request, obj, form, change):
        """Persist the application, then sync preferred_agreement_signing to
        the active agreement when it is still in `generated` state."""
        super().save_model(request, obj, form, change)
        sync_application_signing_path_to_agreement(obj)

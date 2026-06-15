"""Django admin for members app."""

from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email
from apps.agreements.services import get_current_agreement
from apps.core.admin_links import admin_link, admin_links
from apps.core.audit import record_audit_event
from apps.core.export import csv_response
from apps.core.models import AuditEvent
from apps.members.exports import member_columns, member_row
from apps.members.models import Guardian, KitSizeOption, Member, TrainingGroup


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
    list_display = ("full_name", "email", "phone")
    search_fields = ("full_name", "parent_account__email", "personal_id")
    readonly_fields = ("related_records",)
    fields = ("related_records", "full_name", "personal_id", "address",
              "email", "phone", "is_active")

    def has_add_permission(self, request):
        return False

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
        if new_email and new_email != account.email:
            change_parent_email(account, new_email)


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
            with transaction.atomic():
                reparented = Member.objects.filter(
                    training_group__in=others
                ).update(training_group=target)
                TrainingGroup.objects.filter(
                    pk__in=[g.pk for g in others]
                ).delete()
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
    actions = ["export_csv", "export_csv_with_sensitive"]
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


@admin.register(KitSizeOption)
class KitSizeOptionAdmin(admin.ModelAdmin):
    list_display = ("kind", "label", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("label",)

"""Django admin for accounts app."""

from django.contrib import admin
from django.utils.html import format_html

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email
from apps.core.admin_links import admin_link, admin_links


@admin.register(ParentAccount)
class ParentAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "phone", "is_active", "last_login")
    search_fields = ("email", "phone")
    list_filter = ("is_active",)
    readonly_fields = ("related_records",)

    @admin.display(description="Saistītie ieraksti")
    def related_records(self, obj):
        guardian = getattr(obj, "guardian", None) if obj.pk else None
        applications = list(obj.applications.all()) if obj.pk else []
        members = list(guardian.members.all()) if guardian is not None else []
        agreements = [a for m in members for a in m.agreements.all()]
        return format_html(
            "<strong>Vecāks:</strong> {}<br>"
            "<strong>Pieteikumi:</strong> {}<br>"
            "<strong>Biedri:</strong> {}<br>"
            "<strong>Līgumi:</strong> {}",
            admin_link(guardian),
            admin_links(applications),
            admin_links(members),
            admin_links(agreements),
        )  # type: ignore[return-value,no-any-return]

    def save_model(self, request, obj, form, change):
        """Route verified-email changes through change_parent_email so the
        Guardian.email mirror stays in sync (single writer)."""
        if change and "email" in form.changed_data:
            new_email = obj.email
            # Save the non-email fields first under the original email, then let
            # the service perform the email change + mirror update atomically.
            obj.email = form.initial.get("email", obj.email)
            super().save_model(request, obj, form, change)
            change_parent_email(obj, new_email)
        else:
            super().save_model(request, obj, form, change)

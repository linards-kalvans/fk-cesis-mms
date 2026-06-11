"""Django admin for accounts app."""

from django.contrib import admin

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email


@admin.register(ParentAccount)
class ParentAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "phone", "is_active", "last_login")
    search_fields = ("email", "phone")
    list_filter = ("is_active",)

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

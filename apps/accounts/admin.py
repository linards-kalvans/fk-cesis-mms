"""Django admin for accounts app."""

from django.contrib import admin

from apps.accounts.models import ParentAccount


@admin.register(ParentAccount)
class ParentAccountAdmin(admin.ModelAdmin):
    list_display = ("email", "phone", "is_active", "last_login")
    search_fields = ("email", "phone")
    list_filter = ("is_active",)

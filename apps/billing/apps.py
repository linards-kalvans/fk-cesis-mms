"""Billing app config — MembershipPlan, sibling discount, Invoice Ninja sync."""

from django.apps import AppConfig


class BillingConfig(AppConfig):
    name = "apps.billing"
    default_auto_field = "django.db.models.BigAutoField"

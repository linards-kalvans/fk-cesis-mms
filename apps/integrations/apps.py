"""Integrations app config — Invoice Ninja / OCR clients, retry state."""

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = "apps.integrations"
    default_auto_field = "django.db.models.BigAutoField"

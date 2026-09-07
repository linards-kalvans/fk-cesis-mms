"""Staff-facing Admin Hub UI. Owns no models: it renders and delegates."""

from django.apps import AppConfig


class AdminHubConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.admin_hub"
    verbose_name = "Admin Hub"

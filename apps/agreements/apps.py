"""Agreements app config."""

from django.apps import AppConfig


class AgreementsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.agreements"
    label = "agreements"

    def ready(self):
        from apps.agreements import document_generation  # noqa: F401
        from apps.agreements import shadow  # noqa: F401

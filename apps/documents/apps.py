"""Documents app config — private Document model, audited access views."""

from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = "apps.documents"
    default_auto_field = "django.db.models.BigAutoField"

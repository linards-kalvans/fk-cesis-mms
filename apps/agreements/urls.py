"""URL routes for the agreements app."""

from django.urls import path

from apps.agreements import webhooks

app_name = "agreements"

urlpatterns = [
    path(
        "integrations/docuseal/webhook/",
        webhooks.docuseal_webhook,
        name="docuseal-webhook",
    ),
]

"""URL routes for the addresses app."""

from __future__ import annotations

from django.urls import path

from apps.addresses import views

app_name = "addresses"

urlpatterns = [
    path("autocomplete/", views.autocomplete, name="autocomplete"),
]

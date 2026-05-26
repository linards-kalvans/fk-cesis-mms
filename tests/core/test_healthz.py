"""Smoke tests for the /healthz liveness endpoint."""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_returns_ok_when_db_reachable() -> None:
    client = Client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_url_is_named_for_reverse_lookups() -> None:
    from django.urls import reverse

    assert reverse("healthz") == "/healthz"

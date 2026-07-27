"""Portal personalized greeting — the hero card greets the verified parent by
their canonical Guardian display_name (e.g. "Sveiks/-a, Jānis Bērziņš!"),
falling back to a plain greeting when no guardian name is on file yet."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_greets_returning_parent_by_guardian_display_name(
    verified_client, parent_account, make_guardian
):
    make_guardian(parent_account, first_name="Jānis", family_name="Bērziņš")
    resp = verified_client.get(reverse("registrations:parent-portal"))
    assert resp.status_code == 200
    assert "Sveiks/-a, Jānis Bērziņš!" in resp.content.decode()


def test_greets_returning_parent_by_full_name_shorthand(
    verified_client, parent_account, make_guardian
):
    """make_guardian(full_name=...) should still produce a greeting via display_name."""
    make_guardian(parent_account, full_name="Jānis Bērziņš")
    resp = verified_client.get(reverse("registrations:parent-portal"))
    assert resp.status_code == 200
    assert "Sveiks/-a, Jānis Bērziņš!" in resp.content.decode()


def test_falls_back_to_plain_greeting_without_guardian_name(
    verified_client, parent_account
):
    resp = verified_client.get(reverse("registrations:parent-portal"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Sveiks!" in html
    assert "Sveiks/-a," not in html

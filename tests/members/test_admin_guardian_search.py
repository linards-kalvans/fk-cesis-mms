"""P13 cleanup — GuardianAdmin search uses first_name / family_name (not full_name)."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from tests.support import make_guardian

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_guardian_search_by_account_email_does_not_error():
    make_guardian(full_name="Anna Ozola", email="findme@example.com")
    make_guardian(full_name="Cits", email="other@example.com")
    c = _staff_client()
    url = reverse("admin:members_guardian_changelist") + "?q=findme"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Anna Ozola" in body
    assert "Cits" not in body


def test_guardian_search_by_first_name():
    make_guardian(full_name="Anna Ozola", email="a@example.com")
    make_guardian(full_name="Cits", email="b@example.com")
    c = _staff_client()
    url = reverse("admin:members_guardian_changelist") + "?q=Anna"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Anna Ozola" in body
    assert "Cits" not in body


def test_guardian_search_by_family_name():
    make_guardian(full_name="Anna Ozola", email="a@example.com")
    make_guardian(full_name="Jānis Kalniņš", email="b@example.com")
    c = _staff_client()
    url = reverse("admin:members_guardian_changelist") + "?q=Ozola"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Anna Ozola" in body
    assert "Kalniņš" not in body

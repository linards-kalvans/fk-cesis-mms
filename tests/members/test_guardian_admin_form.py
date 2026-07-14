"""The Guardian change page edits the account's email/phone/is_active."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _guardian():
    acc = ParentAccount.objects.create(email="old@example.com", phone="+371", is_active=True)
    g = Guardian(first_name="Vecāks", family_name="", parent_account=acc)
    g.sync_full_name()
    g.save()
    return g


def test_change_page_shows_account_fields():
    g = _guardian()
    c = _staff_client()
    html = c.get(reverse("admin:members_guardian_change", args=[g.pk])).content.decode()
    assert "old@example.com" in html
    assert 'name="email"' in html
    assert 'name="phone"' in html
    assert 'name="is_active"' in html


def test_change_page_shows_first_name_and_family_name():
    g = _guardian()
    c = _staff_client()
    html = c.get(reverse("admin:members_guardian_change", args=[g.pk])).content.decode()
    assert 'name="first_name"' in html
    assert 'name="family_name"' in html


def test_save_writes_phone_and_is_active_to_account():
    g = _guardian()
    c = _staff_client()
    resp = c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "first_name": "Vecāks", "family_name": "", "personal_id": "", "address": "",
        "email": "old@example.com", "phone": "+37100099", "is_active": "",
    })
    assert resp.status_code == 302  # saved + redirected (no form errors)
    g.refresh_from_db()
    assert g.parent_account.phone == "+37100099"
    assert g.parent_account.is_active is False


def test_save_routes_email_change_through_service():
    g = _guardian()
    c = _staff_client()
    c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "first_name": "Vecāks", "family_name": "", "personal_id": "", "address": "",
        "email": "new@example.com", "phone": "+371", "is_active": "on",
    })
    g.refresh_from_db()
    assert g.parent_account.email == "new@example.com"


def test_duplicate_email_is_rejected():
    g = _guardian()
    ParentAccount.objects.create(email="taken@example.com")
    c = _staff_client()
    resp = c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "first_name": "Vecāks", "family_name": "", "personal_id": "", "address": "",
        "email": "taken@example.com", "phone": "+371", "is_active": "on",
    })
    g.refresh_from_db()
    assert g.parent_account.email == "old@example.com"  # unchanged
    assert resp.status_code == 200  # re-renders with an error


def test_save_writes_name_parts_and_full_name_mirror():
    g = _guardian()
    c = _staff_client()
    resp = c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "first_name": "Anna Marija", "family_name": "Ozola",
        "personal_id": "", "address": "",
        "email": "old@example.com", "phone": "+371", "is_active": "on",
    })
    assert resp.status_code == 302
    g.refresh_from_db()
    assert g.first_name == "Anna Marija"
    assert g.family_name == "Ozola"
    assert g.full_name == "Anna Marija Ozola"


def test_change_page_has_no_editable_full_name_input():
    g = _guardian()
    c = _staff_client()
    html = c.get(reverse("admin:members_guardian_change", args=[g.pk])).content.decode()
    assert 'name="full_name"' not in html
    assert g.full_name in html


def test_guardian_add_is_disabled():
    c = _staff_client()
    assert c.get(reverse("admin:members_guardian_add")).status_code == 403

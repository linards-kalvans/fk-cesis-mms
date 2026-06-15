"""Cross-links on the registrations admin (changelist column + change page block)."""

import re

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import Guardian, Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_links_to_approved_member():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert f"/members/member/{m.pk}/change/" in html


def test_changelist_member_column_dash_when_unapproved():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    resp = c.get(reverse("admin:registrations_registrationapplication_changelist"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Biedrs" in html  # column header present
    # no member *change* link for an unapproved app (the nav sidebar's
    # /admin/members/member/ changelist link has no pk, so match the change URL).
    assert not re.search(r"/members/member/\d+/change/", html)


def test_change_page_shows_related_records_block():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_change", args=[app.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html
    assert f"/members/guardian/{g.pk}/change/" in html

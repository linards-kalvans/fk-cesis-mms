"""Admin review-action endpoints port the staff flow into the admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _submitted():
    return RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )


def test_reject_action_transitions_and_redirects_to_changelist():
    app = _submitted()
    c = _staff_client()
    url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(url, {"action": "reject", "review_message": "trūkst dokumenta"})
    assert resp.status_code == 302
    assert reverse("admin:registrations_registrationapplication_changelist") in resp.url
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.REJECTED


def test_request_fix_requires_message_surfaces_error():
    app = _submitted()
    c = _staff_client()
    url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(url, {"action": "request_fix", "review_message": ""}, follow=True)
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.SUBMITTED  # unchanged
    assert b"oblig" in resp.content.lower()  # error message shown


def test_action_endpoint_is_staff_only():
    app = _submitted()
    c = Client()  # anonymous
    url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(url, {"action": "reject", "review_message": "x"})
    assert resp.status_code in (302, 403)
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.SUBMITTED


def test_approve_confirm_then_commit():
    app = _submitted()
    c = _staff_client()
    confirm_url = reverse("admin:registrations_registrationapplication_approve", args=[app.pk])
    assert c.get(confirm_url).status_code == 200  # confirm page (GET)
    resp = c.post(confirm_url, {})  # commit
    assert resp.status_code == 302
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.APPROVED

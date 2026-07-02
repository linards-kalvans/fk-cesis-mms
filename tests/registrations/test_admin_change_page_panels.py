"""Admin change page renders the review panels."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.registrations.models import RegistrationApplication

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_change_page_shows_review_panels():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    c = _staff_client()
    url = reverse("admin:registrations_registrationapplication_change", args=[app.pk])
    html = c.get(url).content.decode()
    assert "mms-review-panel" in html
    assert "review.css" in html
    assert "doc_lightbox.js" in html

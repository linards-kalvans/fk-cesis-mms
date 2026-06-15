"""Search/filter polish on registrations + training-group admins."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import TrainingGroup
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_applications_have_signing_path_filter_and_date_drill():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "preferred_agreement_signing" in html  # filter param in sidebar links
    assert c.get(
        reverse("admin:registrations_registrationapplication_changelist") + "?submitted_at__year=2026"
    ).status_code == 200


def test_training_group_is_searchable():
    TrainingGroup.objects.create(name="U10 A")
    TrainingGroup.objects.create(name="U12 B")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist") + "?q=U10"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "U10 A" in body
    assert "U12 B" not in body

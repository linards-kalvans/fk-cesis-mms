"""Applications changelist shows the agreement status."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member

from tests.support import make_guardian
from apps.registrations.models import RegistrationApplication

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_shows_agreement_state_for_approved_app():
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Līguma statuss" in html  # column header
    assert Agreement.State.SENT.label in html  # the concise state label


def test_changelist_dash_when_no_agreement():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Līguma statuss" in html
    assert "—" in html  # dash fallback for an application with no agreement

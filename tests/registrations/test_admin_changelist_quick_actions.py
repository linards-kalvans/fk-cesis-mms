"""Changelist shows status-aware quick actions."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Guardian, Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_renders_open_link_and_agreement_quick_action():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.GENERATED, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Atvērt" in html
    assert "Atzīmēt nosūtītu" in html  # generated -> mark-sent quick action


def test_changelist_open_link_without_agreement():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Atvērt" in html
    assert "Atzīmēt nosūtītu" not in html  # no agreement -> no agreement quick action

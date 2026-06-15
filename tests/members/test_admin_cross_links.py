"""Related-records cross-links on the members admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member

from tests.support import make_guardian
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_member_change_page_links_to_guardian_application_agreement():
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:members_member_change", args=[m.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/guardian/{g.pk}/change/" in html
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html
    assert f"/agreements/agreement/{agreement.pk}/change/" in html


def test_guardian_change_page_links_to_members_and_applications():
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns", guardian=g,
    )
    c = _staff_client()
    html = c.get(reverse("admin:members_guardian_change", args=[g.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html

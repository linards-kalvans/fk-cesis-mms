"""Related-records cross-links on the agreements admin."""

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


def test_agreement_change_page_links_to_member_and_application():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="Bērns",
        approved_member=m, guardian=g,
    )
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:agreements_agreement_change", args=[agreement.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html

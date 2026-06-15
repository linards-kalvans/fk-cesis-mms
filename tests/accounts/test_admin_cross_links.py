"""Related-records cross-links on the parent-account admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ParentAccount
from apps.agreements.models import Agreement
from apps.members.models import Guardian, Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_parent_account_change_page_links_to_related_records():
    pa = ParentAccount.objects.create(email="vecaks@example.com")
    g = Guardian.objects.create(full_name="Vecāks", parent_account=pa)
    m = Member.objects.create(full_name="Bērns", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        member_full_name="Bērns", parent_account=pa,
    )
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:accounts_parentaccount_change", args=[pa.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/guardian/{g.pk}/change/" in html             # guardian
    assert f"/registrations/registrationapplication/{app.pk}/change/" in html  # application
    assert f"/members/member/{m.pk}/change/" in html               # member (via guardian)
    assert f"/agreements/agreement/{agreement.pk}/change/" in html  # agreement (via member)


def test_parent_account_without_guardian_renders_gracefully():
    pa = ParentAccount.objects.create(email="tukšs@example.com")
    c = _staff_client()
    resp = c.get(reverse("admin:accounts_parentaccount_change", args=[pa.pk]))
    assert resp.status_code == 200
    assert "Saistītie ieraksti" in resp.content.decode()

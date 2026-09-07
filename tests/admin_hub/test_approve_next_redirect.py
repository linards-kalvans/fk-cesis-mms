"""approve_view must honour a validated `next`, like review_action_view does."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def approver(db):
    from django.contrib.auth.models import User

    user = User.objects.create_superuser(
        username="approver", email="a@example.lv", password="x"
    )
    return user


def test_approve_returns_to_a_safe_next(client, approver, submitted_application):
    client.force_login(approver)
    hub_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    response = client.post(f"{url}?next={hub_url}", {"training_group": ""})
    assert response.status_code == 302
    assert response["Location"] == hub_url


def test_approve_ignores_an_offsite_next(client, approver, submitted_application):
    client.force_login(approver)
    url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    response = client.post(f"{url}?next=https://evil.example.com/", {"training_group": ""})
    assert response.status_code == 302
    assert "evil.example.com" not in response["Location"]


def test_approve_without_next_still_lands_on_the_change_page(
    client, approver, submitted_application
):
    client.force_login(approver)
    url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    response = client.post(url, {"training_group": ""})
    assert response.status_code == 302
    assert str(submitted_application.pk) in response["Location"]

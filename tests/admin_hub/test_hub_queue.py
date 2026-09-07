"""Application queue page."""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def test_queue_requires_staff(client):
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_queue_rejects_a_signed_in_non_staff_user(client, django_user_model):
    django_user_model.objects.create_user(username="parent_ish", password="x")
    client.login(username="parent_ish", password="x")
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 302, "non-staff must not reach the hub"


def test_queue_lists_a_submitted_application(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"))
    assert response.status_code == 200
    body = response.content.decode()
    assert submitted_application.member_full_name in body
    assert "Pieteikumu rinda" in body


def test_queue_shows_pipeline_progress_and_next_action(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert "0/8" in body
    assert "Datu pārbaude" in body


def test_queue_default_tab_hides_drafts(client, reviewer, draft_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert draft_application.member_full_name not in body


def test_queue_all_tab_shows_drafts(client, reviewer, draft_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "visi"}).content.decode()
    assert draft_application.member_full_name in body


def test_queue_orders_newest_submission_first(client, reviewer, submitted_application):
    from django.utils import timezone
    from apps.registrations.models import RegistrationApplication

    older = RegistrationApplication.objects.create(
        claimed_email="older@example.lv",
        guardian=submitted_application.guardian,
        parent_account=submitted_application.parent_account,
        member_full_name="Older Child",
        status=RegistrationApplication.Status.SUBMITTED,
        submitted_at=timezone.now() - datetime.timedelta(days=10),
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert body.index(submitted_application.member_full_name) < body.index(
        older.member_full_name
    )


def test_queue_flags_an_application_waiting_over_three_days(
    client, reviewer, submitted_application
):
    from django.utils import timezone

    submitted_application.submitted_at = timezone.now() - datetime.timedelta(days=4)
    submitted_application.save(update_fields=["submitted_at"])
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert "qrow--aging" in body


def test_queue_unknown_tab_falls_back_to_default(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"), {"tab": "../etc/passwd"})
    assert response.status_code == 200
    assert submitted_application.member_full_name in response.content.decode()

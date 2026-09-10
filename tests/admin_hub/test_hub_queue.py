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
    assert "/admin/login/" in response["Location"]


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
    assert "0/7" in body
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


def test_queue_invalid_page_falls_back_to_page_one(client, reviewer, submitted_application):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:queue"), {"page": "not-a-number"})
    assert response.status_code == 200
    assert submitted_application.member_full_name in response.content.decode()


def test_queue_aging_flag_only_applies_to_old_submitted_rows(
    client, reviewer, submitted_application
):
    from django.utils import timezone
    from apps.registrations.models import RegistrationApplication

    RegistrationApplication.objects.create(
        claimed_email="old-fix@example.lv",
        guardian=submitted_application.guardian,
        parent_account=submitted_application.parent_account,
        member_full_name="Old Fix Child",
        status=RegistrationApplication.Status.FIX_REQUESTED,
        submitted_at=timezone.now() - datetime.timedelta(days=10),
    )
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "visi"}).content.decode()
    assert "qrow--aging" not in body


def test_queue_badge_reflects_non_submitted_status(client, reviewer, approved_application):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    assert "badge--approved" in body
    assert "badge--submitted" not in body


def test_queue_document_dots_use_distinct_letters_and_titles(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:queue")).content.decode()
    assert 'title="Vecāka ID">V<' in body
    assert 'title="Bērna ID">B<' in body
    assert 'title="Portrets">P<' in body
    assert "docdot--missing" not in body


def test_queue_procesa_and_parakstiti_tabs_are_disjoint(
    client, reviewer, approved_application
):
    from django.utils import timezone

    client.force_login(reviewer)
    name = approved_application.member_full_name

    procesa_body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    parakstiti_body = client.get(
        reverse("admin_hub:queue"), {"tab": "parakstiti"}
    ).content.decode()
    assert name in procesa_body, "approved-but-unsigned belongs in Procesā"
    assert name not in parakstiti_body

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at", "signed_at"])

    procesa_body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    parakstiti_body = client.get(
        reverse("admin_hub:queue"), {"tab": "parakstiti"}
    ).content.decode()
    assert name not in procesa_body
    assert name in parakstiti_body, "signed agreement belongs in Parakstīti"

    # Guard against the exclude()-across-a-reverse-FK duplicate-row trap:
    # the signed application must appear exactly once in its tab's queryset.
    from apps.admin_hub import queries

    assert queries._tab_queryset("parakstiti").filter(pk=approved_application.pk).count() == 1
    assert queries._tab_queryset("procesa").filter(pk=approved_application.pk).count() == 0


def test_queue_procesa_keeps_a_member_with_signed_agreement_history(
    client, reviewer, approved_application
):
    """A member can carry a historical signed agreement (is_current=False)
    alongside a current, still-unsigned one — e.g. a prior season. Only the
    *current* agreement's signed state may move the application to
    Parakstiti; the historical row must not leak across tabs.

    Built directly via Agreement.objects.create(), not the service layer:
    apps/agreements/services.py never actually produces this combination
    today (every is_current transition moves state off SIGNED in the same
    write), so a fixture or service call could not reach this state. The
    query must be correct regardless of what the service layer currently
    guarantees.
    """
    from django.utils import timezone

    from apps.agreements.models import Agreement

    Agreement.objects.create(
        member=approved_application.approved_member,
        is_current=False,
        state=Agreement.State.SIGNED,
        generated_at=timezone.now(),
        signed_at=timezone.now(),
    )

    client.force_login(reviewer)
    name = approved_application.member_full_name

    procesa_body = client.get(reverse("admin_hub:queue"), {"tab": "procesa"}).content.decode()
    parakstiti_body = client.get(
        reverse("admin_hub:queue"), {"tab": "parakstiti"}
    ).content.decode()

    assert name in procesa_body, "current agreement is unsigned; must stay in Procesa"
    assert name not in parakstiti_body

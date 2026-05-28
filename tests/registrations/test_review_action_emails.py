"""P5 Slice A.1 — Contract for templated review-action emails.

Covers the three admin review actions (approve / request_fix / reject):
- Body contains an absolute URL to the application workspace built from SITE_URL.
- Body contains Latvian copy and references the member's full name.
- Reviewer message is included in the body for fix / reject.
- Subjects are the expected Latvian strings.
- Recipient is the guardian email.
- Emails are plain-text only (no HTML alternative).
- SITE_URL is the configurable base.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from apps.registrations.services import (
    approve_application,
    reject_application,
    request_application_fix,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user():
    return User.objects.create_superuser(
        username="reviewer",
        email="reviewer@example.com",
        password="reviewerpass",
    )


def _workspace_path(application_id: int) -> str:
    return str(reverse("registrations:application-workspace", args=[application_id]))


# ---------------------------------------------------------------------------
# approve_application
# ---------------------------------------------------------------------------


def test_approve_application_email_contains_application_url(submitted_application, staff_user, settings):
    mail.outbox.clear()
    approve_application(submitted_application, staff_user)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    expected_url = f"{settings.SITE_URL}{_workspace_path(submitted_application.id)}"
    assert expected_url in msg.body, (
        f"Approve email body must contain absolute application URL {expected_url!r}; "
        f"got body: {msg.body!r}"
    )
    assert submitted_application.member_full_name in msg.body
    assert msg.subject == "Jūsu pieteikums ir apstiprināts"


def test_approve_email_includes_training_group_when_assigned(
    submitted_application, staff_user
):
    from apps.members.models import TrainingGroup

    mail.outbox.clear()
    group = TrainingGroup.objects.create(name="U10 A", is_active=True)
    approve_application(submitted_application, staff_user, training_group=group)

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Treniņu grupa: U10 A." in body


def test_approve_email_omits_training_group_when_unassigned(
    submitted_application, staff_user
):
    mail.outbox.clear()
    approve_application(submitted_application, staff_user)

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    assert "Treniņu grupa" not in body


# ---------------------------------------------------------------------------
# request_application_fix
# ---------------------------------------------------------------------------


def test_request_fix_email_contains_application_url_and_review_message(
    submitted_application, staff_user, settings
):
    mail.outbox.clear()
    review_msg = "Lūdzu, pievienojiet bērna ID dokumenta otru pusi."
    request_application_fix(submitted_application, staff_user, review_msg)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    expected_url = f"{settings.SITE_URL}{_workspace_path(submitted_application.id)}"
    assert expected_url in msg.body, (
        f"Fix-request email body must contain {expected_url!r}; got: {msg.body!r}"
    )
    assert review_msg in msg.body
    assert msg.subject == "Jūsu pieteikums ir jālabo"


# ---------------------------------------------------------------------------
# reject_application
# ---------------------------------------------------------------------------


def test_reject_email_contains_review_message(submitted_application, staff_user):
    mail.outbox.clear()
    reason = "Pieteikums neatbilst prasībām."
    reject_application(submitted_application, staff_user, reason)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert reason in msg.body
    assert msg.subject == "Jūsu pieteikums ir noraidīts"
    # Rejected parents still get a self-service link to the parent portal so
    # they can review their applications without hunting for the URL.
    portal_url = f"{settings.SITE_URL}{reverse('registrations:parent-portal')}"
    assert portal_url in msg.body


# ---------------------------------------------------------------------------
# Subjects (parametrized across the three actions)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action_name,expected_subject",
    [
        ("approve", "Jūsu pieteikums ir apstiprināts"),
        ("fix", "Jūsu pieteikums ir jālabo"),
        ("reject", "Jūsu pieteikums ir noraidīts"),
    ],
)
def test_email_subject_is_latvian(
    submitted_application, staff_user, action_name, expected_subject
):
    mail.outbox.clear()
    if action_name == "approve":
        approve_application(submitted_application, staff_user)
    elif action_name == "fix":
        request_application_fix(submitted_application, staff_user, "Lūdzu, labojiet.")
    else:
        reject_application(submitted_application, staff_user, "Neatbilst.")

    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == expected_subject


# ---------------------------------------------------------------------------
# Recipient & plain-text shape
# ---------------------------------------------------------------------------


def test_email_recipient_is_guardian_email(submitted_application, staff_user):
    mail.outbox.clear()
    approve_application(submitted_application, staff_user)
    assert mail.outbox[0].to == [submitted_application.guardian_email]


def test_email_body_is_plain_text_only(submitted_application, staff_user):
    mail.outbox.clear()
    approve_application(submitted_application, staff_user)
    msg = mail.outbox[0]
    # send_mail() builds an EmailMessage (no alternatives attribute) or empty list.
    alternatives = getattr(msg, "alternatives", [])
    assert alternatives == [], (
        f"Review-action emails must be plain-text only; got alternatives: {alternatives!r}"
    )


# ---------------------------------------------------------------------------
# SITE_URL is honoured
# ---------------------------------------------------------------------------


def test_email_uses_site_url_setting(submitted_application, staff_user):
    mail.outbox.clear()
    with override_settings(SITE_URL="https://example.test"):
        approve_application(submitted_application, staff_user)

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    expected_url = f"https://example.test{_workspace_path(submitted_application.id)}"
    assert expected_url in body, (
        f"Email body must use SITE_URL override; expected {expected_url!r} in body: {body!r}"
    )

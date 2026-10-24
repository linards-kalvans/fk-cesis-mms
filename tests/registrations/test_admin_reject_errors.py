"""Rejection endpoint: discoverable UI plus truthful known-error mapping.

Unit 3 Task 5 keeps ``reject_application``'s submitted-only, nonblank-message
rule. These tests pin the admin dispatcher's exact Latvian mapping, the
unchanged redirect contract, and the fact that rejection never writes
correction history or sends a request-fix email.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditEvent
from apps.registrations.models import (
    ApplicationCorrectionMessage,
    RegistrationApplication,
)

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]

HUB_URL = "/hub/pieteikumi/"


@pytest.fixture
def reviewer(db):
    return User.objects.create_superuser(
        username="reject-reviewer", email="reject@example.com", password="pw"
    )


@pytest.fixture
def staff_client(reviewer):
    client = Client()
    client.login(username="reject-reviewer", password="pw")
    return client


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _changelist_url():
    return reverse("admin:registrations_registrationapplication_changelist")


def _post(client, application, message, *, next_url=None):
    url = _action_url(application.pk)
    if next_url is not None:
        url = f"{url}?next={next_url}"
    return client.post(
        url, {"action": "reject", "review_message": message}, follow=False
    )


def _rejected_audit_count():
    return AuditEvent.objects.filter(
        action=str(AuditEvent.Action.APPLICATION_REJECTED)
    ).count()


def test_reject_submitted_application_sends_existing_email_and_no_history(
    staff_client, submitted_application, mailoutbox
):
    response = _post(
        staff_client, submitted_application, "  Neatbilst prasībām.  ", next_url=HUB_URL
    )

    assert response.status_code == 302
    assert response["Location"] == HUB_URL

    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.REJECTED
    assert submitted_application.review_message == "Neatbilst prasībām."
    assert submitted_application.reviewed_by is not None

    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.subject == "Jūsu pieteikums ir noraidīts"
    assert message.to == [submitted_application.guardian.email]
    assert ApplicationCorrectionMessage.objects.count() == 0
    assert _rejected_audit_count() == 1


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
def test_blank_reject_message_is_rejected_with_latvian_copy(
    staff_client, submitted_application, mailoutbox, message
):
    response = _post(staff_client, submitted_application, message, next_url=HUB_URL)

    assert response.status_code == 302
    assert response["Location"] == HUB_URL
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED
    assert len(mailoutbox) == 0
    assert _rejected_audit_count() == 0
    assert ApplicationCorrectionMessage.objects.count() == 0

    followed = staff_client.get(HUB_URL, follow=True)
    assert "Noraidīšanas ziņojums ir obligāts." in followed.content.decode()


@pytest.mark.parametrize(
    "status",
    [
        RegistrationApplication.Status.DRAFT,
        RegistrationApplication.Status.FIX_REQUESTED,
        RegistrationApplication.Status.APPROVED,
        RegistrationApplication.Status.REJECTED,
    ],
)
def test_reject_from_a_wrong_state_reports_the_wrong_state_not_a_missing_note(
    staff_client, submitted_application, mailoutbox, status
):
    submitted_application.status = status
    submitted_application.save(update_fields=["status"])
    before = (submitted_application.status, submitted_application.review_message)

    response = _post(
        staff_client, submitted_application, "Noraidīt", next_url=HUB_URL
    )

    assert response.status_code == 302
    assert response["Location"] == HUB_URL
    submitted_application.refresh_from_db()
    assert (submitted_application.status, submitted_application.review_message) == before
    assert len(mailoutbox) == 0
    assert _rejected_audit_count() == 0
    assert ApplicationCorrectionMessage.objects.count() == 0

    followed = staff_client.get(HUB_URL, follow=True)
    body = followed.content.decode()
    assert "Noraidīt var tikai iesniegtu pieteikumu." in body
    assert "Noraidīšanas ziņojums ir obligāts." not in body


def test_unexpected_value_error_stays_observable(
    staff_client, submitted_application, monkeypatch
):
    def _explode(*args, **kwargs):
        raise ValueError("unexpected reject failure")

    monkeypatch.setattr(
        "apps.registrations.admin.reject_application", _explode, raising=True
    )

    with pytest.raises(ValueError, match="unexpected reject failure"):
        _post(staff_client, submitted_application, "Noraidīt", next_url=HUB_URL)

    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED


def test_reject_requires_change_permission(submitted_application):
    user = User.objects.create_user(
        username="reject-viewer", password="x", is_staff=True
    )
    client = Client()
    client.login(username="reject-viewer", password="x")

    response = _post(client, submitted_application, "Noraidīt", next_url=HUB_URL)

    assert response.status_code == 403
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED


def test_anonymous_reject_is_denied(submitted_application, mailoutbox):
    response = _post(Client(), submitted_application, "Noraidīt", next_url=HUB_URL)

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]
    assert len(mailoutbox) == 0


def test_reject_requires_csrf(reviewer, submitted_application):
    client = Client(enforce_csrf_checks=True)
    client.login(username="reject-reviewer", password="pw")

    response = client.post(
        _action_url(submitted_application.pk),
        {"action": "reject", "review_message": "Noraidīt"},
    )

    assert response.status_code == 403
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED


def test_get_never_mutates(staff_client, submitted_application):
    response = staff_client.get(_action_url(submitted_application.pk))

    assert response.status_code == 302
    assert response["Location"] == _change_url(submitted_application.pk)
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED


def test_reject_success_without_next_keeps_the_changelist_fallback(
    staff_client, submitted_application
):
    response = _post(staff_client, submitted_application, "Noraidīt")

    assert response.status_code == 302
    assert response["Location"] == _changelist_url()


def test_reject_ignores_an_unsafe_next(staff_client, submitted_application):
    response = _post(
        staff_client,
        submitted_application,
        "Noraidīt",
        next_url="https://evil.example.com/",
    )

    assert response.status_code == 302
    assert "evil.example.com" not in response["Location"]
    assert response["Location"] == _changelist_url()


def test_reject_error_without_next_stays_on_the_change_page(
    staff_client, submitted_application
):
    response = _post(staff_client, submitted_application, "")

    assert response.status_code == 302
    assert response["Location"] == _change_url(submitted_application.pk)

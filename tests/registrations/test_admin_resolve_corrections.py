"""Unit 2 — admin ``resolve_corrections`` endpoint contract.

The action rides the already registered application review-action endpoint.
These tests cover the state mapping, permissions, POST/CSRF boundary, redirect
safety and idempotent replay without changing any application source.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.registrations import services
from apps.registrations.models import (
    ApplicationCorrectionMessage,
    RegistrationApplication,
)

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]

SERVICE = getattr(services, "resolve_application_corrections", None)
RESOLVED_ACTION = getattr(
    AuditEvent.Action, "APPLICATION_CORRECTIONS_RESOLVED", None
)

PROMPT_STATE_ERROR = (
    "Labojumus var atzīmēt kā atrisinātus tikai pieteikumam statusā Jālabo."
)
INCONSISTENT_HISTORY_ERROR = (
    "Iesniegtam pieteikumam ir neatrisināti labojumu pieprasījumi. "
    "Pārbaudiet pieteikuma stāvokli."
)


def _action_url(application):
    return reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application.pk],
    )


def _change_url(application):
    return reverse(
        "admin:registrations_registrationapplication_change",
        args=[application.pk],
    )


@pytest.fixture
def reviewer():
    return User.objects.create_superuser(
        username="admin-resolve-reviewer",
        email="admin-resolve@example.com",
        password="pw",
    )


def _message(application, reviewer, status=ApplicationCorrectionMessage.Status.SENT):
    return ApplicationCorrectionMessage.objects.create(
        application=application,
        actor=reviewer,
        subject="Labojums",
        body="Lūdzu, labojiet.",
        review_message="Labojiet datus.",
        status=status,
    )


def _audit_count():
    return AuditEvent.objects.filter(action=str(RESOLVED_ACTION)).count()


@contextmanager
def commit_callbacks_executed():
    """Capture ``transaction.on_commit`` callbacks and run them on success."""
    callbacks = []

    def capture(func, *args, **kwargs):
        callbacks.append(func)

    with patch("django.db.transaction.on_commit", side_effect=capture):
        yield
    for callback in callbacks:
        callback()


def _assert_unchanged(application, row=None, *, status=None):
    application.refresh_from_db()
    if status is not None:
        assert application.status == status
    if row is not None:
        row.refresh_from_db()
        assert row.resolved_at is None


class TestResolveCorrectionsSuccess:
    def test_success_honours_a_safe_next(
        self, staff_client, fix_requested_application, reviewer
    ):
        row = _message(fix_requested_application, reviewer)
        _assert_action_available()

        with commit_callbacks_executed():
            response = staff_client.post(
                f"{_action_url(fix_requested_application)}?next=/hub/pieteikumi/",
                {"action": "resolve_corrections"},
            )

        assert response.status_code == 302
        assert response["Location"] == "/hub/pieteikumi/"
        fix_requested_application.refresh_from_db()
        row.refresh_from_db()
        assert (
            fix_requested_application.status
            == RegistrationApplication.Status.SUBMITTED
        )
        assert row.resolved_at is not None
        assert row.resolution_source == "staff_manual"
        # ``staff_client`` is logged in as its own "staff" superuser; the
        # reviewer fixture above seeds correspondence but does not post.
        assert row.resolved_by_id == User.objects.get(username="staff").id
        assert _audit_count() == 1

    def test_success_without_next_lands_on_the_change_page(
        self, staff_client, fix_requested_application, reviewer
    ):
        _message(fix_requested_application, reviewer)
        _assert_action_available()

        response = staff_client.post(
            _action_url(fix_requested_application),
            {"action": "resolve_corrections"},
        )

        assert response.status_code == 302
        assert response["Location"] == _change_url(fix_requested_application)

    def test_zero_history_fix_requested_is_allowed(
        self, staff_client, fix_requested_application
    ):
        _assert_action_available()
        assert not ApplicationCorrectionMessage.objects.filter(
            application=fix_requested_application
        ).exists()

        with commit_callbacks_executed():
            response = staff_client.post(
                _action_url(fix_requested_application),
                {"action": "resolve_corrections"},
            )

        assert response.status_code == 302
        fix_requested_application.refresh_from_db()
        assert (
            fix_requested_application.status
            == RegistrationApplication.Status.SUBMITTED
        )
        assert not ApplicationCorrectionMessage.objects.filter(
            application=fix_requested_application
        ).exists()
        event = AuditEvent.objects.get(action=str(RESOLVED_ACTION))
        assert event.metadata["resolved_count"] == 0

    def test_replay_is_idempotent(
        self, staff_client, fix_requested_application, reviewer
    ):
        row = _message(fix_requested_application, reviewer)
        _assert_action_available()

        with commit_callbacks_executed():
            first = staff_client.post(
                f"{_action_url(fix_requested_application)}?next=/hub/pieteikumi/",
                {"action": "resolve_corrections"},
            )
        assert first.status_code == 302
        fix_requested_application.refresh_from_db()
        row.refresh_from_db()
        submitted_at = fix_requested_application.submitted_at
        resolved_at = row.resolved_at
        audit_count = _audit_count()

        with commit_callbacks_executed():
            second = staff_client.post(
                f"{_action_url(fix_requested_application)}?next=/hub/pieteikumi/",
                {"action": "resolve_corrections"},
            )

        assert second.status_code == 302
        fix_requested_application.refresh_from_db()
        row.refresh_from_db()
        assert fix_requested_application.submitted_at == submitted_at
        assert row.resolved_at == resolved_at
        assert _audit_count() == audit_count


class TestResolveCorrectionsSecurity:
    def test_get_never_mutates(self, staff_client, fix_requested_application, reviewer):
        row = _message(fix_requested_application, reviewer)
        _assert_action_available()

        response = staff_client.get(
            f"{_action_url(fix_requested_application)}?action=resolve_corrections"
        )

        assert response.status_code == 302
        assert response["Location"] == _change_url(fix_requested_application)
        _assert_unchanged(
            fix_requested_application,
            row,
            status=RegistrationApplication.Status.FIX_REQUESTED,
        )
        assert _audit_count() == 0

    def test_anonymous_is_blocked(self, fix_requested_application, reviewer):
        row = _message(fix_requested_application, reviewer)
        response = Client().post(
            _action_url(fix_requested_application),
            {"action": "resolve_corrections"},
        )

        assert response.status_code in (302, 403)
        _assert_unchanged(
            fix_requested_application,
            row,
            status=RegistrationApplication.Status.FIX_REQUESTED,
        )

    def test_nonstaff_authenticated_is_blocked(
        self, fix_requested_application, reviewer
    ):
        row = _message(fix_requested_application, reviewer)
        user = User.objects.create_user(
            username="ordinary-user", email="ordinary@example.com", password="pw"
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            _action_url(fix_requested_application),
            {"action": "resolve_corrections"},
        )

        assert response.status_code in (302, 403)
        _assert_unchanged(
            fix_requested_application,
            row,
            status=RegistrationApplication.Status.FIX_REQUESTED,
        )

    def test_staff_without_change_permission_is_denied(
        self, fix_requested_application, reviewer
    ):
        row = _message(fix_requested_application, reviewer)
        user = User.objects.create_user(
            username="view-only",
            email="view-only@example.com",
            password="pw",
            is_staff=True,
        )
        client = Client()
        client.force_login(user)

        response = client.post(
            _action_url(fix_requested_application),
            {"action": "resolve_corrections"},
        )

        assert response.status_code == 403
        _assert_unchanged(
            fix_requested_application,
            row,
            status=RegistrationApplication.Status.FIX_REQUESTED,
        )
        assert _audit_count() == 0

    def test_enforced_csrf_requires_a_token(
        self, fix_requested_application, reviewer
    ):
        row = _message(fix_requested_application, reviewer)
        _assert_action_available()
        client = Client(enforce_csrf_checks=True)
        client.force_login(reviewer)
        client.get(_change_url(fix_requested_application))
        token = client.cookies["csrftoken"].value

        missing = client.post(
            _action_url(fix_requested_application),
            {"action": "resolve_corrections"},
        )
        assert missing.status_code == 403
        _assert_unchanged(
            fix_requested_application,
            row,
            status=RegistrationApplication.Status.FIX_REQUESTED,
        )

        accepted = client.post(
            _action_url(fix_requested_application),
            {"action": "resolve_corrections"},
            HTTP_X_CSRFTOKEN=token,
        )
        assert accepted.status_code == 302
        fix_requested_application.refresh_from_db()
        assert (
            fix_requested_application.status
            == RegistrationApplication.Status.SUBMITTED
        )

    @pytest.mark.parametrize(
        "unsafe_next",
        ["https://evil.example.com/", "//evil.example.com/"],
    )
    def test_unsafe_next_is_ignored(
        self, staff_client, fix_requested_application, reviewer, unsafe_next
    ):
        _message(fix_requested_application, reviewer)
        _assert_action_available()

        response = staff_client.post(
            f"{_action_url(fix_requested_application)}?next={unsafe_next}",
            {"action": "resolve_corrections"},
        )

        assert response.status_code == 302
        assert response["Location"] == _change_url(fix_requested_application)
        assert "evil.example.com" not in response["Location"]


class TestResolveCorrectionsExpectedErrors:
    def test_submitted_with_unresolved_maps_to_fixed_latvian_message(
        self, staff_client, submitted_application, reviewer
    ):
        row = _message(submitted_application, reviewer)
        old_digest = timezone.now() - timezone.timedelta(hours=1)
        RegistrationApplication.objects.filter(
            pk=submitted_application.pk
        ).update(submission_digest_sent_at=old_digest)
        submitted_application.refresh_from_db()
        _assert_action_available()

        with commit_callbacks_executed():
            response = staff_client.post(
                f"{_action_url(submitted_application)}?next=/hub/pieteikumi/",
                {"action": "resolve_corrections"},
                follow=True,
            )

        assert response.status_code == 200
        assert INCONSISTENT_HISTORY_ERROR.encode() in response.content
        submitted_application.refresh_from_db()
        row.refresh_from_db()
        assert (
            submitted_application.status
            == RegistrationApplication.Status.SUBMITTED
        )
        assert submitted_application.submission_digest_sent_at == old_digest
        assert row.resolved_at is None
        assert _audit_count() == 0

    def test_wrong_state_maps_to_fixed_latvian_message(
        self, staff_client, fix_requested_application, reviewer
    ):
        RegistrationApplication.objects.filter(
            pk=fix_requested_application.pk
        ).update(status=RegistrationApplication.Status.DRAFT)
        fix_requested_application.refresh_from_db()
        row = _message(fix_requested_application, reviewer)
        _assert_action_available()

        response = staff_client.post(
            f"{_action_url(fix_requested_application)}?next=/hub/pieteikumi/",
            {"action": "resolve_corrections"},
            follow=True,
        )

        assert response.status_code == 200
        assert PROMPT_STATE_ERROR.encode() in response.content
        _assert_unchanged(
            fix_requested_application,
            row,
            status=RegistrationApplication.Status.DRAFT,
        )
        assert _audit_count() == 0


class TestResolveCorrectionsUnexpectedErrors:
    def test_unexpected_service_error_is_not_reported_as_success(
        self, staff_client, fix_requested_application, reviewer
    ):
        _message(fix_requested_application, reviewer)
        _assert_action_available()

        with _unexpected_resolver_error():
            with pytest.raises(RuntimeError, match="unexpected history failure"):
                staff_client.post(
                    _action_url(fix_requested_application),
                    {"action": "resolve_corrections"},
                )

        fix_requested_application.refresh_from_db()
        assert (
            fix_requested_application.status
            == RegistrationApplication.Status.FIX_REQUESTED
        )


def _assert_action_available():
    assert SERVICE is not None, (
        "apps.registrations.services.resolve_application_corrections is missing"
    )
    assert RESOLVED_ACTION is not None, (
        "AuditEvent.Action.APPLICATION_CORRECTIONS_RESOLVED is missing"
    )


def _unexpected_resolver_error():
    """Patch whichever binding the admin dispatcher actually uses."""
    from apps.registrations import admin as admin_module

    if hasattr(admin_module, "resolve_application_corrections"):
        return patch.object(
            admin_module,
            "resolve_application_corrections",
            side_effect=RuntimeError("unexpected history failure"),
        )
    return patch.object(
        services,
        "resolve_application_corrections",
        side_effect=RuntimeError("unexpected history failure"),
    )

"""Slice 4 (Task 4) — correction-request history model and send lifecycle.

Covers the domain contract only: send-time snapshot, honest outcomes,
non-atomic failure persistence, resubmission resolution, immutable content,
and the boundaries of the tracked ``request_fix`` path.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.registrations import services as registration_services
from apps.registrations.models import (
    ApplicationCorrectionMessage,
    RegistrationApplication,
)
from apps.registrations.services import (
    approve_application,
    create_or_update_draft,
    reject_application,
    request_application_fix,
    submit_application,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer():
    return User.objects.create_superuser(
        username="correction-reviewer",
        email="reviewer@example.com",
        password="reviewerpass",
    )


def _message_rows():
    return ApplicationCorrectionMessage.objects.order_by("created_at", "pk")


class _FailingResolutionQuerySet:
    """Real queryset that applies ``update`` before raising.

    Wrapping (instead of mocking) the update proves the rollback covers a
    resolution write that genuinely reached the database inside the
    transaction, not just one that never ran.
    """

    def __init__(self, queryset):
        self._queryset = queryset
        self.update_calls = 0
        self.updated_rows = 0

    def update(self, **kwargs):
        self.update_calls += 1
        self.updated_rows = self._queryset.update(**kwargs)
        raise RuntimeError("history resolution write failed")

    def __getattr__(self, name):
        return getattr(self._queryset, name)


class _FailingResolutionManager:
    """Stand-in for ``ApplicationCorrectionMessage.objects``."""

    def __init__(self, manager):
        self._manager = manager
        self.querysets: list[_FailingResolutionQuerySet] = []

    def filter(self, *args, **kwargs):
        queryset = _FailingResolutionQuerySet(
            self._manager.filter(*args, **kwargs)
        )
        self.querysets.append(queryset)
        return queryset

    def __getattr__(self, name):
        return getattr(self._manager, name)


class TestSendLifecycle:
    def test_pending_row_exists_before_mail_and_snapshot_matches_outgoing(
        self, submitted_application, reviewer
    ):
        captured: dict[str, object] = {}

        def fake_send_mail(**kwargs):
            row = ApplicationCorrectionMessage.objects.get()
            assert row.status == ApplicationCorrectionMessage.Status.PENDING
            captured.update(kwargs)
            return 1

        message = "  Lūdzu, labojiet adresi.  "
        with patch(
            "apps.registrations.services.send_mail", side_effect=fake_send_mail
        ):
            returned = request_application_fix(
                submitted_application, reviewer, message
            )

        assert returned is submitted_application
        row = ApplicationCorrectionMessage.objects.get()
        assert row.application_id == submitted_application.id
        assert row.actor_id == reviewer.id
        assert row.review_message == "Lūdzu, labojiet adresi."
        assert row.subject == "Jūsu pieteikums ir jālabo"
        assert captured["subject"] == row.subject
        assert captured["message"] == row.body
        assert row.body == captured["message"]
        assert submitted_application.member_full_name in str(row.body)
        assert row.status == ApplicationCorrectionMessage.Status.SENT
        assert row.sent_at is not None
        assert row.resolved_at is None

    def test_render_once_and_reuse_exact_subject_body(
        self, submitted_application, reviewer
    ):
        captured: dict[str, object] = {}

        def fake_send_mail(**kwargs):
            captured.update(kwargs)
            return 1

        with (
            patch(
                "apps.registrations.services.render_to_string",
                wraps=render_to_string,
            ) as render,
            patch(
                "apps.registrations.services.send_mail", side_effect=fake_send_mail
            ),
        ):
            request_application_fix(
                submitted_application, reviewer, "Viena renderēšana."
            )

        assert render.call_count == 1
        row = ApplicationCorrectionMessage.objects.get()
        assert row.subject == captured["subject"]
        assert row.body == captured["message"]

    def test_return_zero_marks_failed_without_sent_at_or_new_exception(
        self, submitted_application, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=0):
            returned = request_application_fix(
                submitted_application, reviewer, "Sūtīšana atgriež 0."
            )

        assert returned is submitted_application
        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.FAILED
        assert row.sent_at is None
        assert row.body

    @pytest.mark.parametrize("send_result", [None, 2])
    def test_any_non_one_return_marks_failed(
        self, submitted_application, reviewer, send_result
    ):
        with patch(
            "apps.registrations.services.send_mail", return_value=send_result
        ):
            request_application_fix(
                submitted_application, reviewer, "Cits rezultāts."
            )

        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.FAILED
        assert row.sent_at is None

    def test_mail_exception_marks_failed_then_reraises_original(
        self, submitted_application, reviewer
    ):
        original = RuntimeError("mail backend down")
        with patch(
            "apps.registrations.services.send_mail", side_effect=original
        ):
            with pytest.raises(RuntimeError) as exc_info:
                request_application_fix(
                    submitted_application, reviewer, "Sūtīšana neizdevās."
                )

        assert exc_info.value is original
        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.FAILED
        assert row.sent_at is None
        # No raw exception text is persisted.
        assert "mail backend down" not in row.body
        assert "mail backend down" not in row.subject

    def test_mail_exception_when_failure_write_also_fails_keeps_pending(
        self, submitted_application, reviewer, monkeypatch
    ):
        original_mail_error = RuntimeError("smtp backend down")
        original_save = ApplicationCorrectionMessage.save
        calls: list[list[str] | None] = []

        def flaky_save(self, *args, **kwargs):
            calls.append(kwargs.get("update_fields"))
            if len(calls) == 2:
                raise RuntimeError("failed-status write failed")
            return original_save(self, *args, **kwargs)

        monkeypatch.setattr(ApplicationCorrectionMessage, "save", flaky_save)

        with patch(
            "apps.registrations.services.send_mail",
            side_effect=original_mail_error,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                request_application_fix(
                    submitted_application, reviewer, "Sūtīšana neizdevās."
                )

        # The mail exception is the one the caller sees, not the outcome-write
        # error that was swallowed while recording it.
        assert exc_info.value is original_mail_error
        assert len(calls) == 2
        assert calls[1] == ["status"]

        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.PENDING
        assert row.sent_at is None
        # Neither exception is persisted as content.
        for text in (row.subject, row.body, row.review_message):
            assert "smtp backend down" not in text
            assert "failed-status write failed" not in text

    def test_interruption_before_outcome_leaves_pending(
        self, submitted_application, reviewer
    ):
        with patch(
            "apps.registrations.services.send_mail",
            side_effect=KeyboardInterrupt,
        ):
            with pytest.raises(KeyboardInterrupt):
                request_application_fix(
                    submitted_application, reviewer, "Pārtraukta apstrāde."
                )

        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.PENDING
        assert row.sent_at is None

    def test_outcome_write_failure_leaves_pending_not_failed(
        self, submitted_application, reviewer, monkeypatch
    ):
        original_save = ApplicationCorrectionMessage.save
        calls = {"count": 0}

        def flaky_save(self, *args, **kwargs):
            calls["count"] += 1
            if calls["count"] >= 2:
                raise RuntimeError("outcome write failed")
            return original_save(self, *args, **kwargs)

        monkeypatch.setattr(ApplicationCorrectionMessage, "save", flaky_save)

        with patch("apps.registrations.services.send_mail", return_value=1):
            with pytest.raises(RuntimeError, match="outcome write failed"):
                request_application_fix(
                    submitted_application, reviewer, "Rezultāts nezūd."
                )

        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.PENDING
        assert row.sent_at is None


class TestTrackedPathBoundaries:
    def test_reject_creates_no_history(self, submitted_application, reviewer):
        with patch("apps.registrations.services.send_mail", return_value=1):
            returned = reject_application(
                submitted_application, reviewer, "Noraidīts."
            )

        assert returned is submitted_application
        assert not _message_rows().exists()

    def test_approve_creates_no_history(
        self, fix_requested_application, parent_account, reviewer
    ):
        submitted = submit_application(
            fix_requested_application, parent_account
        )
        with patch("apps.registrations.services.send_mail", return_value=1):
            returned = approve_application(submitted, reviewer)

        assert returned is submitted
        assert not _message_rows().exists()

    def test_repeated_correction_cycles_append_immutable_rows(
        self, submitted_application, parent_account, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Pirmais labojums."
            )

        first = ApplicationCorrectionMessage.objects.get()
        first_body = first.body
        first_note = first.review_message

        submit_application(submitted_application, parent_account)

        # Editing the mutable review note afterwards cannot rewrite history.
        submitted_application.review_message = "Cits teksts."
        submitted_application.save(update_fields=["review_message"])

        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Otrais labojums."
            )

        rows = list(_message_rows())
        assert len(rows) == 2
        assert rows[0].review_message == first_note
        assert rows[0].body == first_body
        assert rows[1].review_message == "Otrais labojums."
        assert rows[0].resolved_at is not None
        assert rows[1].resolved_at is None


class TestResubmissionResolution:
    def test_submit_resolves_every_unresolved_status(
        self, submitted_application, parent_account, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Labojiet."
            )

        sent = ApplicationCorrectionMessage.objects.get()
        pending = ApplicationCorrectionMessage.objects.create(
            application=submitted_application,
            actor=reviewer,
            subject="pending subject",
            body="pending body",
            status=ApplicationCorrectionMessage.Status.PENDING,
        )
        failed = ApplicationCorrectionMessage.objects.create(
            application=submitted_application,
            actor=reviewer,
            subject="failed subject",
            body="failed body",
            status=ApplicationCorrectionMessage.Status.FAILED,
        )
        old_resolved_at = timezone.now() - timedelta(days=1)
        already = ApplicationCorrectionMessage.objects.create(
            application=submitted_application,
            actor=reviewer,
            subject="old subject",
            body="old body",
            status=ApplicationCorrectionMessage.Status.SENT,
            sent_at=old_resolved_at,
            resolved_at=old_resolved_at,
        )

        submit_application(submitted_application, parent_account)

        for row in (sent, pending, failed):
            row.refresh_from_db()
            assert row.resolved_at is not None
            assert (
                row.resolution_source
                == ApplicationCorrectionMessage.ResolutionSource.PARENT_RESUBMISSION
            )
            assert row.resolved_by_id is None
        already.refresh_from_db()
        assert already.resolved_at == old_resolved_at
        assert already.resolution_source == ""
        assert already.resolved_by_id is None

    def test_invalid_submission_does_not_resolve(
        self, submitted_application, parent_account, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Labojiet."
            )

        submitted_application.member_full_name = ""
        submitted_application.save(update_fields=["member_full_name"])

        with pytest.raises(ValueError):
            submit_application(submitted_application, parent_account)

        row = ApplicationCorrectionMessage.objects.get()
        assert row.resolved_at is None

    def test_draft_save_does_not_resolve(
        self, submitted_application, parent_account, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Labojiet."
            )

        create_or_update_draft(
            data={"guardian_email": parent_account.email},
            files={},
            application=submitted_application,
            verified_account=parent_account,
        )

        row = ApplicationCorrectionMessage.objects.get()
        assert row.resolved_at is None

    def test_submission_returns_the_passed_instance_with_fresh_transition_fields(
        self, fix_requested_application, parent_account, reviewer
    ):
        application = fix_requested_application
        application.reviewed_by = reviewer
        application.reviewed_at = timezone.now() - timedelta(hours=1)
        application.submission_digest_sent_at = timezone.now() - timedelta(hours=2)
        application.save(
            update_fields=[
                "reviewed_by_id",
                "reviewed_at",
                "submission_digest_sent_at",
            ]
        )

        returned = submit_application(application, parent_account)

        # Immediate view callers ignore the return and read this instance's
        # status for analytics, so the passed instance must not stay stale.
        assert returned is application
        assert application.status == RegistrationApplication.Status.SUBMITTED
        assert application.submitted_at is not None
        assert application.review_message == ""
        assert application.reviewed_by_id is None
        assert application.reviewed_at is None
        assert application.submission_digest_sent_at is None

    def test_stale_parent_submit_cannot_overwrite_staff_resolution(
        self, fix_requested_application, parent_account, reviewer
    ):
        application = fix_requested_application
        row = ApplicationCorrectionMessage.objects.create(
            application=application,
            actor=reviewer,
            subject="staff-resolved subject",
            body="staff-resolved body",
            status=ApplicationCorrectionMessage.Status.SENT,
        )
        stale_parent_instance = RegistrationApplication.objects.get(pk=application.pk)

        registration_services.resolve_application_corrections(
            application, reviewer
        )

        # The digest may have been delivered after staff resolution; a losing
        # parent submission must neither clear it nor replace staff provenance.
        digest_sent_at = timezone.now() - timedelta(minutes=5)
        RegistrationApplication.objects.filter(pk=application.pk).update(
            submission_digest_sent_at=digest_sent_at
        )
        staff_submitted_at = RegistrationApplication.objects.values_list(
            "submitted_at", flat=True
        ).get(pk=application.pk)

        with pytest.raises(
            ValueError, match="only draft or fix_requested applications can be submitted"
        ):
            submit_application(stale_parent_instance, parent_account)

        application.refresh_from_db()
        row.refresh_from_db()
        assert application.status == RegistrationApplication.Status.SUBMITTED
        assert application.submitted_at == staff_submitted_at
        assert application.submission_digest_sent_at == digest_sent_at
        assert row.resolved_at is not None
        assert row.resolution_source == "staff_manual"
        assert row.resolved_by_id == reviewer.id

    def test_submission_save_failure_rolls_back_resolution(
        self, fix_requested_application, parent_account
    ):
        row = ApplicationCorrectionMessage.objects.create(
            application=fix_requested_application,
            subject="subject",
            body="body",
        )

        with patch.object(
            RegistrationApplication,
            "save",
            side_effect=RuntimeError("submission write failed"),
        ):
            with pytest.raises(RuntimeError, match="submission write failed"):
                submit_application(fix_requested_application, parent_account)

        row.refresh_from_db()
        fix_requested_application.refresh_from_db()
        assert row.resolved_at is None
        assert (
            fix_requested_application.status
            == RegistrationApplication.Status.FIX_REQUESTED
        )

    def test_resolution_write_failure_after_submission_save_rolls_back(
        self, fix_requested_application, parent_account, reviewer
    ):
        application = fix_requested_application
        submitted_at = timezone.now() - timedelta(days=1)
        reviewed_at = timezone.now() - timedelta(hours=2)
        digest_sent_at = timezone.now() - timedelta(hours=1)
        application.status = RegistrationApplication.Status.FIX_REQUESTED
        application.review_message = "Labojiet personas datus."
        application.reviewed_by = reviewer
        application.reviewed_at = reviewed_at
        application.submitted_at = submitted_at
        application.submission_digest_sent_at = digest_sent_at
        application.save(
            update_fields=[
                "status",
                "review_message",
                "reviewed_by_id",
                "reviewed_at",
                "submitted_at",
                "submission_digest_sent_at",
            ]
        )

        sent = ApplicationCorrectionMessage.objects.create(
            application=application,
            actor=reviewer,
            subject="sent subject",
            body="sent body",
            status=ApplicationCorrectionMessage.Status.SENT,
            sent_at=timezone.now() - timedelta(days=3),
        )
        pending = ApplicationCorrectionMessage.objects.create(
            application=application,
            actor=reviewer,
            subject="pending subject",
            body="pending body",
            status=ApplicationCorrectionMessage.Status.PENDING,
        )
        failed = ApplicationCorrectionMessage.objects.create(
            application=application,
            actor=reviewer,
            subject="failed subject",
            body="failed body",
            status=ApplicationCorrectionMessage.Status.FAILED,
        )

        manager = _FailingResolutionManager(
            ApplicationCorrectionMessage._default_manager
        )
        with patch.object(ApplicationCorrectionMessage, "objects", manager):
            with pytest.raises(
                RuntimeError, match="history resolution write failed"
            ):
                submit_application(application, parent_account)

        # The resolution UPDATE really executed against the DB (all three
        # unresolved rows) and only then failed; the rollback must undo both
        # the submission write that preceded it and the resolution itself.
        assert len(manager.querysets) == 1
        assert manager.querysets[0].update_calls == 1
        assert manager.querysets[0].updated_rows == 3

        application.refresh_from_db()
        assert (
            application.status
            == RegistrationApplication.Status.FIX_REQUESTED
        )
        assert application.review_message == "Labojiet personas datus."
        assert application.reviewed_by_id == reviewer.id
        assert application.reviewed_at == reviewed_at
        assert application.submitted_at == submitted_at
        assert application.submission_digest_sent_at == digest_sent_at

        for row in (sent, pending, failed):
            row.refresh_from_db()
            assert row.resolved_at is None


class TestModelLifecycle:
    def test_application_cascade_deletes_history(
        self, submitted_application, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Dzēšam."
            )
        assert _message_rows().count() == 1

        submitted_application.delete()

        assert _message_rows().count() == 0

    def test_actor_deletion_sets_null_and_preserves_history(
        self, submitted_application, reviewer
    ):
        with patch("apps.registrations.services.send_mail", return_value=1):
            request_application_fix(
                submitted_application, reviewer, "Dzēšam lietotāju."
            )
        reviewer.delete()

        row = ApplicationCorrectionMessage.objects.get()
        assert row.actor_id is None
        assert row.body
        assert row.status == ApplicationCorrectionMessage.Status.SENT

    def test_ordering_is_created_at_then_pk(
        self, submitted_application
    ):
        first = ApplicationCorrectionMessage.objects.create(
            application=submitted_application, subject="a", body="a"
        )
        second = ApplicationCorrectionMessage.objects.create(
            application=submitted_application, subject="b", body="b"
        )
        third = ApplicationCorrectionMessage.objects.create(
            application=submitted_application, subject="c", body="c"
        )

        assert list(_message_rows()) == [first, second, third]


class TestActualAdminCallersPersistFailures:
    """The real admin entry points do not wrap the send in a transaction, so
    a failed-history row survives a mail exception. These tests use
    ``transaction=True`` to prove persistence outside the test transaction."""

    @pytest.mark.django_db(transaction=True)
    def test_registrations_review_action_persists_failed_history(
        self, staff_client, submitted_application
    ):
        url = reverse(
            "admin:registrations_registrationapplication_review-action",
            args=[submitted_application.id],
        )

        with patch(
            "apps.registrations.services.send_mail",
            side_effect=RuntimeError("smtp rejected"),
        ):
            with pytest.raises(RuntimeError, match="smtp rejected"):
                staff_client.post(
                    url,
                    {
                        "action": "request_fix",
                        "review_message": "Labojiet, lūdzu.",
                    },
                )

        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.FAILED
        assert row.sent_at is None
        assert row.review_message == "Labojiet, lūdzu."

    @pytest.mark.django_db(transaction=True)
    def test_family_hub_request_fix_persists_failed_history(
        self, staff_client, submitted_application
    ):
        guardian = submitted_application.guardian
        url = reverse(
            "admin:members_guardian_family_hub_action", args=[guardian.pk]
        )

        with patch(
            "apps.registrations.services.send_mail",
            side_effect=RuntimeError("smtp rejected"),
        ):
            response = staff_client.post(
                url,
                {
                    "action": "request_fix",
                    "application_id": submitted_application.pk,
                    "review_message": "Labojiet no ģimenes centra.",
                },
            )

        assert response.status_code == 302
        row = ApplicationCorrectionMessage.objects.get()
        assert row.status == ApplicationCorrectionMessage.Status.FAILED
        assert row.sent_at is None
        assert row.review_message == "Labojiet no ģimenes centra."

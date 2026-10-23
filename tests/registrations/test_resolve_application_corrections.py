"""Unit 2 — ``resolve_application_corrections`` domain contract.

These tests describe the approved manual-resolution service before it exists.
They assert state-table behavior, provenance, audit, immutability, rollback and
the absence of approval/member/agreement/email/analytics side effects.
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.db.models import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.registrations import services
from apps.registrations.models import (
    ApplicationCorrectionMessage,
    RegistrationApplication,
)

pytestmark = pytest.mark.django_db

SERVICE = getattr(services, "resolve_application_corrections", None)
RESOLVED_ACTION = getattr(
    AuditEvent.Action, "APPLICATION_CORRECTIONS_RESOLVED", None
)


def _require_service():
    """Fail as a test (not a collection error) until the service exists."""
    assert SERVICE is not None, (
        "apps.registrations.services.resolve_application_corrections is missing"
    )
    return SERVICE


def _require_resolution_fields(model=ApplicationCorrectionMessage):
    names = {field.name for field in model._meta.fields}
    missing = {"resolution_source", "resolved_by"} - names
    assert not missing, f"ApplicationCorrectionMessage missing fields: {missing}"


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


@pytest.fixture
def reviewer():
    return User.objects.create_superuser(
        username="resolve-reviewer",
        email="resolve-reviewer@example.com",
        password="pw",
    )


@pytest.fixture
def fix_app(fix_requested_application):
    return fix_requested_application


def _stamp_review_state(application, reviewer):
    old = timezone.now() - timezone.timedelta(days=2)
    digest = timezone.now() - timezone.timedelta(hours=3)
    RegistrationApplication.objects.filter(pk=application.pk).update(
        submitted_at=old,
        review_message="Lūdzu, labojiet datus.",
        reviewed_by=reviewer,
        reviewed_at=old,
        submission_digest_sent_at=digest,
    )
    application.refresh_from_db()
    return old, digest


def _message(application, reviewer, status, *, sent_at=None, resolved_at=None):
    return ApplicationCorrectionMessage.objects.create(
        application=application,
        actor=reviewer,
        subject=f"{status} subject",
        body=f"{status} body",
        review_message=f"{status} review note",
        status=status,
        sent_at=sent_at,
        resolved_at=resolved_at,
    )


def _snapshot(row):
    row.refresh_from_db()
    return {
        "subject": row.subject,
        "body": row.body,
        "review_message": row.review_message,
        "status": row.status,
        "sent_at": row.sent_at,
        "created_at": row.created_at,
        "actor_id": row.actor_id,
    }


# ---------------------------------------------------------------------------
# Schema contract
# ---------------------------------------------------------------------------


class TestResolutionSchema:
    def test_resolution_source_and_resolved_by_fields_exist(self):
        _require_resolution_fields()
        source = ApplicationCorrectionMessage._meta.get_field("resolution_source")
        resolver = ApplicationCorrectionMessage._meta.get_field("resolved_by")

        assert source.max_length == 32
        assert source.blank is True
        assert source.default == ""
        assert set(dict(source.choices)) == {
            "",
            "parent_resubmission",
            "staff_manual",
        }

        assert resolver.null is True
        assert resolver.blank is True
        assert resolver.remote_field.on_delete.__name__ == "SET_NULL"
        assert resolver.remote_field.related_name == "+"
        assert resolver.related_model._meta.label_lower == "auth.user"

    def test_audit_action_choice_exists(self):
        assert RESOLVED_ACTION is not None, (
            "AuditEvent.Action.APPLICATION_CORRECTIONS_RESOLVED is missing"
        )
        assert str(RESOLVED_ACTION) == "application_corrections_resolved"


# ---------------------------------------------------------------------------
# FIX_REQUESTED transition
# ---------------------------------------------------------------------------


class TestFixRequestedTransition:
    def test_resolves_all_unresolved_attempts_with_one_now_and_keeps_history(
        self, fix_app, reviewer
    ):
        resolve = _require_service()
        _stamp_review_state(fix_app, reviewer)
        old_resolved_at = timezone.now() - timezone.timedelta(days=10)
        sent = _message(
            fix_app,
            reviewer,
            ApplicationCorrectionMessage.Status.SENT,
            sent_at=timezone.now() - timezone.timedelta(days=1),
        )
        pending = _message(
            fix_app, reviewer, ApplicationCorrectionMessage.Status.PENDING
        )
        failed = _message(
            fix_app, reviewer, ApplicationCorrectionMessage.Status.FAILED
        )
        already = _message(
            fix_app,
            reviewer,
            ApplicationCorrectionMessage.Status.SENT,
            sent_at=old_resolved_at,
            resolved_at=old_resolved_at,
        )
        before = {row.pk: _snapshot(row) for row in (sent, pending, failed, already)}

        started = timezone.now()
        returned = resolve(fix_app, reviewer)
        finished = timezone.now()

        assert isinstance(returned, RegistrationApplication)
        assert returned.pk == fix_app.pk
        assert returned.status == RegistrationApplication.Status.SUBMITTED
        assert returned.review_message == ""
        assert returned.reviewed_by_id is None
        assert returned.reviewed_at is None
        assert returned.submission_digest_sent_at is None
        assert returned.submitted_at is not None
        assert started <= returned.submitted_at <= finished

        resolved_times = []
        for row in (sent, pending, failed):
            row.refresh_from_db()
            assert row.resolved_at is not None
            assert started <= row.resolved_at <= finished
            assert row.resolution_source == "staff_manual"
            assert row.resolved_by_id == reviewer.id
            resolved_times.append(row.resolved_at)
        assert len(set(resolved_times)) == 1
        assert returned.submitted_at == resolved_times[0]

        already.refresh_from_db()
        assert already.resolved_at == old_resolved_at
        assert already.resolution_source == ""
        assert already.resolved_by_id is None

        for row in (sent, pending, failed, already):
            assert _snapshot(row) == before[row.pk]

    def test_no_fabricated_history_when_zero_attempts(self, fix_app, reviewer):
        resolve = _require_service()
        assert not ApplicationCorrectionMessage.objects.filter(
            application=fix_app
        ).exists()

        with commit_callbacks_executed():
            returned = resolve(fix_app, reviewer)

        assert returned.status == RegistrationApplication.Status.SUBMITTED
        assert not ApplicationCorrectionMessage.objects.filter(
            application=fix_app
        ).exists()
        event = AuditEvent.objects.get(action=str(RESOLVED_ACTION))
        assert event.metadata["resolved_count"] == 0

    def test_bypasses_completeness_gates_without_side_effects(
        self, parent_account, reviewer
    ):
        resolve = _require_service()
        application = RegistrationApplication.objects.create(
            status=RegistrationApplication.Status.FIX_REQUESTED,
            parent_account=parent_account,
            member_full_name="",
        )
        _message(application, reviewer, ApplicationCorrectionMessage.Status.FAILED)

        from apps.agreements.models import Agreement
        from apps.members.models import Member

        member_count = Member.objects.count()
        agreement_count = Agreement.objects.count()

        with (
            patch("apps.analytics.services.track_event") as track_event,
            patch(
                "apps.analytics.services.track_application_submitted"
            ) as track_submitted,
            patch("apps.registrations.services.send_mail") as send_mail,
            commit_callbacks_executed(),
        ):
            resolve(application, reviewer)

        assert Member.objects.count() == member_count
        assert Agreement.objects.count() == agreement_count
        assert track_event.call_count == 0
        assert track_submitted.call_count == 0
        assert send_mail.call_count == 0
        assert application.__class__.objects.get(
            pk=application.pk
        ).status == RegistrationApplication.Status.SUBMITTED

    def test_audit_is_structural_and_redacted(self, fix_app, reviewer):
        resolve = _require_service()
        sent = _message(
            fix_app, reviewer, ApplicationCorrectionMessage.Status.SENT
        )
        pii = [
            fix_app.member_full_name,
            fix_app.guardian_contact_email,
            fix_app.guardian_name,
            sent.subject,
            sent.body,
            sent.review_message,
        ]

        with commit_callbacks_executed():
            resolve(fix_app, reviewer)

        event = AuditEvent.objects.get(action=str(RESOLVED_ACTION))
        assert event.actor_id == reviewer.id
        assert event.target_id == str(fix_app.pk)
        assert "registrationapplication" in event.target_type.lower()
        assert event.target_repr
        assert set(event.metadata) == {
            "from_status",
            "to_status",
            "resolved_count",
            "source",
        }
        assert event.metadata == {
            "from_status": "fix_requested",
            "to_status": "submitted",
            "resolved_count": 1,
            "source": "staff_manual",
        }
        serialized = json.dumps(event.metadata) + event.target_repr
        for value in pii:
            if value:
                assert value not in serialized

    def test_rollback_after_message_update_error_preserves_both_states(
        self, fix_app, reviewer
    ):
        resolve = _require_service()
        old_submitted, digest = _stamp_review_state(fix_app, reviewer)
        row = _message(
            fix_app, reviewer, ApplicationCorrectionMessage.Status.SENT
        )

        class _FailingManager:
            def __init__(self, manager):
                self._manager = manager
                self.updated_rows = 0

            def filter(self, *args, **kwargs):
                outer = self

                class _FailingQueryset:
                    def __init__(self, queryset):
                        self._queryset = queryset

                    def update(self, **kwargs):
                        outer.updated_rows = self._queryset.update(**kwargs)
                        raise RuntimeError("history resolution write failed")

                    def __getattr__(self, name):
                        return getattr(self._queryset, name)

                return _FailingQueryset(self._manager.filter(*args, **kwargs))

            def __getattr__(self, name):
                return getattr(self._manager, name)

        manager = _FailingManager(ApplicationCorrectionMessage._default_manager)
        with patch.object(ApplicationCorrectionMessage, "objects", manager):
            with pytest.raises(
                RuntimeError, match="history resolution write failed"
            ):
                resolve(fix_app, reviewer)

        assert manager.updated_rows == 1
        fix_app.refresh_from_db()
        row.refresh_from_db()
        assert fix_app.status == RegistrationApplication.Status.FIX_REQUESTED
        assert fix_app.review_message == "Lūdzu, labojiet datus."
        assert fix_app.reviewed_by_id == reviewer.id
        assert fix_app.reviewed_at is not None
        assert fix_app.submitted_at == old_submitted
        assert fix_app.submission_digest_sent_at == digest
        assert row.resolved_at is None
        assert row.resolution_source == ""
        assert row.resolved_by_id is None


# ---------------------------------------------------------------------------
# Rejected states / no-op
# ---------------------------------------------------------------------------


class TestStateTable:
    def test_submitted_without_unresolved_is_a_true_no_op(
        self, submitted_application
    ):
        resolve = _require_service()
        before = RegistrationApplication.objects.get(pk=submitted_application.pk)
        audited_before = AuditEvent.objects.count()

        with (
            CaptureQueriesContext(connection) as queries,
            commit_callbacks_executed(),
        ):
            returned = resolve(submitted_application, None)

        updated_tables = [
            q["sql"].upper()
            for q in queries.captured_queries
            if q["sql"].lstrip().upper().startswith("UPDATE")
        ]
        assert not any("REGISTRATIONAPPLICATION" in sql for sql in updated_tables)
        assert not any("APPLICATIONCORRECTIONMESSAGE" in sql for sql in updated_tables)
        assert returned.pk == submitted_application.pk
        assert returned.status == RegistrationApplication.Status.SUBMITTED
        assert returned.submitted_at == before.submitted_at
        assert returned.updated_at == before.updated_at
        assert returned.submission_digest_sent_at == before.submission_digest_sent_at
        assert AuditEvent.objects.count() == audited_before

    def test_submitted_with_unresolved_is_rejected_without_writes(
        self, submitted_application, reviewer
    ):
        resolve = _require_service()
        old_digest = timezone.now() - timezone.timedelta(hours=1)
        RegistrationApplication.objects.filter(
            pk=submitted_application.pk
        ).update(submission_digest_sent_at=old_digest)
        submitted_application.refresh_from_db()
        row = _message(
            submitted_application,
            reviewer,
            ApplicationCorrectionMessage.Status.PENDING,
        )
        before_submitted_at = submitted_application.submitted_at

        with commit_callbacks_executed():
            with pytest.raises(
                ValueError,
                match="^submitted application has unresolved corrections$",
            ):
                resolve(submitted_application, reviewer)

        submitted_application.refresh_from_db()
        row.refresh_from_db()
        assert submitted_application.status == RegistrationApplication.Status.SUBMITTED
        assert submitted_application.submitted_at == before_submitted_at
        assert submitted_application.submission_digest_sent_at == old_digest
        assert row.resolved_at is None
        assert not AuditEvent.objects.filter(
            action=str(RESOLVED_ACTION)
        ).exists()

    @pytest.mark.parametrize(
        "status",
        [
            RegistrationApplication.Status.DRAFT,
            RegistrationApplication.Status.APPROVED,
            RegistrationApplication.Status.REJECTED,
        ],
    )
    def test_other_states_are_rejected_without_writes(
        self, submitted_application, reviewer, status
    ):
        resolve = _require_service()
        RegistrationApplication.objects.filter(
            pk=submitted_application.pk
        ).update(status=status)
        submitted_application.refresh_from_db()
        row = _message(
            submitted_application,
            reviewer,
            ApplicationCorrectionMessage.Status.SENT,
        )

        with commit_callbacks_executed():
            with pytest.raises(
                ValueError,
                match="^cannot resolve corrections in this application state$",
            ):
                resolve(submitted_application, reviewer)

        submitted_application.refresh_from_db()
        row.refresh_from_db()
        assert submitted_application.status == status
        assert row.resolved_at is None
        assert not AuditEvent.objects.filter(
            action=str(RESOLVED_ACTION)
        ).exists()


# ---------------------------------------------------------------------------
# PostgreSQL-only lock / serialization contract
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="row-lock contract is PostgreSQL-only; SQLite is not evidence",
)
class TestPostgresSerialization:
    @staticmethod
    def _backend_pid() -> int:
        """Return the backend pid of this thread's Django connection."""
        from django.db import connection as django_connection

        django_connection.ensure_connection()
        return int(django_connection.connection.info.backend_pid)

    @staticmethod
    def _blocking_pids(probe_cursor, backend_pid: int) -> list[int]:
        probe_cursor.execute("SELECT pg_blocking_pids(%s)", [backend_pid])
        return list(probe_cursor.fetchone()[0])

    @classmethod
    def _wait_for_exact_blocker(
        cls,
        probe_cursor,
        blocked_pid: int,
        holder_pid: int,
        label: str,
    ) -> list[int]:
        """Wait until PostgreSQL reports the exact holder blocking ``blocked_pid``.

        Polling ``pg_blocking_pids`` is the proof, not a fixed sleep: an
        unrelated lock waiter in the database can never satisfy this.
        """
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            blockers = cls._blocking_pids(probe_cursor, blocked_pid)
            if holder_pid in blockers:
                return blockers
            time.sleep(0.01)
        pytest.fail(
            f"{label} backend {blocked_pid} was never blocked by holder "
            f"{holder_pid}; pg_blocking_pids={cls._blocking_pids(probe_cursor, blocked_pid)}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_two_concurrent_resolve_calls_race_and_only_one_transitions(
        self, fix_app, reviewer, monkeypatch
    ):
        import psycopg
        from django.db import close_old_connections
        from django.db import connection as django_connection

        resolve = _require_service()
        _message(fix_app, reviewer, ApplicationCorrectionMessage.Status.FAILED)

        first_holds_lock = threading.Event()
        release_first = threading.Event()
        first_thread_ref: dict[str, threading.Thread] = {}
        first_pid: dict[str, int] = {}
        second_pid: dict[str, int] = {}
        second_ready = threading.Event()
        first_results: list[RegistrationApplication] = []
        second_results: list[RegistrationApplication] = []
        first_errors: list[BaseException] = []
        second_errors: list[BaseException] = []
        original_update = QuerySet.update

        def blocking_update(self, **kwargs):
            result = original_update(self, **kwargs)
            if (
                self.model is ApplicationCorrectionMessage
                and threading.current_thread()
                is first_thread_ref.get("thread")
            ):
                # First resolver has applied the history UPDATE and therefore
                # holds the application row lock; hold its transaction open
                # until the second real resolve call is provably blocked on it.
                first_holds_lock.set()
                if not release_first.wait(15):
                    raise AssertionError("timed out releasing first resolver")
            return result

        monkeypatch.setattr(QuerySet, "update", blocking_update)

        def first_worker():
            close_old_connections()
            try:
                first_pid["pid"] = self._backend_pid()
                first_results.append(resolve(fix_app, reviewer))
            except BaseException as exc:  # noqa: BLE001 — asserted below
                first_errors.append(exc)
            finally:
                django_connection.close()

        def second_worker():
            close_old_connections()
            try:
                second_pid["pid"] = self._backend_pid()
                second_ready.set()
                second_results.append(resolve(fix_app, reviewer))
            except BaseException as exc:  # noqa: BLE001 — asserted below
                second_errors.append(exc)
            finally:
                django_connection.close()

        first_thread = threading.Thread(
            target=first_worker, name="first-resolve"
        )
        first_thread_ref["thread"] = first_thread
        second_thread = None
        probe = None
        try:
            first_thread.start()
            assert first_holds_lock.wait(5), (
                "first resolver never reached the history UPDATE"
            )

            second_thread = threading.Thread(
                target=second_worker, name="second-resolve"
            )
            second_thread.start()
            assert second_ready.wait(5), "second resolver never started"
            assert first_pid and second_pid

            params = dict(connection.get_connection_params())
            probe = psycopg.connect(**params, autocommit=True)
            probe_cur = probe.cursor()
            blockers = self._wait_for_exact_blocker(
                probe_cur,
                second_pid["pid"],
                first_pid["pid"],
                "second resolver",
            )
            assert blockers == [first_pid["pid"]]
        finally:
            release_first.set()
            if probe is not None:
                probe.close()
            first_thread.join(10)
            if second_thread is not None:
                second_thread.join(10)
            monkeypatch.setattr(QuerySet, "update", original_update)

        assert not first_thread.is_alive()
        assert second_thread is not None and not second_thread.is_alive()
        assert first_errors == []
        assert second_errors == []
        assert len(first_results) == 1
        assert len(second_results) == 1

        winner = first_results[0]
        loser = second_results[0]
        assert winner.status == RegistrationApplication.Status.SUBMITTED
        assert loser.status == RegistrationApplication.Status.SUBMITTED
        assert winner.submitted_at is not None

        fix_app.refresh_from_db()
        row = ApplicationCorrectionMessage.objects.get(application=fix_app)
        assert fix_app.status == RegistrationApplication.Status.SUBMITTED
        assert fix_app.submitted_at == winner.submitted_at
        assert fix_app.updated_at == winner.updated_at
        assert fix_app.submission_digest_sent_at is None
        # The blocked loser observed the committed winner and performed a true
        # no-op: no new timestamp, digest, history or audit row.
        assert loser.submitted_at == winner.submitted_at
        assert loser.updated_at == winner.updated_at
        assert loser.review_message == ""
        assert loser.reviewed_by_id is None
        assert loser.reviewed_at is None
        assert loser.submission_digest_sent_at is None
        assert row.resolved_at == winner.submitted_at
        assert row.resolution_source == "staff_manual"
        assert row.resolved_by_id == reviewer.id
        assert AuditEvent.objects.filter(action=str(RESOLVED_ACTION)).count() == 1
    @pytest.mark.django_db(transaction=True)
    def test_parent_submit_losing_to_staff_cannot_overwrite_final_state(
        self, fix_app, parent_account, reviewer, monkeypatch
    ):
        import psycopg
        from django.db import close_old_connections
        from django.db import connection as django_connection

        resolve = _require_service()
        submit = getattr(services, "submit_application")
        _message(fix_app, reviewer, ApplicationCorrectionMessage.Status.SENT)
        stale_parent_instance = RegistrationApplication.objects.get(pk=fix_app.pk)

        messages_updated = threading.Event()
        release_staff = threading.Event()
        staff_thread_ref: dict[str, threading.Thread] = {}
        staff_pid: dict[str, int] = {}
        parent_pid: dict[str, int] = {}
        parent_started = threading.Event()
        original_update = QuerySet.update

        def blocking_update(self, **kwargs):
            result = original_update(self, **kwargs)
            if (
                self.model is ApplicationCorrectionMessage
                and threading.current_thread()
                is staff_thread_ref.get("thread")
            ):
                messages_updated.set()
                if not release_staff.wait(15):
                    raise AssertionError("timed out releasing staff resolver")
            return result

        monkeypatch.setattr(QuerySet, "update", blocking_update)

        staff_errors: list[BaseException] = []
        parent_errors: list[BaseException] = []

        def staff_worker():
            close_old_connections()
            try:
                staff_pid["pid"] = self._backend_pid()
                resolve(fix_app, reviewer)
            except BaseException as exc:  # noqa: BLE001
                staff_errors.append(exc)
            finally:
                django_connection.close()

        def parent_worker():
            close_old_connections()
            try:
                parent_pid["pid"] = self._backend_pid()
                parent_started.set()
                submit(stale_parent_instance, parent_account)
            except BaseException as exc:  # noqa: BLE001
                parent_errors.append(exc)
            finally:
                django_connection.close()

        staff_thread = threading.Thread(target=staff_worker, name="staff-resolve")
        staff_thread_ref["thread"] = staff_thread
        parent_thread = None
        probe = None
        try:
            staff_thread.start()
            assert messages_updated.wait(5), (
                "staff did not reach message resolution"
            )

            parent_thread = threading.Thread(
                target=parent_worker, name="parent-submit"
            )
            parent_thread.start()
            assert parent_started.wait(5)
            assert staff_pid and parent_pid

            params = dict(connection.get_connection_params())
            probe = psycopg.connect(**params, autocommit=True)
            probe_cur = probe.cursor()
            blockers = self._wait_for_exact_blocker(
                probe_cur,
                parent_pid["pid"],
                staff_pid["pid"],
                "parent submit",
            )
            assert blockers == [staff_pid["pid"]]
        finally:
            release_staff.set()
            if probe is not None:
                probe.close()
            staff_thread.join(10)
            if parent_thread is not None:
                parent_thread.join(10)
            monkeypatch.setattr(QuerySet, "update", original_update)

        assert not staff_thread.is_alive()
        assert parent_thread is not None and not parent_thread.is_alive()
        assert staff_errors == []
        assert len(parent_errors) == 1
        assert isinstance(parent_errors[0], ValueError)
        assert "only draft or fix_requested" in str(parent_errors[0])

        fix_app.refresh_from_db()
        row = ApplicationCorrectionMessage.objects.get(application=fix_app)
        assert fix_app.status == RegistrationApplication.Status.SUBMITTED
        assert fix_app.review_message == ""
        assert fix_app.reviewed_by_id is None
        assert row.resolution_source == "staff_manual"
        assert row.resolved_by_id == reviewer.id
        assert AuditEvent.objects.filter(action=str(RESOLVED_ACTION)).count() == 1

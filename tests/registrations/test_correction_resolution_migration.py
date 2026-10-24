"""Task 2 — registrations 0014 correction-resolution provenance migration.

Forward: only rows already resolved at 0013 receive ``parent_resubmission``;
unresolved rows stay blank and no actor is invented. Reverse: removes only the
new provenance fields and preserves the pre-existing resolution timestamp and
all immutable content.
"""

from __future__ import annotations

import importlib

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

pytestmark = [pytest.mark.django_db(transaction=True)]

_APP_0013 = ("registrations", "0013_applicationcorrectionmessage")
_APP_0014 = ("registrations", "0014_applicationcorrectionmessage_resolution")


def _project_state(executor, node):
    executor.loader.build_graph()
    return executor.loader.project_state([node]).apps


@pytest.fixture
def at_0013():
    executor = MigrationExecutor(connection)
    executor.migrate([_APP_0013])
    apps = _project_state(executor, _APP_0013)
    try:
        yield apps
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def _seed(apps):
    Application = apps.get_model("registrations", "RegistrationApplication")
    Message = apps.get_model("registrations", "ApplicationCorrectionMessage")
    User = apps.get_model("auth", "User")

    actor = User.objects.create(username="historical-resolver")
    application = Application.objects.create(
        status="submitted", member_full_name="Vēsturisks Bērns"
    )
    old = timezone.now() - timezone.timedelta(days=30)
    sent_at = old - timezone.timedelta(days=1)
    resolved = Message.objects.create(
        application=application,
        actor=actor,
        created_at=old,
        sent_at=sent_at,
        resolved_at=old,
        subject="Vēsturisks temats",
        body="Vēsturisks saturs",
        review_message="Vēsturiska piezīme",
        status="sent",
    )
    unresolved = Message.objects.create(
        application=application,
        actor=actor,
        created_at=old,
        sent_at=sent_at,
        resolved_at=None,
        subject="Neatrisināts temats",
        body="Neatrisināts saturs",
        review_message="Neatrisināta piezīme",
        status="failed",
    )
    return {
        "application_pk": application.pk,
        "resolved_pk": resolved.pk,
        "unresolved_pk": unresolved.pk,
        "actor_pk": actor.pk,
        "old": old,
        "sent_at": sent_at,
        "resolved_created_at": resolved.created_at,
        "unresolved_created_at": unresolved.created_at,
    }


def test_forward_backfills_only_already_resolved_rows(at_0013):
    seeded = _seed(at_0013)

    executor = MigrationExecutor(connection)
    executor.migrate([_APP_0014])
    apps = _project_state(executor, _APP_0014)
    Message = apps.get_model("registrations", "ApplicationCorrectionMessage")

    resolved = Message.objects.get(pk=seeded["resolved_pk"])
    unresolved = Message.objects.get(pk=seeded["unresolved_pk"])

    assert resolved.resolution_source == "parent_resubmission"
    assert resolved.resolved_by_id is None
    assert resolved.resolved_at == seeded["old"]
    assert resolved.actor_id == seeded["actor_pk"]
    assert resolved.created_at == seeded["resolved_created_at"]
    assert resolved.sent_at == seeded["sent_at"]
    assert resolved.subject == "Vēsturisks temats"
    assert resolved.body == "Vēsturisks saturs"
    assert resolved.review_message == "Vēsturiska piezīme"
    assert resolved.status == "sent"

    assert unresolved.resolution_source == ""
    assert unresolved.resolved_by_id is None
    assert unresolved.resolved_at is None
    assert unresolved.actor_id == seeded["actor_pk"]
    assert unresolved.created_at == seeded["unresolved_created_at"]
    assert unresolved.sent_at == seeded["sent_at"]
    assert unresolved.subject == "Neatrisināts temats"
    assert unresolved.body == "Neatrisināts saturs"
    assert unresolved.review_message == "Neatrisināta piezīme"
    assert unresolved.status == "failed"


def test_reverse_removes_only_new_fields_and_keeps_old_data(at_0013):
    seeded = _seed(at_0013)

    executor = MigrationExecutor(connection)
    executor.migrate([_APP_0014])
    executor = MigrationExecutor(connection)
    executor.migrate([_APP_0013])
    apps = _project_state(executor, _APP_0013)
    Message = apps.get_model("registrations", "ApplicationCorrectionMessage")

    resolved = Message.objects.get(pk=seeded["resolved_pk"])
    unresolved = Message.objects.get(pk=seeded["unresolved_pk"])

    assert "resolution_source" not in {field.name for field in Message._meta.fields}
    assert "resolved_by" not in {field.name for field in Message._meta.fields}
    assert resolved.resolved_at == seeded["old"]
    assert resolved.actor_id == seeded["actor_pk"]
    assert resolved.created_at == seeded["resolved_created_at"]
    assert resolved.sent_at == seeded["sent_at"]
    assert resolved.subject == "Vēsturisks temats"
    assert resolved.body == "Vēsturisks saturs"
    assert resolved.status == "sent"
    assert unresolved.resolved_at is None
    assert unresolved.subject == "Neatrisināts temats"
    assert unresolved.body == "Neatrisināts saturs"


def test_core_audit_choice_exists():
    from apps.core.models import AuditEvent

    assert (
        AuditEvent.Action.APPLICATION_CORRECTIONS_RESOLVED
        == "application_corrections_resolved"
    )


def test_core_choice_migration_exists():
    importlib.import_module("apps.core.migrations.0013_alter_auditevent_action")

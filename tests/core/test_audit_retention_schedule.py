import pytest

pytestmark = pytest.mark.django_db


def test_audit_prune_schedule_row_exists():
    from django_q.models import Schedule

    sched = Schedule.objects.filter(name="audit-retention-prune").first()
    assert sched is not None
    assert sched.func == "apps.core.tasks.prune_audit_events"
    assert sched.schedule_type == Schedule.DAILY


def test_audit_prune_schedule_migration_is_idempotent():
    from importlib import import_module
    from django_q.models import Schedule

    migration = import_module("apps.core.migrations.0002_audit_retention_schedule")
    before = Schedule.objects.filter(name="audit-retention-prune").count()
    migration.create_schedule(None, None)
    after = Schedule.objects.filter(name="audit-retention-prune").count()
    assert before == 1
    assert after == 1

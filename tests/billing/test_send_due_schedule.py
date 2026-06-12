import pytest

pytestmark = pytest.mark.django_db


def test_send_due_schedule_row_exists():
    from django_q.models import Schedule

    sched = Schedule.objects.filter(name="billing-send-due-invoices").first()
    assert sched is not None
    assert sched.func == "apps.integrations.tasks.send_due_invoices"
    assert sched.schedule_type == Schedule.DAILY


def test_send_due_schedule_migration_is_idempotent():
    from importlib import import_module

    migration = import_module("apps.billing.migrations.0009_billing_send_due_schedule")
    from django_q.models import Schedule

    before = Schedule.objects.filter(name="billing-send-due-invoices").count()
    migration.create_schedule(None, None)
    after = Schedule.objects.filter(name="billing-send-due-invoices").count()
    assert before == 1
    assert after == 1

import pytest

pytestmark = pytest.mark.django_db


def test_payment_sync_schedule_row_exists():
    from django_q.models import Schedule

    sched = Schedule.objects.filter(name="billing-payment-sync").first()
    assert sched is not None
    assert sched.func == "apps.integrations.tasks.sync_billing_payments"
    assert sched.schedule_type == Schedule.DAILY


def test_schedule_migration_is_idempotent():
    """Re-running the create function must not create a duplicate row."""
    from importlib import import_module

    migration = import_module(
        "apps.billing.migrations.0005_billing_payment_sync_schedule"
    )
    from django_q.models import Schedule

    before = Schedule.objects.filter(name="billing-payment-sync").count()
    migration.create_schedule(None, None)
    after = Schedule.objects.filter(name="billing-payment-sync").count()
    assert before == 1
    assert after == 1

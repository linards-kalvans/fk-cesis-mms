"""Register the nightly billing payment-sync django-q2 Schedule (P6 Slice C)."""

import datetime

from django.conf import settings
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "billing-payment-sync"
SCHEDULE_FUNC = "apps.integrations.tasks.sync_billing_payments"


def _next_run():
    hour = getattr(settings, "BILLING_PAYMENT_SYNC_HOUR", 3)
    now = timezone.localtime()
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": SCHEDULE_FUNC,
            "schedule_type": Schedule.DAILY,
            "next_run": _next_run(),
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_payment_projection"),
        # Depend on django_q's latest migration so the fully-migrated Schedule
        # table exists before we insert a row.
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]

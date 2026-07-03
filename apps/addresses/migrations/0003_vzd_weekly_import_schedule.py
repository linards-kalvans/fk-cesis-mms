"""Register weekly VZD address import django-q2 Schedule."""

import datetime

from django.conf import settings
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "address-vzd-weekly-import"
SCHEDULE_FUNC = "apps.addresses.tasks.import_vzd_addresses_from_urls"


def _next_run():
    weekday = getattr(settings, "ADDRESS_IMPORT_WEEKDAY", 6)
    hour = getattr(settings, "ADDRESS_IMPORT_HOUR", 1)
    now = timezone.localtime()
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    days_ahead = (weekday - candidate.weekday()) % 7
    candidate += datetime.timedelta(days=days_ahead)
    if candidate <= now:
        candidate += datetime.timedelta(days=7)
    return candidate


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": SCHEDULE_FUNC,
            "schedule_type": Schedule.WEEKLY,
            "next_run": _next_run(),
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("addresses", "0002_addressapartment"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]

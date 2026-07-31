"""Add the P19 daily submitted-registration digest model + per-row flag, and seed the singleton + django-q Schedule."""

import datetime

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


SCHEDULE_NAME = "registrations-submission-digest"
SCHEDULE_FUNC = "apps.registrations.tasks.send_submitted_registration_digest"


def _next_run():
    """Next local Europe/Riga 08:00 (or the next day if already past 08:00)."""
    now = timezone.localtime()
    candidate = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def create_digest_defaults(apps, schema_editor):
    """Idempotently seed the singleton settings row and the django-q Schedule.

    Uses ``apps.get_model`` for the historical ``RegistrationSubmissionDigestSettings``
    so the same callback works with both the migration registry and the global
    app registry (the schedule tests rerun the callback manually).
    """
    from django_q.models import Schedule

    DigestSettings = apps.get_model(
        "registrations", "RegistrationSubmissionDigestSettings"
    )
    DigestSettings.objects.get_or_create(pk=1)
    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": SCHEDULE_FUNC,
            "schedule_type": Schedule.DAILY,
            "next_run": _next_run(),
        },
    )


def remove_digest_defaults(apps, schema_editor):
    """Reverse of ``create_digest_defaults`` — remove only the named Schedule."""
    from django_q.models import Schedule

    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("registrations", "0011_registrationapplication_referral_code"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="registrationapplication",
            name="submission_digest_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="RegistrationSubmissionDigestSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "last_successful_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Pēdējā veiksmīgā nosūtīšana",
                    ),
                ),
                (
                    "recipients",
                    models.ManyToManyField(
                        blank=True,
                        limit_choices_to=models.Q(
                            ("is_active", True), ("is_staff", True)
                        ),
                        related_name="registration_submission_digest_settings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Iesniegto pieteikumu kopsavilkuma iestatījumi",
                "verbose_name_plural": "Iesniegto pieteikumu kopsavilkuma iestatījumi",
            },
        ),
        migrations.RunPython(create_digest_defaults, remove_digest_defaults),
    ]

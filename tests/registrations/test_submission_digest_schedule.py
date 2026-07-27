"""Tests for P19 submission digest schedule migration and singleton seeding.

Covers:
- Singleton RegistrationSubmissionDigestSettings exists at pk=1 after migrations.
- Schedule row seeded with name='registrations-submission-digest', func pointing to the digest task, schedule_type=DAILY, next_run at local Europe/Riga 08:00.
- Idempotent seed: rerunning the migration seed callback leaves exactly one singleton row and one Schedule row.

The migration file is expected at ``apps.registrations.migrations.0012_submission_digest_settings``.
The migration must define a seed callback (expected name: ``create_digest_defaults``) that accepts ``(apps, schema_editor)`` per Django convention.
"""

import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Singleton model
# ---------------------------------------------------------------------------


class TestDigestSettingsSingleton:
    """Singleton RegistrationSubmissionDigestSettings must exist at pk=1."""

    def test_singleton_exists_at_pk_1(self):
        """Migration must create the singleton config row at pk=1."""
        from apps.registrations.models import RegistrationSubmissionDigestSettings

        obj = RegistrationSubmissionDigestSettings.objects.filter(pk=1).first()
        assert obj is not None

    def test_singleton_has_no_recipients_by_default(self):
        """Default singleton must have an empty recipients M2M."""
        from apps.registrations.models import RegistrationSubmissionDigestSettings

        obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        assert obj.recipients.count() == 0

    def test_singleton_last_successful_at_null_by_default(self):
        """Default singleton must have last_successful_at=None."""
        from apps.registrations.models import RegistrationSubmissionDigestSettings

        obj = RegistrationSubmissionDigestSettings.objects.get(pk=1)
        assert obj.last_successful_at is None


# ---------------------------------------------------------------------------
# Schedule row
# ---------------------------------------------------------------------------


class TestDigestScheduleRow:
    """Schedule row must be seeded with correct name/func/schedule_type."""

    def test_schedule_row_exists(self):
        """Migration must create the Schedule row."""
        from django_q.models import Schedule

        sched = Schedule.objects.filter(
            name="registrations-submission-digest"
        ).first()
        assert sched is not None

    def test_schedule_func(self):
        """Schedule func must point to the digest task."""
        from django_q.models import Schedule

        sched = Schedule.objects.get(name="registrations-submission-digest")
        assert sched.func == "apps.registrations.tasks.send_submitted_registration_digest"

    def test_schedule_type_daily(self):
        """Schedule type must be DAILY."""
        from django_q.models import Schedule

        sched = Schedule.objects.get(name="registrations-submission-digest")
        assert sched.schedule_type == Schedule.DAILY

    def test_schedule_next_run_at_0800_riga(self):
        """Initial next_run must be at local Europe/Riga 08:00."""
        from django_q.models import Schedule
        from django.utils import timezone

        sched = Schedule.objects.get(name="registrations-submission-digest")
        assert sched.next_run is not None
        riga_time = timezone.localtime(sched.next_run)
        assert riga_time.hour == 8
        assert riga_time.minute == 0


# ---------------------------------------------------------------------------
# Idempotent seed
# ---------------------------------------------------------------------------


class TestDigestSeedIdempotent:
    """Migration seed callback must be idempotent for both singleton and Schedule row."""

    def test_migration_seed_idempotent_for_singleton_and_schedule(self):
        """Rerunning the migration seed callback leaves exactly one singleton and one Schedule row."""
        from importlib import import_module

        from django.apps import apps as django_apps
        from django_q.models import Schedule

        from apps.registrations.models import RegistrationSubmissionDigestSettings

        # Baseline after migrations.
        assert RegistrationSubmissionDigestSettings.objects.count() == 1
        assert (
            Schedule.objects.filter(name="registrations-submission-digest").count() == 1
        )

        # Import the migration module and call its seed callback.
        migration = import_module(
            "apps.registrations.migrations.0012_submission_digest_settings"
        )
        # The migration is expected to define a callback named create_digest_defaults
        # that accepts (apps, schema_editor) per Django convention. Production migration
        # must use the passed registry for its historical settings model.
        seed_callback = getattr(migration, "create_digest_defaults", None)
        assert seed_callback is not None, (
            "Migration must define a seed callback (expected name: create_digest_defaults)"
        )

        # Rerun seed with the global app registry.
        seed_callback(django_apps, None)

        assert RegistrationSubmissionDigestSettings.objects.count() == 1
        assert (
            Schedule.objects.filter(name="registrations-submission-digest").count() == 1
        )

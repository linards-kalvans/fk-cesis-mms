"""Backfill an Agreement row for every approved Member that was created
before Slice C shipped and therefore lacks one.

Each backfilled row uses the source application's
``preferred_agreement_signing`` when set, falling back to ``electronic``
(the project's preferred direction). State is ``generated``; the
``generated_at`` timestamp is taken from the application's ``reviewed_at``
when available (closer to the real approval moment) and otherwise from
``timezone.now()``. The reverse migration drops only the backfilled rows
(identified by their absence of any lifecycle action past ``generated`` —
they would never have ``sent_at`` etc. set in a backfill scenario).
"""

from __future__ import annotations

from django.db import migrations
from django.utils import timezone


def backfill_agreements(apps, schema_editor):
    Member = apps.get_model("members", "Member")
    Agreement = apps.get_model("agreements", "Agreement")
    RegistrationApplication = apps.get_model("registrations", "RegistrationApplication")

    for member in Member.objects.all():
        if Agreement.objects.filter(member=member).exists():
            continue
        application = RegistrationApplication.objects.filter(
            approved_member=member
        ).first()
        signing_path = ""
        generated_at = None
        if application is not None:
            signing_path = application.preferred_agreement_signing or ""
            generated_at = application.reviewed_at
        if not signing_path:
            signing_path = "electronic"
        if generated_at is None:
            generated_at = timezone.now()
        Agreement.objects.create(
            member=member,
            is_current=True,
            state="generated",
            signing_path=signing_path,
            generated_at=generated_at,
        )


def remove_backfilled_agreements(apps, schema_editor):
    """Drop only the rows that look like backfills: state=generated, no
    sent/signed/voided timestamps, no external_id."""
    Agreement = apps.get_model("agreements", "Agreement")
    Agreement.objects.filter(
        state="generated",
        sent_at__isnull=True,
        signed_at__isnull=True,
        voided_at__isnull=True,
        external_id="",
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("agreements", "0001_initial"),
        ("members", "0002_kitsizeoption"),
        ("registrations", "0007_personal_data_consent"),
    ]

    operations = [
        migrations.RunPython(backfill_agreements, remove_backfilled_agreements),
    ]

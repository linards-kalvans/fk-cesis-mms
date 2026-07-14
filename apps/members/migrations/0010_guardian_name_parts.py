"""P13 — Guardian first_name + family_name columns, backfilled from full_name.

Adds two explicit name fields to the Guardian model. Migration 0010 is
non-destructive: the existing ``full_name`` column is kept as a temporary
mirror; existing rows are split by the same last-token rule used by
``apps.members.models.split_guardian_full_name``.

The forward operation is implemented as a plain AddField pair (so Django
detects the migration with makemigrations --check) plus a RunPython that
populates the new fields from the legacy mirror. The RunPython callable
``backfill_guardian_name_parts`` is importable by tests so the backfill
rule can be exercised without round-tripping the whole migration.
"""

from django.db import migrations, models


def _split_name(full_name):
    parts = str(full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def backfill_guardian_name_parts(apps, schema_editor):
    Guardian = apps.get_model("members", "Guardian")
    for guardian in Guardian.objects.all().only("pk", "full_name"):
        first_name, family_name = _split_name(guardian.full_name)
        guardian.first_name = first_name
        guardian.family_name = family_name
        guardian.save(update_fields=["first_name", "family_name"])


def backfill_guardian_name_parts_reverse(apps, schema_editor):
    """Reverse migration: drop the explicit fields (mirror stays for the
    forward path; the data was already in ``full_name`` before this slice)."""
    Guardian = apps.get_model("members", "Guardian")
    Guardian.objects.all().update(first_name="", family_name="")


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0009_p8_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="guardian",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="guardian",
            name="family_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.RunPython(
            backfill_guardian_name_parts,
            backfill_guardian_name_parts_reverse,
        ),
    ]

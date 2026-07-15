"""Add ``Agreement.agreement_number`` and backfill deterministic values.

Allocated format: ``FKC-{year}-{sequence:03d}`` (e.g. ``FKC-2026-001``). The
prefix is locked in this migration per the design; later overrides belong to
the application services, which read ``AGREEMENT_NUMBER_PREFIX`` from
settings. Sequence is per-calendar-year (Riga local time) so 2026's count
restarts at 1 on 2027-01-01.

Ordering rule: by ``generated_at`` ascending, then by ``id`` ascending — this
mirrors ``create_agreement_for_member`` so backfilled numbers match the
order in which the next ``create_agreement_for_member`` call would assign.
"""
from __future__ import annotations

from django.db import migrations, models
from django.utils import timezone


_PREFIX = "FKC"


def backfill_agreement_numbers(apps, schema_editor):
    Agreement = apps.get_model("agreements", "Agreement")
    qs = (
        Agreement.objects.filter(agreement_number__isnull=True)
        .order_by("generated_at", "id")
        .iterator()
    )
    sequence_by_year: dict[int, int] = {}
    for agreement in qs:
        year = timezone.localtime(agreement.generated_at).year
        sequence_by_year[year] = sequence_by_year.get(year, 0) + 1
        agreement.agreement_number = f"{_PREFIX}-{year}-{sequence_by_year[year]:03d}"
        agreement.save(update_fields=["agreement_number"])


class Migration(migrations.Migration):

    dependencies = [
        ("agreements", "0005_agreement_billing_plan_agreement_first_billing_month"),
    ]

    operations = [
        migrations.AddField(
            model_name="agreement",
            name="agreement_number",
            field=models.CharField(
                blank=True,
                max_length=32,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(
            backfill_agreement_numbers, migrations.RunPython.noop
        ),
    ]

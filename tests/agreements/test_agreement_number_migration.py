"""Tests for the 0006 agreement_number backfill migration."""

from __future__ import annotations

from datetime import datetime
from importlib import import_module

import pytest
from django.apps import apps
from django.utils import timezone

from apps.agreements.models import Agreement


pytestmark = pytest.mark.django_db


def _dt(year: int, month: int, day: int):
    return timezone.make_aware(datetime(year, month, day, 12, 0))


def test_backfill_agreement_numbers_orders_by_generated_at_then_id(
    agreement_member,
):
    module = import_module("apps.agreements.migrations.0006_agreement_number")
    newer = Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=_dt(2026, 2, 1),
        agreement_number=None,
    )
    older = Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=_dt(2026, 1, 1),
        agreement_number=None,
    )

    module.backfill_agreement_numbers(apps, None)

    older.refresh_from_db()
    newer.refresh_from_db()
    assert older.agreement_number == "FKC-2026-001"
    assert newer.agreement_number == "FKC-2026-002"


def test_backfill_restarts_sequence_each_year(agreement_member):
    module = import_module("apps.agreements.migrations.0006_agreement_number")
    first = Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=_dt(2026, 1, 1),
        agreement_number=None,
    )
    second = Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=_dt(2027, 1, 1),
        agreement_number=None,
    )

    module.backfill_agreement_numbers(apps, None)

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.agreement_number == "FKC-2026-001"
    assert second.agreement_number == "FKC-2027-001"

"""Tests for immutable agreement number allocation (FKC-YYYY-SEQ)."""

from __future__ import annotations

from datetime import datetime

import pytest
from django.test.utils import override_settings
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member


pytestmark = pytest.mark.django_db


def test_create_agreement_assigns_default_number(agreement_member):
    agreement = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
    )

    year = timezone.localtime(agreement.generated_at).year
    assert agreement.agreement_number == f"FKC-{year}-001"


def test_create_reuses_current_agreement_number(agreement_member):
    first = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
    )
    second = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.PAPER,
    )

    assert second.id == first.id
    assert second.agreement_number == first.agreement_number


@override_settings(AGREEMENT_NUMBER_PREFIX="TEST")
def test_create_uses_configured_prefix(agreement_member):
    agreement = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
    )

    year = timezone.localtime(agreement.generated_at).year
    assert agreement.agreement_number == f"TEST-{year}-001"


def test_sequence_uses_next_number_in_same_year(agreement_member, monkeypatch):
    generated_at = timezone.make_aware(datetime(2026, 3, 1, 12, 0))
    monkeypatch.setattr(
        "apps.agreements.services.timezone.now", lambda: generated_at
    )
    existing = Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=timezone.make_aware(datetime(2026, 2, 1, 12, 0)),
        agreement_number="FKC-2026-998",
    )
    assert existing.agreement_number == "FKC-2026-998"

    agreement = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
    )

    assert agreement.agreement_number == "FKC-2026-999"


def test_sequence_expands_after_999(agreement_member, monkeypatch):
    generated_at = timezone.make_aware(datetime(2026, 3, 1, 12, 0))
    monkeypatch.setattr(
        "apps.agreements.services.timezone.now", lambda: generated_at
    )
    Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=timezone.make_aware(datetime(2026, 2, 1, 12, 0)),
        agreement_number="FKC-2026-999",
    )

    agreement = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
    )

    assert agreement.agreement_number == "FKC-2026-1000"


def test_number_assignment_retries_after_duplicate_sequence(
    agreement_member, monkeypatch
):
    generated_at = timezone.make_aware(datetime(2026, 3, 1, 12, 0))
    monkeypatch.setattr(
        "apps.agreements.services.timezone.now", lambda: generated_at
    )
    Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        generated_at=timezone.make_aware(datetime(2026, 2, 1, 12, 0)),
        agreement_number="FKC-2026-001",
    )
    sequences = iter([1, 2])
    monkeypatch.setattr(
        "apps.agreements.services._next_agreement_sequence_for_year",
        lambda year: next(sequences),
    )

    agreement = create_agreement_for_member(
        agreement_member,
        Agreement.SigningPath.ELECTRONIC,
    )

    assert agreement.agreement_number == "FKC-2026-002"

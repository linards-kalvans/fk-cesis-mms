"""Tests for the 0002 backfill data migration."""

from __future__ import annotations

import pytest
from django.utils import timezone


pytestmark = pytest.mark.django_db


def test_backfill_creates_agreement_for_member_without_one(agreement_member):
    """The forward migration creates a generated electronic agreement for an
    approved member that lacks one."""
    from importlib import import_module

    module = import_module(
        "apps.agreements.migrations.0002_backfill_agreements_for_approved_members"
    )

    from django.apps import apps

    # Sanity: ensure no agreement yet
    from apps.agreements.models import Agreement

    assert not Agreement.objects.filter(member=agreement_member).exists()

    # Call the forward op directly (RunPython callable). It expects the
    # historical apps registry, but the live registry works here because
    # the schema is identical to head.
    module.backfill_agreements(apps, None)

    agreement = Agreement.objects.get(member=agreement_member)
    assert agreement.state == "generated"
    assert agreement.signing_path == "electronic"
    assert agreement.is_current is True
    assert agreement.generated_at is not None


def test_backfill_does_not_duplicate_existing_agreement(
    agreement_member, actor
):
    """Idempotency: running the backfill twice doesn't create a second row."""
    from importlib import import_module

    module = import_module(
        "apps.agreements.migrations.0002_backfill_agreements_for_approved_members"
    )
    from django.apps import apps

    from apps.agreements.models import Agreement
    from apps.agreements.services import create_agreement_for_member

    existing = create_agreement_for_member(
        agreement_member, Agreement.SigningPath.PAPER
    )
    module.backfill_agreements(apps, None)
    module.backfill_agreements(apps, None)

    assert Agreement.objects.filter(member=agreement_member).count() == 1
    only = Agreement.objects.get(member=agreement_member)
    assert only.id == existing.id
    assert only.signing_path == "paper"  # untouched


def test_backfill_honours_application_preferred_signing_path(db):
    """When the source application has a paper preference, the backfilled
    agreement reflects it."""
    from importlib import import_module

    module = import_module(
        "apps.agreements.migrations.0002_backfill_agreements_for_approved_members"
    )
    from django.apps import apps as app_registry
    from django.contrib.auth.models import User

    from apps.agreements.models import Agreement
    from apps.members.models import Guardian, Member
    from apps.registrations.models import RegistrationApplication

    # Build a pre-Slice-C scenario by hand: an approved member linked to an
    # application whose preferred_agreement_signing="paper", but no agreement.
    guardian = Guardian.objects.create(full_name="Guardian X")
    member = Member.objects.create(full_name="Member X", guardian=guardian)
    staff = User.objects.create_user(username="staff", is_staff=True)
    RegistrationApplication.objects.create(
        guardian_email="g@example.test",
        preferred_agreement_signing="paper",
        status="approved",
        approved_member=member,
        reviewed_by=staff,
        reviewed_at=timezone.now(),
    )

    module.backfill_agreements(app_registry, None)

    agreement = Agreement.objects.get(member=member)
    assert agreement.signing_path == "paper"

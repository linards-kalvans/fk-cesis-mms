"""Tests for the training_group argument extension of approve_application."""

from __future__ import annotations

import pytest

from apps.members.models import TrainingGroup
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def training_group_a(db):
    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def inactive_group(db):
    return TrainingGroup.objects.create(name="U10 Arhīvs", is_active=False)


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


def test_approve_without_group_creates_member_with_no_group(submitted_application, reviewer):
    """Regression: existing call site signature still works."""
    app = approve_application(submitted_application, reviewer)
    assert app.approved_member is not None
    assert app.approved_member.training_group is None


def test_approve_with_active_group_assigns_member(submitted_application, reviewer, training_group_a):
    app = approve_application(submitted_application, reviewer, training_group=training_group_a)
    assert app.approved_member is not None
    assert app.approved_member.training_group_id == training_group_a.id


def test_approve_with_inactive_group_raises_value_error(submitted_application, reviewer, inactive_group):
    with pytest.raises(ValueError, match="inactive"):
        approve_application(submitted_application, reviewer, training_group=inactive_group)

    # And no Member was created — application stayed submitted.
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED
    assert submitted_application.approved_member_id is None


def test_idempotent_reapprove_ignores_different_group(submitted_application, reviewer, training_group_a):
    other_group = TrainingGroup.objects.create(name="U10 C", is_active=True)
    first = approve_application(submitted_application, reviewer, training_group=training_group_a)
    assigned_member_id = first.approved_member_id
    assigned_group_id = first.approved_member.training_group_id

    # Second call with a different group must not mutate.
    second = approve_application(submitted_application, reviewer, training_group=other_group)
    assert second.approved_member_id == assigned_member_id
    second.approved_member.refresh_from_db()
    assert second.approved_member.training_group_id == assigned_group_id


# --- Agreement creation on approval (P5 Slice C) ---


def test_approve_creates_agreement_with_default_electronic_when_no_preference(
    submitted_application, reviewer
):
    from apps.agreements.models import Agreement
    from apps.agreements.services import get_current_agreement

    submitted_application.preferred_agreement_signing = ""
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    approve_application(submitted_application, reviewer)
    submitted_application.refresh_from_db()
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement is not None
    assert agreement.state == Agreement.State.GENERATED
    assert agreement.signing_path == Agreement.SigningPath.ELECTRONIC


def test_approve_creates_agreement_honouring_application_paper_preference(
    submitted_application, reviewer
):
    from apps.agreements.models import Agreement
    from apps.agreements.services import get_current_agreement

    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    approve_application(submitted_application, reviewer)
    submitted_application.refresh_from_db()
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement is not None
    assert agreement.signing_path == Agreement.SigningPath.PAPER


def test_idempotent_reapprove_does_not_create_second_agreement(
    submitted_application, reviewer
):
    from apps.agreements.models import Agreement

    approve_application(submitted_application, reviewer)
    # Second call hits the idempotency early-return; agreement count stays at 1.
    approve_application(submitted_application, reviewer)
    submitted_application.refresh_from_db()
    assert Agreement.objects.filter(
        member=submitted_application.approved_member
    ).count() == 1

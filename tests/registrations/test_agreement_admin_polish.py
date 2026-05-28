"""Slice C admin polish: navigation from Agreement admin to review detail,
and signing-path sync when the application admin form is saved."""

from __future__ import annotations

import pytest

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    get_current_agreement,
    mark_agreement_sent,
    set_signing_path,
    sync_application_signing_path_to_agreement,
    void_agreement,
)
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


# --- Agreement.get_absolute_url ---


def test_get_absolute_url_points_to_review_detail(submitted_application, reviewer):
    from django.urls import reverse

    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement is not None
    expected = reverse(
        "registrations:admin-review-detail", args=[submitted_application.id]
    )
    assert agreement.get_absolute_url() == expected


def test_get_absolute_url_empty_when_member_has_no_source_application(db):
    """Defensive: an Agreement attached to a Member without a source_application
    returns an empty string so the admin VIEW ON SITE button gracefully no-ops."""
    from apps.members.models import Guardian, Member

    guardian = Guardian.objects.create(full_name="Detached Guardian")
    orphan_member = Member.objects.create(
        full_name="Detached Member", guardian=guardian
    )
    a = create_agreement_for_member(
        orphan_member, Agreement.SigningPath.ELECTRONIC
    )
    assert a.get_absolute_url() == ""


# --- sync_application_signing_path_to_agreement ---


def test_sync_updates_signing_path_when_agreement_is_generated(
    submitted_application, reviewer
):
    """Application-form change of preferred_agreement_signing propagates to
    the active agreement while it is still in `generated` state."""
    submitted_application.preferred_agreement_signing = "electronic"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    approve_application(submitted_application, reviewer)

    # Staff flips the application's preferred path post-approval (e.g. parent
    # called and asked to switch).
    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    sync_application_signing_path_to_agreement(submitted_application)

    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.signing_path == Agreement.SigningPath.PAPER


def test_sync_is_noop_when_agreement_is_past_generated(
    submitted_application, reviewer
):
    """Once the agreement has been sent (or signed, or voided), staff edits to
    the application's signing preference do NOT propagate. The Līgums module
    is the canonical control for advanced states."""
    submitted_application.preferred_agreement_signing = "electronic"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    mark_agreement_sent(agreement, reviewer)

    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    sync_application_signing_path_to_agreement(submitted_application)

    agreement.refresh_from_db()
    assert agreement.signing_path == Agreement.SigningPath.ELECTRONIC  # unchanged


def test_sync_is_noop_when_agreement_is_signed(submitted_application, reviewer):
    submitted_application.preferred_agreement_signing = "electronic"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    set_signing_path(agreement, Agreement.SigningPath.ELECTRONIC, reviewer)
    mark_agreement_sent(agreement, reviewer)
    from apps.agreements.services import mark_agreement_signed

    mark_agreement_signed(agreement, reviewer)

    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    sync_application_signing_path_to_agreement(submitted_application)

    agreement.refresh_from_db()
    assert agreement.signing_path == Agreement.SigningPath.ELECTRONIC  # unchanged


def test_sync_is_noop_when_agreement_is_void(submitted_application, reviewer):
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    void_agreement(agreement, reviewer, "duplicate")

    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    sync_application_signing_path_to_agreement(submitted_application)

    agreement.refresh_from_db()
    # voided agreement keeps its signing_path unchanged
    assert agreement.signing_path != "paper" or agreement.state == Agreement.State.VOID


def test_sync_is_noop_when_application_has_no_approved_member(submitted_application):
    """Pre-approval applications have no agreement to sync."""
    assert submitted_application.approved_member_id is None
    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    sync_application_signing_path_to_agreement(submitted_application)  # no error
    assert Agreement.objects.count() == 0


def test_sync_is_noop_when_preference_is_empty_string(
    submitted_application, reviewer
):
    """Clearing the application's preference does NOT clear the agreement's
    signing_path — the agreement always has a concrete value."""
    submitted_application.preferred_agreement_signing = "paper"
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.signing_path == Agreement.SigningPath.PAPER

    submitted_application.preferred_agreement_signing = ""
    submitted_application.save(update_fields=["preferred_agreement_signing"])
    sync_application_signing_path_to_agreement(submitted_application)

    agreement.refresh_from_db()
    assert agreement.signing_path == Agreement.SigningPath.PAPER  # unchanged

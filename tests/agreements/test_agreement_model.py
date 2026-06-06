"""Tests for apps.agreements.models.Agreement."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.agreements.models import Agreement


pytestmark = pytest.mark.django_db


def test_agreement_defaults_are_generated_electronic_current(agreement_member):
    a = Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
    )
    assert a.state == Agreement.State.GENERATED
    assert a.signing_path == Agreement.SigningPath.ELECTRONIC
    assert a.is_current is True
    assert a.generated_at is not None
    assert a.sent_at is None
    assert a.signed_at is None
    assert a.voided_at is None


def test_state_choices_match_spec():
    values = {value for value, _label in Agreement.State.choices}
    assert values == {"generated", "sent", "signed", "void"}


def test_signing_path_choices_match_spec():
    values = {value for value, _label in Agreement.SigningPath.choices}
    assert values == {"electronic", "paper"}


def test_unique_current_constraint_blocks_second_current_for_same_member(
    agreement_member,
):
    Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Agreement.objects.create(
                member=agreement_member,
                generated_at=timezone.now(),
            )


def test_archived_agreement_allows_new_current(agreement_member):
    archived = Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
        is_current=False,
    )
    fresh = Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
    )
    assert archived.is_current is False
    assert fresh.is_current is True


def test_member_cascade_delete_removes_all_agreements(agreement_member):
    Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
        is_current=False,
    )
    Agreement.objects.create(
        member=agreement_member,
        generated_at=timezone.now(),
        is_current=True,
    )
    agreement_member.delete()
    assert Agreement.objects.count() == 0


@pytest.mark.django_db
def test_agreement_has_external_error_code_field(agreement_member):
    from apps.agreements.models import Agreement
    from django.utils import timezone

    a = Agreement.objects.create(
        member=agreement_member, generated_at=timezone.now()
    )
    assert a.external_error_code == ""
    a.external_error_code = "auth_failed"
    a.save(update_fields=["external_error_code"])
    a.refresh_from_db()
    assert a.external_error_code == "auth_failed"

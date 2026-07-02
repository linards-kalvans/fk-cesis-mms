"""P8: Member lifecycle model tests — status + discontinuation fields."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_member_defaults_active(make_guardian, parent_account):
    """A new Member must default to active with no discontinuation fields set."""
    from apps.members.models import Member

    member = Member.objects.create(full_name="Bērns", guardian=make_guardian(account=parent_account))

    assert hasattr(member, "status")
    assert member.status == Member.Status.ACTIVE
    assert member.discontinued_effective_date is None
    assert member.discontinuation_reason == ""
    assert member.discontinued_at is None


def test_member_status_has_discontinued_choice():
    from apps.members.models import Member

    assert hasattr(Member.Status, "ACTIVE")
    assert Member.Status.ACTIVE == "active"
    assert hasattr(Member.Status, "DISCONTINUED")
    assert Member.Status.DISCONTINUED == "discontinued"


def test_member_can_be_set_to_discontinued(make_guardian, parent_account):
    """Member can transition to discontinued status via ORM."""
    from django.utils import timezone
    from apps.members.models import Member

    member = Member.objects.create(full_name="Bērns", guardian=make_guardian(account=parent_account))
    now = timezone.now()

    member.status = Member.Status.DISCONTINUED
    member.discontinued_effective_date = "2026-09-01"
    member.discontinuation_reason = "Pārcelšanās"
    member.discontinued_at = now
    member.save()

    member.refresh_from_db()
    assert member.status == Member.Status.DISCONTINUED
    assert str(member.discontinued_effective_date) == "2026-09-01"
    assert member.discontinuation_reason == "Pārcelšanās"

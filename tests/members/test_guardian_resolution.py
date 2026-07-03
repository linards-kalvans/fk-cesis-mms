"""Slice A — canonical Guardian 1:1 with ParentAccount."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian

pytestmark = pytest.mark.django_db


def test_guardian_links_one_to_one_to_parent_account():
    account = ParentAccount.objects.create(email="link@example.com")
    guardian = Guardian.objects.create(parent_account=account)
    # Reverse accessor is singular (OneToOne).
    assert account.guardian == guardian


def test_parent_account_can_have_only_one_guardian():
    account = ParentAccount.objects.create(email="dup@example.com")
    Guardian.objects.create(parent_account=account)
    with pytest.raises(IntegrityError):
        Guardian.objects.create(parent_account=account)


def test_resolve_guardian_is_idempotent_and_reads_account_email():
    from apps.members.services import resolve_guardian_for_account

    account = ParentAccount.objects.create(email="resolve@example.com")
    first = resolve_guardian_for_account(account)
    second = resolve_guardian_for_account(account)

    assert first.pk == second.pk  # same row, not a duplicate
    assert first.parent_account_id == account.id
    assert first.email == "resolve@example.com"  # proxy reads through the account
    assert Guardian.objects.filter(parent_account=account).count() == 1

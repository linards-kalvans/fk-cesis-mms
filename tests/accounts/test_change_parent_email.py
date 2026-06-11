"""Slice C — admin-initiated verified email change service."""

import pytest

from apps.accounts.models import ParentAccount
from apps.accounts.services import change_parent_email
from apps.members.services import resolve_guardian_for_account

pytestmark = pytest.mark.django_db


def test_changes_email_and_syncs_guardian_mirror():
    account = ParentAccount.objects.create(email="old@example.com")
    guardian = resolve_guardian_for_account(account)  # mirror == old@example.com
    assert guardian.email == "old@example.com"

    change_parent_email(account, "new@example.com")

    account.refresh_from_db()
    guardian.refresh_from_db()
    assert account.email == "new@example.com"
    assert guardian.email == "new@example.com"


def test_normalizes_new_email():
    account = ParentAccount.objects.create(email="old@example.com")
    change_parent_email(account, "  New@Example.COM ")
    account.refresh_from_db()
    assert account.email == "new@example.com"


def test_noop_when_unchanged():
    account = ParentAccount.objects.create(email="same@example.com")
    change_parent_email(account, "SAME@example.com")  # case-insensitive no-op, must not raise
    account.refresh_from_db()
    assert account.email == "same@example.com"


def test_rejects_email_owned_by_another_account():
    ParentAccount.objects.create(email="taken@example.com")
    account = ParentAccount.objects.create(email="mine@example.com")
    with pytest.raises(ValueError):
        change_parent_email(account, "TAKEN@example.com")
    account.refresh_from_db()
    assert account.email == "mine@example.com"


def test_safe_when_account_has_no_guardian():
    account = ParentAccount.objects.create(email="noguardian@example.com")
    change_parent_email(account, "moved@example.com")  # must not raise
    account.refresh_from_db()
    assert account.email == "moved@example.com"


def test_db_level_collision_converted_to_valueerror(monkeypatch):
    from django.db.models.query import QuerySet

    ParentAccount.objects.create(email="taken@example.com")
    account = ParentAccount.objects.create(email="mine@example.com")

    # Simulate the TOCTOU race: pre-check sees the email as free, but the DB
    # unique constraint still rejects the save.
    monkeypatch.setattr(QuerySet, "exists", lambda self: False)

    with pytest.raises(ValueError):
        change_parent_email(account, "taken@example.com")

"""Slice B1 — guardian-read accessors prefer the canonical Guardian / ParentAccount,
falling back to the denormalized columns (which still exist in B1)."""

from __future__ import annotations

import pytest

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def test_accessors_prefer_guardian_when_profile_populated():
    account = ParentAccount.objects.create(email="acct@example.com")
    guardian = Guardian.objects.create(
        parent_account=account,
        full_name="Guardian Row",
        personal_id="010101-22222",
        phone="+37120000000",
        address="Guardian Address 1",
        email="acct@example.com",
    )
    app = RegistrationApplication.objects.create(
        parent_account=account,
        guardian=guardian,
        guardian_email="stale@example.com",
        guardian_full_name="Stale Column Name",
        guardian_personal_id="999999-99999",
        guardian_phone="+37100000000",
        guardian_declared_address="Stale Column Address",
    )
    assert app.guardian_name == "Guardian Row"
    assert app.guardian_pid == "010101-22222"
    assert app.guardian_contact_phone == "+37120000000"
    assert app.guardian_address == "Guardian Address 1"
    assert app.guardian_contact_email == "acct@example.com"


def test_accessors_fall_back_to_columns_when_guardian_profile_empty():
    app = RegistrationApplication.objects.create(
        guardian_email="col@example.com",
        guardian_full_name="Column Name",
        guardian_personal_id="010101-33333",
        guardian_phone="+37111111111",
        guardian_declared_address="Column Address",
    )
    assert app.guardian_name == "Column Name"
    assert app.guardian_pid == "010101-33333"
    assert app.guardian_contact_phone == "+37111111111"
    assert app.guardian_address == "Column Address"
    assert app.guardian_contact_email == "col@example.com"


def test_email_accessor_prefers_parent_account_over_column():
    account = ParentAccount.objects.create(email="verified@example.com")
    app = RegistrationApplication.objects.create(
        parent_account=account, guardian_email="old-column@example.com"
    )
    assert app.guardian_contact_email == "verified@example.com"

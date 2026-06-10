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


def test_linked_guardian_is_source_even_when_field_empty():
    """A linked Guardian is the source of truth: an empty Guardian field must NOT
    fall back to a stale column (so clearing a field propagates)."""
    account = ParentAccount.objects.create(email="empty@example.com")
    guardian = Guardian.objects.create(
        parent_account=account, full_name="Has Name", personal_id="", phone="", address=""
    )
    app = RegistrationApplication.objects.create(
        parent_account=account, guardian=guardian, guardian_email="x@example.com",
        guardian_personal_id="111111-11111", guardian_phone="+37100000000",
        guardian_declared_address="Stale Col Addr",
    )
    assert app.guardian_name == "Has Name"
    assert app.guardian_pid == ""          # empty Guardian value wins, not the column
    assert app.guardian_contact_phone == ""
    assert app.guardian_address == ""


def test_draft_save_populates_the_guardian_profile():
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="draft@example.com")
    app = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Anna Bērziņa",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000001",
            "guardian_declared_address": "Rīga, Brīvības 1",
        },
        files={},
        verified_account=account,
    )
    guardian = Guardian.objects.get(parent_account=account)
    assert guardian.full_name == "Anna Bērziņa"
    assert guardian.personal_id == "010101-12345"
    assert guardian.phone == "+37120000001"
    assert guardian.address == "Rīga, Brīvības 1"


def test_editing_guardian_on_second_app_propagates_to_first():
    """Propagation: two apps share one Guardian; editing guardian data on the
    second is visible through the first app's accessors."""
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="prop@example.com")
    app1 = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Old Name",
              "guardian_phone": "+37120000000", "guardian_declared_address": "Addr 1",
              "guardian_personal_id": "010101-11111"},
        files={}, verified_account=account,
    )
    create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "New Name",
              "guardian_phone": "+37120000000", "guardian_declared_address": "Addr 1",
              "guardian_personal_id": "010101-11111"},
        files={}, verified_account=account,
    )
    app1.refresh_from_db()
    assert app1.guardian_name == "New Name"


def test_admin_review_detail_renders_guardian_via_read_through(client, django_user_model):
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="render@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Render Name",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Render Addr"},
        files={}, verified_account=account,
    )
    # Simulate a later shared-Guardian edit that the column on THIS app never saw.
    guardian = Guardian.objects.get(parent_account=account)
    guardian.full_name = "Edited Shared Name"
    guardian.save(update_fields=["full_name"])

    staff = django_user_model.objects.create_user(
        username="staff-rt", password="pw", is_staff=True, is_superuser=True
    )
    client.force_login(staff)
    resp = client.get(f"/admin/review/applications/{app.id}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Edited Shared Name" in body          # read-through wins
    assert "Render Name" not in body             # stale column value not shown


def test_prefill_uses_guardian_profile_for_returning_parent():
    from apps.registrations.services import create_or_update_draft, get_application_prefill

    account = ParentAccount.objects.create(email="prefill@example.com")
    create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Prefill Guardian",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Prefill Addr"},
        files={}, verified_account=account,
    )
    # Edit the shared Guardian directly; prefill must reflect it, not a stale column.
    guardian = Guardian.objects.get(parent_account=account)
    guardian.full_name = "Updated Guardian"
    guardian.save(update_fields=["full_name"])

    prefill = get_application_prefill(account)
    assert prefill["guardian_full_name"] == "Updated Guardian"

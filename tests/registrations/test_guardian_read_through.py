"""Slice B1 — guardian-read accessors prefer the canonical Guardian / ParentAccount."""

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
    )
    app = RegistrationApplication.objects.create(
        parent_account=account,
        guardian=guardian,
    )
    assert app.guardian_name == "Guardian Row"
    assert app.guardian_pid == "010101-22222"
    assert app.guardian_contact_phone == "+37120000000"
    assert app.guardian_address == "Guardian Address 1"
    assert app.guardian_contact_email == "acct@example.com"


def test_email_accessor_prefers_parent_account_over_column():
    account = ParentAccount.objects.create(email="verified@example.com")
    app = RegistrationApplication.objects.create(parent_account=account)
    assert app.guardian_contact_email == "verified@example.com"


def test_linked_guardian_is_source_even_when_field_empty():
    """A linked Guardian is the source of truth: an empty Guardian field must NOT
    fall back to a stale column (so clearing a field propagates)."""
    account = ParentAccount.objects.create(email="empty@example.com")
    guardian = Guardian.objects.create(
        parent_account=account, full_name="Has Name", personal_id="", phone="", address=""
    )
    app = RegistrationApplication.objects.create(
        parent_account=account, guardian=guardian,
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


def test_admin_change_page_renders_guardian_via_read_through(client, django_user_model):
    from django.urls import reverse

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
    resp = client.get(
        reverse("admin:registrations_registrationapplication_change", args=[app.id])
    )
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


def test_make_guardian_helper_links_a_populated_guardian(make_guardian):
    account = ParentAccount.objects.create(email="helper@example.com")
    guardian = make_guardian(account, full_name="Helper Name", personal_id="010101-12345",
                             phone="+37120000000", address="Helper Addr")
    assert guardian.parent_account_id == account.id
    assert guardian.full_name == "Helper Name"
    assert guardian.email == "helper@example.com"  # mirrored from the account
    app = RegistrationApplication.objects.create(parent_account=account, guardian=guardian)
    assert app.guardian_name == "Helper Name"


def test_draft_save_writes_guardian_not_columns(make_guardian):
    """create_or_update_draft populates the Guardian from form data."""
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="nocol@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Form Name",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Form Addr"},
        files={}, verified_account=account,
    )
    guardian = app.guardian
    assert guardian.full_name == "Form Name"
    assert guardian.personal_id == "010101-12345"
    assert guardian.phone == "+37120000000"
    assert guardian.address == "Form Addr"


def test_str_uses_account_email_not_column():
    account = ParentAccount.objects.create(email="str@example.com")
    app = RegistrationApplication.objects.create(parent_account=account, member_full_name="Kid")
    assert str(app) == "str@example.com — Kid"


def test_accessors_return_empty_when_unlinked():
    app = RegistrationApplication.objects.create(claimed_email="anon@example.com")
    assert app.guardian_name == ""
    assert app.guardian_contact_email == ""


def test_update_existing_draft_repopulates_guardian_profile():
    """create_or_update_draft on an existing draft updates the linked Guardian
    from the new form data (the guardian_id-guarded write)."""
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="update@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "First",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "A"},
        files={}, verified_account=account,
    )
    create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Second",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "A"},
        files={}, application=app, verified_account=account,
    )
    app.refresh_from_db()
    assert app.guardian_name == "Second"

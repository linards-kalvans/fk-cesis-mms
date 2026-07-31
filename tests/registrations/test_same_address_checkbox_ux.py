"""P1 — "Adrese tāda pati kā vecāka" checkbox UX — RED tests.

Covers acceptance criteria for the live browser-side address-sync behavior:
  1. When checkbox is checked, member address field becomes disabled.
  2. When checkbox is checked, member address field value is populated from
     guardian declared address field.
  3. While checkbox remains checked, changing guardian declared address
     updates member address live.
  4. When checkbox is unchecked again, member address field becomes enabled.
  5. When checkbox is unchecked again, previous manual member address is
     restored.
  6. Behavior must work on both new_registration.html and edit_registration.html.
  7. Server-side same-address save logic remains source of truth; this task is
     only about live browser UX.

Because Django response tests cannot execute browser JS, these tests assert
the required DOM hooks, data attributes, and script markers that the
implementation MUST provide to support the live address-sync behavior.
Each test is named after the acceptance criterion it verifies.
"""

import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY  # noqa: F401
from apps.accounts.services import issue_magic_link

pytestmark = pytest.mark.django_db


# ===========================================================================
# Helpers
# ===========================================================================


def _login_via_magic_link(client, account):
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _create_and_login(email="sameaddr@example.com"):
    """Create a ParentAccount, log in, return (client, account)."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37111111111",
    )
    client = Client()
    _login_via_magic_link(client, acct)
    return client, acct


def _create_draft(
    client,
    account,
    email="sameaddr@example.com",
    guardian_address="Riga 1",
    member_address="",
    same_address=False,
):
    from apps.registrations.services import create_or_update_draft

    return create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_first_name": "SameAddr",
            "guardian_family_name": "Guardian",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": guardian_address,
            "member_full_name": "SameAddr Child",
            "member_personal_id": "010125-12345",
            "member_birth_date": "2025-01-01",
            "member_actual_address": member_address,
            "member_same_address_as_guardian": same_address,
        },
        files={},
        verified_account=account,
    )


# ===========================================================================
# AC1 — new_registration.html: checkbox DOM hooks present
# ===========================================================================


class TestNewRegistrationCheckboxHooks:
    """new_registration.html must contain the checkbox with required DOM hooks."""

    def setup_method(self):
        self.client, self.account = _create_and_login("sameaddr-new@example.com")

    def test_checkbox_has_id_and_label(self):
        """Checkbox must have id='id_member_same_address_as_guardian' and label text."""
        resp = self.client.get("/applications/new/", follow=True)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'id="id_member_same_address_as_guardian"' in content
        assert "Adrese tāda pati kā vecāka" in content

    def test_member_address_field_has_data_attribute(self):
        """Member address input must have data attribute linking to checkbox."""
        resp = self.client.get("/applications/new/", follow=True)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'data-sync-address-for="id_member_same_address_as_guardian"' in content, (
            "Member address field must have data-sync-address-for attribute "
            "linking it to the 'id_member_same_address_as_guardian' checkbox."
        )

    def test_hidden_previous_address_input_present(self):
        """Hidden input must exist to store previous manual address value."""
        resp = self.client.get("/applications/new/", follow=True)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'id="member_actual_address_previous"' in content, (
            "Hidden input #member_actual_address_previous must exist to "
            "store the previous manual member address when checkbox is checked."
        )

    def test_initialization_script_present(self):
        """Initialization script must be present in the page to wire up sync."""
        resp = self.client.get("/applications/new/", follow=True)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "SameAddressSync" in content or "same-address-sync" in content, (
            "Page must include the same-address-sync initialization script "
            "(look for 'SameAddressSync' or 'same-address-sync' marker)."
        )


# ===========================================================================
# AC2 — edit_registration.html: checkbox DOM hooks present
# ===========================================================================


class TestEditRegistrationCheckboxHooks:
    """edit_registration.html must contain the checkbox with required DOM hooks."""

    def setup_method(self):
        self.client, self.account = _create_and_login("sameaddr-edit@example.com")
        self.app = _create_draft(
            self.client,
            self.account,
            email="sameaddr-edit@example.com",
            guardian_address="Riga 2",
            member_address="Riga 3",
            same_address=False,
        )

    def test_checkbox_has_id_and_label(self):
        """Checkbox must have id='id_member_same_address_as_guardian' and label text."""
        resp = self.client.get(f"/applications/{self.app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'id="id_member_same_address_as_guardian"' in content
        assert "Adrese tāda pati kā vecāka" in content

    def test_member_address_field_has_data_attribute(self):
        """Member address input must have data attribute linking to checkbox."""
        resp = self.client.get(f"/applications/{self.app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'data-sync-address-for="id_member_same_address_as_guardian"' in content, (
            "Member address field must have data-sync-address-for attribute "
            "linking it to the 'id_member_same_address_as_guardian' checkbox."
        )

    def test_hidden_previous_address_input_present(self):
        """Hidden input must exist to store previous manual address value."""
        resp = self.client.get(f"/applications/{self.app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'id="member_actual_address_previous"' in content, (
            "Hidden input #member_actual_address_previous must exist to "
            "store the previous manual member address when checkbox is checked."
        )

    def test_initialization_script_present(self):
        """Initialization script must be present in the page to wire up sync."""
        resp = self.client.get(f"/applications/{self.app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "SameAddressSync" in content or "same-address-sync" in content, (
            "Page must include the same-address-sync initialization script "
            "(look for 'SameAddressSync' or 'same-address-sync' marker)."
        )


# ===========================================================================
# AC3 — edit_registration.html: checkbox checked state with pre-filled address
# ===========================================================================


class TestEditRegistrationCheckboxCheckedState:
    """When checkbox is checked, member address field must show guardian address."""

    def setup_method(self):
        self.client, self.account = _create_and_login(
            "sameaddr-checked@example.com"
        )
        self.app = _create_draft(
            self.client,
            self.account,
            email="sameaddr-checked@example.com",
            guardian_address="Daugavgrivas iela 1",
            member_address="",
            same_address=True,
        )

    def test_checkbox_rendered_checked(self):
        """Checkbox must render as checked when same_address is True."""
        resp = self.client.get(f"/applications/{self.app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'id="id_member_same_address_as_guardian"' in content
        assert 'checked' in content or 'checked="checked"' in content, (
            "Checkbox must be rendered as checked when "
            "member_same_address_as_guardian is True."
        )

    def test_member_address_field_has_guardian_address_value(self):
        """Member address input must be pre-filled with guardian declared address."""
        resp = self.client.get(f"/applications/{self.app.pk}/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Daugavgrivas iela 1" in content, (
            "Member address input must be pre-filled with the guardian "
            "declared address value when checkbox is checked."
        )


# ===========================================================================
# AC4 — DOM attribute contract: data attributes enable JS-driven behavior
# ===========================================================================


class TestDOMAttributeContract:
    """Both templates must expose the full set of data attributes that the
    SameAddressSync script requires to drive the live browser behavior:

      - Checkbox:  id="id_member_same_address_as_guardian"
      - Address:   id="id_member_actual_address",
                   data-sync-address-for="id_member_same_address_as_guardian"
      - Hidden:    id="member_actual_address_previous"
      - Script:    initialization block referencing these IDs
    """

    def _collect_dom_hooks(self, content):
        """Extract the set of DOM hook identifiers from rendered HTML."""
        hooks = set()
        for attr in (
            'id="id_member_same_address_as_guardian"',
            'id="id_member_actual_address"',
            'data-sync-address-for="id_member_same_address_as_guardian"',
            'id="member_actual_address_previous"',
        ):
            if attr in content:
                hooks.add(attr)
        if "SameAddressSync" in content or "same-address-sync" in content:
            hooks.add("init-script")
        return hooks

    def test_new_registration_has_all_dom_hooks(self):
        """new_registration.html must expose all required DOM hooks."""
        client, _account = _create_and_login("sameaddr-contract@example.com")
        resp = client.get("/applications/new/", follow=True)
        assert resp.status_code == 200
        hooks = self._collect_dom_hooks(resp.content.decode())
        expected = {
            'id="id_member_same_address_as_guardian"',
            'id="id_member_actual_address"',
            'data-sync-address-for="id_member_same_address_as_guardian"',
            'id="member_actual_address_previous"',
            "init-script",
        }
        missing = expected - hooks
        assert not missing, (
            f"new_registration.html missing DOM hooks: {missing}. "
            "The SameAddressSync script requires all of these."
        )

    def test_edit_registration_has_all_dom_hooks(self):
        """edit_registration.html must expose all required DOM hooks."""
        client, account = _create_and_login("domhooks@example.com")
        app = _create_draft(
            client,
            account,
            email="domhooks@example.com",
            guardian_address="Riga 5",
            member_address="",
            same_address=False,
        )
        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200
        hooks = self._collect_dom_hooks(resp.content.decode())
        expected = {
            'id="id_member_same_address_as_guardian"',
            'id="id_member_actual_address"',
            'data-sync-address-for="id_member_same_address_as_guardian"',
            'id="member_actual_address_previous"',
            "init-script",
        }
        missing = expected - hooks
        assert not missing, (
            f"edit_registration.html missing DOM hooks: {missing}. "
            "The SameAddressSync script requires all of these."
        )

"""P1 — Verified guardian chooser / dashboard behavior tests.

Covers the verified-parent layer behavior described in
docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md:

- Chooser/dashboard lives on ``/portal/``, not ``/register/``.
- Verified guardian session is established by setting
  ``PARENT_ACCOUNT_SESSION_KEY`` directly in the test client session.
- With an existing draft on ``/portal/``: continue-draft action visible,
  start-new-registration action visible, registrations list visible.
- Without an existing draft on ``/portal/``: start-new-registration visible
  as primary path, registrations list area still visible.
- Existing guardian starting a new registration uses ``/applications/new/``.
- On ``/applications/new/``: guardian fields are prefilled from the verified
  account / latest application; member/child fields are NOT prefilled.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.contrib.sessions.backends.db import SessionStore

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_verified(client: Client, account: ParentAccount) -> None:
    """Establish verified guardian session by injecting the session cookie.

    Creates a fresh session store, writes the parent-account key, persists
    to the DB, and sets the session cookie on the test client directly.
    This avoids magic-link login and works reliably with Django's test
    client even when no response has been received yet.
    """
    session = SessionStore()
    session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
    session.save()
    client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key


def _make_child_identity_file(name: str = "id.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


# ===========================================================================
# 7a. Existing guardian WITH draft: continue draft primary
# ===========================================================================


class TestExistingGuardianWithDraft:
    """When a verified guardian has an existing draft, continue draft is primary."""

    def test_continue_draft_link_present_on_portal(self):
        """The portal page must show a continue-draft action when a draft exists."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="withdraft@example.com",
            phone="+3711111111",
        )
        create_or_update_draft(
            data={
                "guardian_email": "withdraft@example.com",
                "guardian_full_name": "WithDraft Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child WithDraft",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/portal/")
        assert resp.status_code == 200, (
            f"Portal returned {resp.status_code}, expected 200."
        )
        content = resp.content.decode()
        assert "Turpināt" in content or "turpināt" in content.lower() or "continue" in content.lower(), (
            "Portal must show a continue-draft action when a draft exists."
        )

    def test_start_new_registration_available_with_draft(self):
        """The portal must also offer start-new-registration when a draft exists."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="withdraft2@example.com",
            phone="+37133333333",
        )
        create_or_update_draft(
            data={
                "guardian_email": "withdraft2@example.com",
                "guardian_full_name": "WithDraft2 Guardian",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37144444444",
                "guardian_address": "Riga 3",
                "child_full_name": "Child WithDraft2",
                "child_personal_id": "010125-33333",
                "child_birth_date": "2025-02-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "jauns" in content.lower() or "new" in content.lower() or "sākt" in content.lower() or "start" in content.lower(), (
            "Portal must offer start-new-registration when a draft exists."
        )

    def test_registrations_list_visible_with_draft(self):
        """The registrations list must be visible when a draft exists."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="withdraft3@example.com",
            phone="+37155555555",
        )
        create_or_update_draft(
            data={
                "guardian_email": "withdraft3@example.com",
                "guardian_full_name": "WithDraft3 Guardian",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37166666666",
                "guardian_address": "Riga 5",
                "child_full_name": "Child WithDraft3",
                "child_personal_id": "010125-55555",
                "child_birth_date": "2025-03-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "WithDraft3" in content or "withdraft3" in content, (
            "Portal must show the existing application in the registrations list."
        )


# ===========================================================================
# 7b. Existing guardian WITHOUT draft: start new registration primary
# ===========================================================================


class TestExistingGuardianWithoutDraft:
    """When a verified guardian has no draft, start-new-registration is primary."""

    def test_start_new_registration_primary_without_draft(self):
        """The portal must show start-new-registration as primary when no draft exists."""
        acct = ParentAccount.objects.create(
            email="nodraft@example.com",
            phone="+37177777777",
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/portal/")
        assert resp.status_code == 200, (
            f"Portal returned {resp.status_code}, expected 200."
        )
        content = resp.content.decode()
        assert "jauns" in content.lower() or "new" in content.lower() or "sākt" in content.lower() or "start" in content.lower(), (
            "Portal must offer start-new-registration when no draft exists."
        )

    def test_registrations_list_visible_without_draft(self):
        """The registrations list area must be visible even when no drafts exist."""
        acct = ParentAccount.objects.create(
            email="nodraft2@example.com",
            phone="+37188888888",
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/portal/")
        assert resp.status_code == 200, (
            f"Portal returned {resp.status_code}, expected 200."
        )
        # The portal page must render (200) even with zero applications.
        # The template uses an {% empty %} branch, so the page body exists.
        assert b"Nav pieteikumu" in resp.content or b"pieteikumu" in resp.content.lower(), (
            "Portal must render the registrations list area even when empty."
        )


# ===========================================================================
# 8. Existing guardian starting new registration: guardian-only prefill
# ===========================================================================


class TestExistingGuardianPrefill:
    """Existing guardian starting a new registration must get guardian-only prefill.

    Member/child fields must NOT be prefilled from a previous application.
    """

    def test_guardian_fields_prefilled_on_new_registration(self):
        """Guardian fields must be prefilled from the verified account / latest application."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="prefillguardian@example.com",
            phone="+37199999999",
        )
        create_or_update_draft(
            data={
                "guardian_email": "prefillguardian@example.com",
                "guardian_full_name": "Prefill Guardian",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37100000000",
                "guardian_address": "Riga 99",
                "child_full_name": "Child Previous",
                "child_personal_id": "010125-99999",
                "child_birth_date": "2025-04-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/applications/new/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Prefill Guardian" in content, (
            "Guardian full_name must be prefilled from existing application."
        )

    def test_guardian_email_prefilled_from_account(self):
        """Guardian email must be prefilled from the verified account."""
        acct = ParentAccount.objects.create(
            email="emailprefill@example.com",
            phone="+37134343434",
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/applications/new/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "emailprefill@example.com" in content, (
            "Guardian email must be prefilled from the verified account."
        )

    def test_guardian_phone_prefilled_from_account(self):
        """Guardian phone must be prefilled from the verified account."""
        acct = ParentAccount.objects.create(
            email="phoneprefill@example.com",
            phone="+37150505050",
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/applications/new/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "+37150505050" in content, (
            "Guardian phone must be prefilled from the verified account."
        )

    def test_member_child_fields_not_prefilled(self):
        """Member/child fields must NOT be prefilled when starting a new registration."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="nomemberprefill@example.com",
            phone="+37112121212",
        )
        create_or_update_draft(
            data={
                "guardian_email": "nomemberprefill@example.com",
                "guardian_full_name": "NoMemberPrefill Guardian",
                "guardian_personal_id": "010101-12121",
                "guardian_phone": "+37123232323",
                "guardian_address": "Riga 12",
                "child_full_name": "Previous Child",
                "child_personal_id": "010125-12121",
                "child_birth_date": "2025-05-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/applications/new/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Previous Child" not in content, (
            "Child full_name must NOT be prefilled for new registration."
        )
        assert "010125-12121" not in content, (
            "Child personal ID must NOT be prefilled for new registration."
        )

    def test_no_continue_draft_action_on_new_registration_page(self):
        """The new registration page must not show continue-draft actions."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="nocdnprefill@example.com",
            phone="+37120202020",
        )
        create_or_update_draft(
            data={
                "guardian_email": "nocdnprefill@example.com",
                "guardian_full_name": "NoCDN Prefill Guardian",
                "guardian_personal_id": "010101-20202",
                "guardian_phone": "+37121212121",
                "guardian_address": "Riga 20",
                "child_full_name": "Previous Child CDN",
                "child_personal_id": "010125-20202",
                "child_birth_date": "2025-06-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/applications/new/")
        assert resp.status_code == 200
        content = resp.content.decode()
        # The new-registration form must not include continue-draft navigation.
        # We assert the form action area does not contain a draft-continue link.
        assert "Turpināt melnrakstu" not in content and "turpināt melnrakstu" not in content.lower(), (
            "New registration page must not show continue-draft action."
        )


# ===========================================================================
# 7a-b. Portal is the chooser, not /register/
# ===========================================================================


class TestPortalIsChooserNotRegister:
    """The chooser/dashboard lives on /portal/, not /register/."""

    def test_register_page_is_not_the_chooser(self):
        """The /register/ page must NOT serve as the chooser/dashboard for
        verified guardians. Chooser behavior belongs on /portal/.
        """
        acct = ParentAccount.objects.create(
            email="registernotchooser@example.com",
            phone="+37130303030",
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.get("/register/")
        # /register/ should either redirect to portal or present the email-entry
        # gate, NOT a chooser with continue-draft / start-new actions.
        assert resp.status_code in (302, 200)
        if resp.status_code == 200:
            content = resp.content.decode()
            # Must NOT show the chooser actions
            assert "Turpināt" not in content or "jauns" not in content or "sākt" not in content, (
                "/register/ must not serve as the chooser dashboard for verified guardians."
            )

    def test_portal_redirects_unverified_to_login(self):
        """Unauthenticated users must be redirected when accessing /portal/."""
        client = Client()
        resp = client.get("/portal/", follow=False)
        assert resp.status_code == 302, (
            f"Unauthenticated /portal/ must redirect, got {resp.status_code}."
        )
        assert "/register/" in resp.url, (
            "Redirect must go to /register/ for unverified portal access."
        )


# ===========================================================================
# 7a-b. Continue draft action follows to edit page
# ===========================================================================


class TestContinueDraftAction:
    """Clicking continue-draft must redirect to the edit page for that draft."""

    def test_continue_draft_redirects_to_edit_page(self):
        """POST continue-draft must redirect to the application edit URL."""
        from apps.registrations.services import create_or_update_draft

        acct = ParentAccount.objects.create(
            email="continuedraft@example.com",
            phone="+37145454545",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "continuedraft@example.com",
                "guardian_full_name": "Continue Draft Guardian",
                "guardian_personal_id": "010101-45454",
                "guardian_phone": "+37156565656",
                "guardian_address": "Riga 45",
                "child_full_name": "Child ContinueDraft",
                "child_personal_id": "010125-45454",
                "child_birth_date": "2025-06-01",
            },
            files={},
            verified_account=acct,
        )

        client = Client()
        _login_verified(client, acct)

        resp = client.post(
            "/portal/",
            data={"action": "continue_draft"},
            follow=False,
        )
        assert resp.status_code == 302, (
            f"Continue-draft POST returned {resp.status_code}, expected 302."
        )
        assert f"/applications/{app.pk}/edit/" in resp.url, (
            f"Redirect must go to the draft's edit page. Got: {resp.url}"
        )

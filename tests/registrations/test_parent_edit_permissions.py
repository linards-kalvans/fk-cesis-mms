"""Parent edit permissions — P1-aligned regression tests.

Covers:
- Owner can open draft edit page.
- Other parent cannot open draft edit page.
- Submitted application is not editable by owner.
- Portal lists only current parent applications.
- fix_requested applications are editable by owning parent.
- rejected applications are not editable; portal shows reject message, no edit CTA.
- cross-browser / cross-account protection.
"""

import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# View: start_registration — /register/
# ---------------------------------------------------------------------------

class TestStartRegistrationView:
    """Start page is the guardian-email entry route.

    P1: /register/ is NOT a full application form — it accepts only an email
    and issues a one-time code for verification.
    """

    def test_start_page_accessible_without_session(self):
        client = Client()
        resp = client.get("/register/")
        assert resp.status_code == 200

    def test_start_page_accessible_without_login(self):
        """Even if no ParentAccount exists, the page loads."""
        client = Client()
        resp = client.get("/register/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# View: edit_registration — /applications/<id>/edit/
# ---------------------------------------------------------------------------

class TestEditRegistrationView:
    """Edit page should enforce ownership and draft status."""

    def test_owner_can_open_draft_edit_page(self, verified_client, draft_application):
        resp = verified_client.get(f"/applications/{draft_application.pk}/edit/")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/applications/{draft_application.pk}/")

    def test_summary_route_redirects_to_canonical_workspace(
        self, verified_client, draft_application
    ):
        """Summary route must redirect (302) to canonical workspace."""
        resp = verified_client.get(f"/applications/{draft_application.pk}/summary/")
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/applications/{draft_application.pk}/")

    def test_other_parent_cannot_open_draft_edit_page(
        self, other_verified_client, draft_application
    ):
        """A different logged-in parent gets blocked."""
        # draft_application is owned by parent_account; other_verified_client
        # is logged in as other_parent_account — distinct ownership.
        resp = other_verified_client.get(f"/applications/{draft_application.pk}/edit/")
        assert resp.status_code == 404

    def test_submitted_application_not_editable_by_owner(
        self, verified_client, submitted_application
    ):
        """Once submitted, owner cannot edit."""
        resp = verified_client.get(
            f"/applications/{submitted_application.pk}/edit/"
        )
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(
            f"/applications/{submitted_application.pk}/"
        )


# ---------------------------------------------------------------------------
# View: submit_registration — /applications/<id>/submit/
# ---------------------------------------------------------------------------

class TestSubmitRegistrationView:
    """Submit view should enforce ownership and required documents."""

    def test_owner_can_submit_with_documents(
        self, verified_client, draft_with_documents, submit_payload
    ):
        app = draft_with_documents
        resp = verified_client.post(
            f"/applications/{app.pk}/submit/",
            data=submit_payload,
        )
        # Successful submit redirects to parent portal
        assert resp.status_code == 302
        # Verify status changed
        app.refresh_from_db()
        assert app.status == "submitted"

    def test_owner_cannot_submit_without_documents(
        self, verified_client, draft_application
    ):
        app = draft_application
        resp = verified_client.post(
            f"/applications/{app.pk}/submit/",
            data={
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_email": "",
                "guardian_phone": "",
                "guardian_declared_address": "",
                "member_full_name": "",
                "member_personal_id": "",
                "member_birth_date": "",
                "member_same_address_as_guardian": True,
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# View: parent_portal — /portal/
# ---------------------------------------------------------------------------

class TestParentPortalView:
    """Portal should list only the current parent's applications."""

    def test_portal_lists_only_current_parent_applications(
        self, parent_account, other_parent_account
    ):
        """Two parents, two apps — each portal shows only own."""
        from apps.registrations.services import create_or_update_draft

        # Parent A creates draft
        create_or_update_draft(
            data={
                "guardian_email": parent_account.email,
                "guardian_full_name": "Parent A",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37199999999",
                "guardian_declared_address": "Riga 88",
                "member_full_name": "Child A",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-04-01",
            },
            files={},
            verified_account=parent_account,
        )

        # Parent B creates draft
        create_or_update_draft(
            data={
                "guardian_email": other_parent_account.email,
                "guardian_full_name": "Parent B",
                "guardian_personal_id": "010101-00000",
                "guardian_phone": "+37112121212",
                "guardian_declared_address": "Riga 99",
                "member_full_name": "Child B",
                "member_personal_id": "010125-00000",
                "member_birth_date": "2025-05-01",
            },
            files={},
            verified_account=other_parent_account,
        )

        # Login as Parent A and check portal shows only A's data
        client_a = Client()
        raw = issue_magic_link(parent_account)
        client_a.get(f"/accounts/verify/{raw}/")
        resp = client_a.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Parent A" in content or "parent@example.com" in content
        assert "Parent B" not in content and "other@example.com" not in content

    def test_portal_redirects_anonymous(self):
        client = Client()
        resp = client.get("/portal/")
        assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Resumed parent — continue own draft after magic-link login
# ---------------------------------------------------------------------------

class TestResumedParentCanContinueDraft:
    """After magic-link login, parent should see and continue their draft."""

    def test_resumed_parent_can_continue_own_draft(self):
        """Parent creates draft without login, requests magic link, verifies, then continues."""
        # Step 1: Create draft without login (anonymous) — no ParentAccount created
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "resume@example.com",
                "guardian_full_name": "Resume Parent",
                "guardian_personal_id": "010101-21212",
                "guardian_phone": "+37132323232",
                "guardian_declared_address": "Riga 21",
                "member_full_name": "Child Resume",
                "member_personal_id": "010125-21212",
                "member_birth_date": "2025-06-01",
            },
            files={},
        )

        # Step 2: No ParentAccount exists yet — draft is unlinked
        assert app.parent_account is None
        assert app.claimed_email == "resume@example.com"

        # Step 3: Request magic link for claimed email (no ParentAccount needed)
        client = Client()
        resp = client.post(
            "/accounts/request-magic-link/",
            {"email": "resume@example.com"},
        )
        assert resp.status_code == 200, (
            f"Magic-link request failed: {resp.status_code}"
        )

        # Step 4: Extract verify URL and consume it
        content = resp.content.decode()
        import re

        verify_urls = re.findall(r"/accounts/verify/[^\s'\"<>]+", content)
        assert verify_urls, "No verify URL found in magic-link response"
        verify_url = verify_urls[-1]
        if not verify_url.endswith("/"):
            verify_url += "/"
        verify_resp = client.get(verify_url)
        assert verify_resp.status_code == 302  # redirects to portal

        # Step 5: After verification, draft is linked to new ParentAccount
        # and should be editable
        app.refresh_from_db()
        assert app.parent_account is not None

        # Step 6: Open workspace — should work (session has verified parent)
        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200

    def test_resumed_parent_cannot_edit_other_parent_draft(self):
        """Resumed parent should NOT be able to edit someone else's draft."""
        from apps.registrations.services import create_or_update_draft

        # Parent A creates draft
        app_a = create_or_update_draft(
            data={
                "guardian_email": "otherdraft@example.com",
                "guardian_full_name": "Other Draft",
                "guardian_personal_id": "010101-31313",
                "guardian_phone": "+37142424242",
                "guardian_declared_address": "Riga 31",
                "member_full_name": "Child Other",
                "member_personal_id": "010125-31313",
                "member_birth_date": "2025-07-01",
            },
            files={},
        )

        # Parent B logs in
        acct_b = ParentAccount.objects.create(
            email="blogin@example.com",
            phone="+37152525252",
        )
        client = Client()
        raw = issue_magic_link(acct_b)
        client.get(f"/accounts/verify/{raw}/")

        # Parent B tries to edit Parent A's draft
        resp = client.get(f"/applications/{app_a.pk}/edit/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: submitted application portal card must show 'Skatīt pieteikumu'
# ---------------------------------------------------------------------------


class TestSubmittedApplicationPortalCard:
    """Submitted application card must show 'Skatīt pieteikumu', not 'Turpināt'."""

    def test_portal_card_shows_skatit_ieteikumu_for_submitted(
        self, verified_client, submitted_application
    ):
        """Submitted application must show 'Skatīt pieteikumu' link on portal."""
        resp = verified_client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Skatīt pieteikumu" in content, (
            "Submitted application portal card must show 'Skatīt pieteikumu'."
        )

    def test_portal_card_no_turpat_for_submitted(
        self, verified_client, submitted_application
    ):
        """Submitted application must NOT show 'Turpināt' link on portal."""
        resp = verified_client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Turpināt" not in content, (
            "Submitted application portal card must not show 'Turpināt'."
        )


# ---------------------------------------------------------------------------
# Parent identity gate: same-browser vs cross-browser draft access
# ---------------------------------------------------------------------------

class TestSameBrowserVsCrossBrowser:
    """Draft continuity must work in same browser but not across browsers."""

    def test_cross_browser_cannot_access_draft(self):
        """A fresh browser session cannot access a draft saved in another session."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft

        create_or_update_draft(
            data={
                "guardian_email": "crosscross@example.com",
                "guardian_full_name": "Same Browser Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga, Brivibas 1",
                "member_full_name": "Child SB",
                "member_personal_id": "010125-12345",
                "member_birth_date": "2025-01-01",
            },
            files={},
        )

        # Fresh client = different browser
        other_browser = Client()
        app = RegistrationApplication.objects.get(
            claimed_email="crosscross@example.com"
        )
        resp = other_browser.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404, (
            "Cross-browser must not access draft by application ID."
        )

    def test_cross_browser_cannot_access_via_portal(self):
        """Cross-browser cannot see another browser's drafts in portal."""
        from apps.registrations.services import create_or_update_draft

        create_or_update_draft(
            data={
                "guardian_email": "crossportal@example.com",
                "guardian_full_name": "Same Browser Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga, Brivibas 1",
                "member_full_name": "Child SB",
                "member_personal_id": "010125-12345",
                "member_birth_date": "2025-01-01",
            },
            files={},
        )

        other_browser = Client()
        resp = other_browser.get("/portal/")
        # Should redirect to login
        assert resp.status_code == 302, (
            "Unauthenticated cross-browser must be redirected from portal."
        )


# ---------------------------------------------------------------------------
# fix_requested — parent editability and portal visibility
# ---------------------------------------------------------------------------


class TestFixRequestedEditability:
    """fix_requested applications must be editable by the owning parent."""

    def test_fix_requested_is_editable_by_owning_parent(
        self, verified_client, fix_requested_application, parent_account
    ):
        """fix_requested application must be editable by owning parent."""
        from apps.registrations.services import can_edit_application

        assert can_edit_application(fix_requested_application, parent_account) is True, (
            "fix_requested application must be editable by owning parent."
        )

    def test_fix_requested_edit_page_accessible(
        self, verified_client, fix_requested_application
    ):
        """fix_requested application workspace must load (200) for owning parent."""
        resp = verified_client.get(f"/applications/{fix_requested_application.pk}/")
        assert resp.status_code == 200, (
            f"Expected 200 for fix_requested workspace, got {resp.status_code}."
        )

    def test_fix_requested_not_editable_by_other_parent(
        self, fix_requested_application, other_parent_account
    ):
        """fix_requested application must not be editable by another parent."""
        from apps.registrations.services import can_edit_application

        assert can_edit_application(fix_requested_application, other_parent_account) is False, (
            "fix_requested application must not be editable by other parent."
        )


class TestParentPortalFixRequestedVisibility:
    """Portal must show fix message and edit CTA for fix_requested."""

    def test_portal_shows_fix_message_and_edit_cta(
        self, verified_client, fix_requested_application
    ):
        """Portal must display review message and edit link for fix_requested."""
        resp = verified_client.get("/portal/")
        assert resp.status_code == 200, (
            f"Expected 200 on portal, got {resp.status_code}."
        )
        content = resp.content.decode()
        assert "Please correct the personal ID format." in content, (
            "Portal must show the fix_requested review message."
        )
        # Must show an edit/continue link
        has_edit_link = (
            "edit" in content.lower()
            or "turpinat" in content.lower()
            or "labot" in content.lower()
            or f"/applications/{fix_requested_application.pk}/" in content
        )
        assert has_edit_link, (
            "Portal must show an edit/continue link for fix_requested application."
        )


class TestFixRequestedDraftSavePreservesStatus:
    """Saving a fix_requested application through parent workspace must keep fix_requested status.

    Regression: create_or_update_draft() unconditionally sets status=DRAFT,
    silently reverting fix_requested to draft.
    """

    def test_save_draft_on_fix_requested_keeps_fix_requested_status(
        self, verified_client, fix_requested_application, parent_account, submit_payload
    ):
        """POST save-draft on a fix_requested application must keep status fix_requested."""
        from apps.registrations.models import RegistrationApplication

        app = fix_requested_application
        initial_status = app.status
        assert initial_status == RegistrationApplication.Status.FIX_REQUESTED

        resp = verified_client.post(
            f"/applications/{app.pk}/",
            {
                **submit_payload,
                "guardian_full_name": "Updated Guardian",
                "guardian_email": parent_account.email,
                "member_kit_size_shirt": app.member_kit_size_shirt_id,
                "member_kit_size_shorts": app.member_kit_size_shorts_id,
                "submit_action": "save_draft",
            },
        )

        assert resp.status_code == 302
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.FIX_REQUESTED, (
            f"Expected fix_requested after save-draft, got {app.status}."
        )
        assert app.guardian_full_name == "Updated Guardian", (
            "Edited field must be persisted after save-draft."
        )
        assert app.review_message == "Please correct the personal ID format.", (
            "review_message must be preserved after save-draft."
        )


class TestParentPortalRejectedVisibility:
    """Portal must show reject message but no edit CTA for rejected."""

    def test_portal_shows_reject_message_no_edit_cta(
        self, verified_client, rejected_application
    ):
        """Portal must display reject message and no edit link."""
        app = rejected_application
        resp = verified_client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Application does not meet requirements." in content, (
            "Portal must show the reject review message."
        )
        # Must NOT show an edit link
        has_edit_link = f"/applications/{app.pk}/edit/" in content
        assert not has_edit_link, (
            "Portal must not show an edit link for rejected application."
        )

    def test_rejected_application_not_editable_by_parent(
        self, rejected_application, parent_account
    ):
        """rejected application must not be editable by the owning parent."""
        from apps.registrations.services import can_edit_application

        assert can_edit_application(rejected_application, parent_account) is False, (
            "rejected application must not be editable."
        )

    def test_rejected_edit_page_redirects_to_workspace(
        self, verified_client, rejected_application
    ):
        """rejected application edit page must redirect to workspace for owning parent."""
        app = rejected_application
        resp = verified_client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 302, (
            f"Expected 302 for rejected edit page, got {resp.status_code}."
        )
        assert resp.headers["Location"].endswith(f"/applications/{app.pk}/")

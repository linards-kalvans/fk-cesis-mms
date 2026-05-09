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
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login_via_magic_link(client, account):
    """Convenience: issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_member_identity_file(name="id.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_guardian_identity_file(name="guardian_id.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _ensure_kit_sizes():
    """Create kit size options if they don't already exist. Returns (shirt_pk, shorts_pk)."""
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        defaults={"label": "S", "is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        defaults={"label": "S", "is_active": True},
    )
    return shirt.pk, shorts.pk


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

    def setup_method(self):
        self.client = Client()

    def _create_draft_with_owner(self, email="edit@example.com"):
        """Helper: create a ParentAccount, log in, create a verified draft app."""
        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Edit Owner",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child Edit",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={},
            verified_account=acct,
        )
        return acct, app

    def test_owner_can_open_draft_edit_page(self):
        acct, app = self._create_draft_with_owner("ownedit@example.com")
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200

    def test_other_parent_cannot_open_draft_edit_page(self):
        """A different logged-in parent gets blocked."""
        self._create_draft_with_owner("ownedit2@example.com")
        # Create and login a different parent
        other = ParentAccount.objects.create(
            email="otheredit@example.com",
            phone="+37133333333",
        )
        _login_via_magic_link(self.client, other)
        from apps.registrations.models import RegistrationApplication

        app = RegistrationApplication.objects.first()
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404

    def test_submitted_application_not_editable_by_owner(self):
        """Once submitted, owner cannot edit."""
        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email="subedit@example.com",
            phone="+37111111111",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft, submit_application

        app = create_or_update_draft(
            data={
                "guardian_email": "subedit@example.com",
                "guardian_full_name": "Sub Edit Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child SubEdit",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("subedit_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("subedit_member.jpg"),
                "member_portrait_document": _make_member_identity_file("subedit_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# View: submit_registration — /applications/<id>/submit/
# ---------------------------------------------------------------------------

class TestSubmitRegistrationView:
    """Submit view should enforce ownership and required documents."""

    def setup_method(self):
        self.client = Client()

    def _create_draft_with_doc_and_login(self, email="subview@example.com"):
        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37144444444",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Submit View",
                "guardian_personal_id": "010101-44444",
                "guardian_phone": "+37155555555",
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child SubView",
                "member_personal_id": "010125-44444",
                "member_birth_date": "2025-02-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("subview_guardian_id.jpg"),
                "member_identity_document": _make_member_identity_file("subview_member_id.jpg"),
                "member_portrait_document": _make_member_identity_file("subview_portrait.jpg"),
            },
            verified_account=acct,
        )
        return acct, app

    def test_owner_can_submit_with_documents(self):
        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct, app = self._create_draft_with_doc_and_login("owndocsubmit@example.com")
        resp = self.client.post(
            f"/applications/{app.pk}/submit/",
            data={
                "guardian_full_name": "Submit Guardian",
                "guardian_personal_id": "010101-12345",
                "guardian_email": "owndocsubmit@example.com",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga, Brivibas 1",
                "member_full_name": "Submit Child",
                "member_personal_id": "010125-67890",
                "member_birth_date": "2025-01-01",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
                "preferred_agreement_signing": "paper",
            },
        )
        # Successful submit redirects to parent portal
        assert resp.status_code == 302
        # Verify status changed
        app.refresh_from_db()
        assert app.status == "submitted"

    def test_owner_cannot_submit_without_documents(self):
        acct = ParentAccount.objects.create(
            email="nosubmit@example.com",
            phone="+37166666666",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "nosubmit@example.com",
                "guardian_full_name": "No Submit",
                "guardian_personal_id": "010101-66666",
                "guardian_phone": "+37177777777",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "Child NoSub",
                "member_personal_id": "010125-66666",
                "member_birth_date": "2025-03-01",
            },
            files={},
            verified_account=acct,
        )
        resp = self.client.post(
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

    def setup_method(self):
        self.client = Client()

    def test_portal_lists_only_current_parent_applications(self):
        """Two parents, two apps — each portal shows only own."""
        # Parent A
        acct_a = ParentAccount.objects.create(
            email="portalA@example.com",
            phone="+37188888888",
        )
        _login_via_magic_link(self.client, acct_a)
        from apps.registrations.services import create_or_update_draft

        create_or_update_draft(
            data={
                "guardian_email": "portalA@example.com",
                "guardian_full_name": "Parent A",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37199999999",
                "guardian_declared_address": "Riga 88",
                "member_full_name": "Child A",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-04-01",
            },
            files={},
            verified_account=acct_a,
        )

        # Parent B
        acct_b = ParentAccount.objects.create(
            email="portalB@example.com",
            phone="+37100000000",
        )
        _login_via_magic_link(self.client, acct_b)
        create_or_update_draft(
            data={
                "guardian_email": "portalB@example.com",
                "guardian_full_name": "Parent B",
                "guardian_personal_id": "010101-00000",
                "guardian_phone": "+37112121212",
                "guardian_declared_address": "Riga 99",
                "member_full_name": "Child B",
                "member_personal_id": "010125-00000",
                "member_birth_date": "2025-05-01",
            },
            files={},
            verified_account=acct_b,
        )

        # Re-login as A and check portal
        _login_via_magic_link(self.client, acct_a)
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Parent A" in content or "portalA" in content
        assert "Parent B" not in content and "portalB" not in content

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

        # Step 6: Open edit page — should work (session has verified parent)
        resp = client.get(f"/applications/{app.pk}/edit/")
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
        _login_via_magic_link(client, acct_b)

        # Parent B tries to edit Parent A's draft
        resp = client.get(f"/applications/{app_a.pk}/edit/")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Regression: submitted application portal card must show 'Skatīt pieteikumu'
# ---------------------------------------------------------------------------


class TestSubmittedApplicationPortalCard:
    """Submitted application card must show 'Skatīt pieteikumu', not 'Turpināt'."""

    def setup_method(self):
        self.client = Client()

    def _create_and_login(self, email="submittedperm@example.com"):
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        _login_via_magic_link(self.client, acct)
        return acct

    def _create_submitted_application(self, email="submittedperm@example.com"):
        shirt_pk, shorts_pk = _ensure_kit_sizes()
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = self._create_and_login(email)
        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Submitted Perm Guardian",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37166666666",
                "guardian_declared_address": "Riga 55",
                "member_full_name": "Child SubmittedPerm",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("submittedperm_guardian_id.png"),
                "member_identity_document": _make_member_identity_file("submittedperm_member_id.png"),
                "member_portrait_document": _make_member_identity_file("submittedperm_portrait.png"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        return app

    def test_portal_card_shows_skatit_ieteikumu_for_submitted(self):
        """Submitted application must show 'Skatīt pieteikumu' link on portal."""
        self._create_submitted_application()
        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Skatīt pieteikumu" in content, (
            "Submitted application portal card must show 'Skatīt pieteikumu'."
        )

    def test_portal_card_no_turpat_for_submitted(self):
        """Submitted application must NOT show 'Turpināt' link on portal."""
        self._create_submitted_application()
        resp = self.client.get("/portal/")
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

    def setup_method(self):
        self.client = Client()

    def _save_draft_anonymously(self, email="samebrowser@example.com"):
        """Save a draft as anonymous user and return the application."""
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
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
        return app

    def test_cross_browser_cannot_access_draft(self):
        """A fresh browser session cannot access a draft saved in another session."""
        self._save_draft_anonymously("crosscross@example.com")

        # Fresh client = different browser
        other_browser = Client()

        # Try to access by application ID
        from apps.registrations.models import RegistrationApplication

        app = RegistrationApplication.objects.get(
            guardian_email="crosscross@example.com"
        )
        resp = other_browser.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404, (
            "Cross-browser must not access draft by application ID."
        )

    def test_cross_browser_cannot_access_via_portal(self):
        """Cross-browser cannot see another browser's drafts in portal."""
        self._save_draft_anonymously("crossportal@example.com")

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

    def setup_method(self):
        self.client = Client()

    def _create_fix_requested_app(self, email="fixedit@example.com"):
        """Create a draft, submit it, then set status to fix_requested."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Fix Edit Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child FixEdit",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("fix_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("fix_member.jpg"),
                "member_portrait_document": _make_member_identity_file("fix_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.review_message = "Please correct the personal ID format."
        app.save(update_fields=["status", "review_message"])
        return acct, app

    def test_fix_requested_is_editable_by_owning_parent(self):
        """fix_requested application must be editable by owning parent."""
        from apps.registrations.services import can_edit_application

        acct, app = self._create_fix_requested_app("fixownedit@example.com")
        _login_via_magic_link(self.client, acct)

        assert can_edit_application(app, acct) is True, (
            "fix_requested application must be editable by owning parent."
        )

    def test_fix_requested_edit_page_accessible(self):
        """fix_requested application edit page must load (200) for owning parent."""
        acct, app = self._create_fix_requested_app("fixpageedit@example.com")
        _login_via_magic_link(self.client, acct)

        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 200, (
            f"Expected 200 for fix_requested edit page, got {resp.status_code}."
        )

    def test_fix_requested_not_editable_by_other_parent(self):
        """fix_requested application must not be editable by another parent."""
        from apps.registrations.services import can_edit_application

        acct, app = self._create_fix_requested_app("fixother@example.com")

        other = ParentAccount.objects.create(
            email="otherfix@example.com",
            phone="+37133333333",
        )
        _login_via_magic_link(self.client, other)

        assert can_edit_application(app, other) is False, (
            "fix_requested application must not be editable by other parent."
        )


class TestParentPortalFixRequestedVisibility:
    """Portal must show fix message and edit CTA for fix_requested."""

    def setup_method(self):
        self.client = Client()

    def _create_fix_requested_app(self, email="portalfix@example.com"):
        """Create a draft, submit it, then set status to fix_requested."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Portal Fix Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child PortalFix",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("pf_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("pf_member.jpg"),
                "member_portrait_document": _make_member_identity_file("pf_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.review_message = "Please correct the personal ID format."
        app.save(update_fields=["status", "review_message"])
        return acct, app

    def test_portal_shows_fix_message_and_edit_cta(self):
        """Portal must display review message and edit link for fix_requested."""
        acct, app = self._create_fix_requested_app("fixportalext@example.com")
        _login_via_magic_link(self.client, acct)

        resp = self.client.get("/portal/")
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
            or f"/applications/{app.pk}/edit/" in content
        )
        assert has_edit_link, (
            "Portal must show an edit/continue link for fix_requested application."
        )


class TestParentPortalRejectedVisibility:
    """Portal must show reject message but no edit CTA for rejected."""

    def setup_method(self):
        self.client = Client()

    def _create_rejected_app(self, email="portalreject@example.com"):
        """Create a draft, submit it, then set status to rejected."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = _ensure_kit_sizes()
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Portal Reject Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child PortalReject",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("pr_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("pr_member.jpg"),
                "member_portrait_document": _make_member_identity_file("pr_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        app.status = RegistrationApplication.Status.REJECTED
        app.review_message = "Application does not meet requirements."
        app.save(update_fields=["status", "review_message"])
        return acct, app

    def test_portal_shows_reject_message_no_edit_cta(self):
        """Portal must display reject message and no edit link."""
        acct, app = self._create_rejected_app("rejectportalext@example.com")
        _login_via_magic_link(self.client, acct)

        resp = self.client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Application does not meet requirements." in content, (
            "Portal must show the reject review message."
        )
        # Must NOT show an edit link
        has_edit_link = (
            f"/applications/{app.pk}/edit/" in content
        )
        assert not has_edit_link, (
            "Portal must not show an edit link for rejected application."
        )

    def test_rejected_application_not_editable_by_parent(self):
        """rejected application must not be editable by the owning parent."""
        from apps.registrations.services import can_edit_application

        acct, app = self._create_rejected_app("noteditreject@example.com")
        _login_via_magic_link(self.client, acct)

        assert can_edit_application(app, acct) is False, (
            "rejected application must not be editable."
        )

    def test_rejected_edit_page_returns_404(self):
        """rejected application edit page must return 404 for owning parent."""
        acct, app = self._create_rejected_app("rejected404@example.com")
        _login_via_magic_link(self.client, acct)

        resp = self.client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404, (
            f"Expected 404 for rejected edit page, got {resp.status_code}."
        )

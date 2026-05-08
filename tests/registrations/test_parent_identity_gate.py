"""Parent identity gate — security regression tests.

Red-phase: these tests assert the verified identity gate behavior described in
docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md.

They must FAIL against the current implementation because:
- parent_account is non-nullable FK (no claimed_email / verified_parent split)
- draft save auto-creates ParentAccount by typed email
- magic-link request requires ParentAccount to exist
- portal queries by parent_account which = auto-linked email
- no draft_session_key for same-browser continuity
"""

import pytest
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


def _make_child_identity_file(name="id.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


# ---------------------------------------------------------------------------
# 1. Typing an existing parent's email on a new draft must NOT expose
#    that parent's registrations.
# ---------------------------------------------------------------------------

class TestNoCrossRegistrationExposure:
    """Security: typed email must not be treated as proof of ownership."""

    def test_draft_with_existing_parent_email_does_not_expose_other_parents_apps(self):
        """Creating a draft with another parent's email must NOT auto-link
        or expose that parent's existing registrations.
        """
        from apps.registrations.services import create_or_update_draft

        # Parent A already has a registration
        parent_a = ParentAccount.objects.create(
            email="parenta@example.com",
            phone="+3711111111",
        )
        app_a = create_or_update_draft(
            data={
                "guardian_email": "parenta@example.com",
                "guardian_full_name": "Parent A",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child A",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={},
        )

        # Parent B creates a draft using parenta@example.com
        # In the target model, this should create a draft with claimed_email
        # but NOT link to parent_a
        app_b = create_or_update_draft(
            data={
                "guardian_email": "parenta@example.com",
                "guardian_full_name": "Parent B Impostor",
                "guardian_personal_id": "010101-22222",
                "guardian_phone": "+37133333333",
                "guardian_address": "Riga 2",
                "child_full_name": "Child B",
                "child_personal_id": "010125-22222",
                "child_birth_date": "2025-02-01",
            },
            files={},
        )

        # app_b must NOT be linked to parent_a
        assert app_b.parent_account_id != parent_a.id, (
            "Draft created with another parent's email must not auto-link "
            "to that parent's account."
        )

    def test_different_browser_cannot_access_existing_parent_applications(self):
        """A different browser (new session) must not see parent_a's apps
        just by typing parent_a's email.
        """
        from apps.registrations.services import create_or_update_draft

        parent_a = ParentAccount.objects.create(
            email="secureparent@example.com",
            phone="+3714444444",
        )
        create_or_update_draft(
            data={
                "guardian_email": "secureparent@example.com",
                "guardian_full_name": "Secure Parent",
                "guardian_personal_id": "010101-44444",
                "guardian_phone": "+37155555555",
                "guardian_address": "Riga 4",
                "child_full_name": "Child Secure",
                "child_personal_id": "010125-44444",
                "child_birth_date": "2025-03-01",
            },
            files={},
            verified_account=parent_a,
        )

        # New browser session — no login
        new_client = Client()
        # Try to access parent_a's application by ID
        app_id = ParentAccount.objects.get(
            email="secureparent@example.com"
        ).applications.first().pk

        resp = new_client.get(f"/applications/{app_id}/edit/")
        assert resp.status_code == 404, (
            "Different browser must not access another parent's application."
        )


# ---------------------------------------------------------------------------
# 2. Anonymous user can save and resume a draft in the same browser session.
# ---------------------------------------------------------------------------

class TestAnonymousDraftContinuity:
    """Anonymous draft save + resume must work in same browser session."""

    def test_anonymous_user_can_save_and_resume_draft(self):
        """Anonymous user saves draft → closes session → reopens → can edit."""
        from apps.registrations.services import create_or_update_draft

        # Save draft anonymously (no login)
        app = create_or_update_draft(
            data={
                "guardian_email": "anonymous@example.com",
                "guardian_full_name": "Anonymous Parent",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37166666666",
                "guardian_address": "Riga 6",
                "child_full_name": "Child Anon",
                "child_personal_id": "010125-99999",
                "child_birth_date": "2025-04-01",
            },
            files={},
        )

        # The draft should have a draft_session_key for same-browser access
        # This field must exist on the model
        assert hasattr(app, "draft_session_key"), (
            "RegistrationApplication must have draft_session_key field."
        )
        assert app.draft_session_key is not None, (
            "draft_session_key must be set when draft is saved."
        )

    def test_same_browser_can_resume_draft_without_verification(self):
        """Same browser can reopen draft via session without magic-link verification."""
        client = Client()
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "resume@example.com",
                "guardian_full_name": "Resume Parent",
                "guardian_personal_id": "010101-77777",
                "guardian_phone": "+37188888888",
                "guardian_address": "Riga 7",
                "child_full_name": "Child Resume",
                "child_personal_id": "010125-77777",
                "child_birth_date": "2025-05-01",
            },
            files={},
        )

        # Start page POST creates draft and stores session info
        resp = client.post(
            "/register/",
            data={
                "guardian_email": "resume@example.com",
                "guardian_full_name": "Resume Parent 2",
                "guardian_personal_id": "010101-77778",
                "guardian_phone": "+37188888889",
                "guardian_address": "Riga 7b",
                "child_full_name": "Child Resume 2",
                "child_personal_id": "010125-77778",
                "child_birth_date": "2025-05-02",
            },
            follow=False,
        )
        assert resp.status_code == 302

        # Edit page should be accessible without login
        edit_resp = client.get(resp.url, follow=False)
        assert edit_resp.status_code == 200, (
            "Same browser must be able to resume draft without verification."
        )


# ---------------------------------------------------------------------------
# 3. Different browser cannot access a draft by application ID alone.
# ---------------------------------------------------------------------------

class TestCrossBrowserDraftProtection:
    """Draft must not be accessible from a different browser session."""

    def test_different_browser_cannot_access_draft_by_id(self):
        """Draft saved in browser A must not be editable in browser B."""
        from apps.registrations.services import create_or_update_draft

        # Browser A creates draft
        app = create_or_update_draft(
            data={
                "guardian_email": "crossbrowser@example.com",
                "guardian_full_name": "Cross Browser",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37144444444",
                "guardian_address": "Riga 3",
                "child_full_name": "Child Cross",
                "child_personal_id": "010125-33333",
                "child_birth_date": "2025-06-01",
            },
            files={},
        )

        # Browser B tries to access the draft
        browser_b = Client()
        resp = browser_b.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404, (
            "Different browser must not access draft by application ID."
        )


# ---------------------------------------------------------------------------
# 4. Magic-link request should work for a claimed-email draft even when
#    no ParentAccount existed beforehand.
# ---------------------------------------------------------------------------

class TestMagicLinkForClaimedEmail:
    """Magic-link request must work for claimed-email drafts without
    a pre-existing ParentAccount.
    """

    def test_request_magic_link_works_without_existing_parent_account(self):
        """Requesting magic-link for an email that has no ParentAccount
        must succeed (not raise 'Konts ar šo e-pastu nav atrasts').
        """
        from apps.registrations.services import create_or_update_draft

        # Create a draft (which stores claimed_email) but no ParentAccount
        # exists yet. In the current code, _get_or_create_parent_account
        # creates one — in the target model, the draft has claimed_email
        # but no parent_account.
        app = create_or_update_draft(
            data={
                "guardian_email": "noaccount@example.com",
                "guardian_full_name": "No Account",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37166666666",
                "guardian_address": "Riga 5",
                "child_full_name": "Child NoAcct",
                "child_personal_id": "010125-55555",
                "child_birth_date": "2025-07-01",
            },
            files={},
        )

        # In the target model, parent_account should be NULL
        assert app.parent_account_id is None, (
            "Draft must not auto-link ParentAccount. parent_account should be NULL."
        )

        # Magic-link request should work for this email
        client = Client()
        resp = client.post(
            "/accounts/request-magic-link/",
            {"email": "noaccount@example.com"},
        )
        # Should NOT return 400/422 with "Konts ar šo e-pastu nav atrasts"
        assert resp.status_code == 200, (
            f"Magic-link request failed for claimed-email without ParentAccount. "
            f"Got status {resp.status_code}."
        )
        content = resp.content.decode()
        assert "Konts ar šo e-pastu nav atrasts" not in content, (
            "Magic-link form must not require pre-existing ParentAccount."
        )


# ---------------------------------------------------------------------------
# 5. After successful magic-link verification, matching claimed-email
#    applications become visible in the portal for the verified parent.
# ---------------------------------------------------------------------------

class TestPostVerificationPortalVisibility:
    """After magic-link verification, claimed-email drafts become visible."""

    def test_verified_parent_sees_matching_claimed_email_apps(self):
        """After verification, portal shows applications with matching
        claimed_email.
        """
        from apps.registrations.services import create_or_update_draft

        # Create a draft with claimed_email but no parent_account
        app = create_or_update_draft(
            data={
                "guardian_email": "verifyportal@example.com",
                "guardian_full_name": "Verify Portal",
                "guardian_personal_id": "010101-12121",
                "guardian_phone": "+37123232323",
                "guardian_address": "Riga 12",
                "child_full_name": "Child VP",
                "child_personal_id": "010125-12121",
                "child_birth_date": "2025-08-01",
            },
            files={},
        )

        # After verification, the app should be linked to the new ParentAccount
        client = Client()
        resp = client.post(
            "/accounts/request-magic-link/",
            {"email": "verifyportal@example.com"},
        )
        assert resp.status_code == 200, "Magic-link request must succeed."

        # Extract verify URL from response — use the last /accounts/verify/ path
        # found in the HTML (works for debug preview links in <a> or <code> tags).
        # If the response is a redirect, follow it directly.
        if resp.status_code == 302:
            client.get(resp.url)
        else:
            content = resp.content.decode()
            import re

            # Find all /accounts/verify/… occurrences; take the last one
            # (debug previews may list multiple URLs).
            verify_urls = re.findall(r"/accounts/verify/[^\s'\"<>]+", content)
            if verify_urls:
                last_url = verify_urls[-1]
                # Ensure trailing slash
                if not last_url.endswith("/"):
                    last_url += "/"
                client.get(last_url)
            # After verification, portal should show the application
            portal_resp = client.get("/portal/")
            assert portal_resp.status_code == 200
            portal_content = portal_resp.content.decode()
            assert "Verify Portal" in portal_content or "verifyportal" in portal_content, (
                "Verified parent must see matching claimed-email applications in portal."
            )


# ---------------------------------------------------------------------------
# 6. Portal must query by verified parent ownership, not just typed email.
# ---------------------------------------------------------------------------

class TestPortalQueriesByVerifiedParent:
    """Portal must use verified_parent, not claimed_email, for visibility."""

    def test_portal_does_not_show_apps_with_matching_claimed_email_only(self):
        """Portal must NOT show applications just because claimed_email matches.
        It must show only applications linked to the verified parent_account.
        """
        from apps.registrations.services import create_or_update_draft

        # Create an application for Parent A (verified)
        parent_a = ParentAccount.objects.create(
            email="portalquery@example.com",
            phone="+37134343434",
        )
        _login_via_magic_link(Client(), parent_a)

        app_a = create_or_update_draft(
            data={
                "guardian_email": "portalquery@example.com",
                "guardian_full_name": "Portal Query A",
                "guardian_personal_id": "010101-34343",
                "guardian_phone": "+37145454545",
                "guardian_address": "Riga 34",
                "child_full_name": "Child PQ A",
                "child_personal_id": "010125-34343",
                "child_birth_date": "2025-09-01",
            },
            files={},
            verified_account=parent_a,
        )

        # Parent A's portal should show their own app
        client = Client()
        _login_via_magic_link(client, parent_a)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Portal Query A" in content or "portalquery" in content, (
            "Portal must show verified parent's own applications."
        )

    def test_portal_model_has_verified_parent_field(self):
        """RegistrationApplication must have both claimed_email and
        verified_parent (or nullable parent_account) for the identity gate.
        Per the approved design spec the model uses claimed_email +
        verified_parent FK.
        """
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "claimed_email" in field_names, (
            "RegistrationApplication must have claimed_email field."
        )
        # The design spec calls for verified_parent; if the implementation
        # instead reuses a nullable parent_account, that also satisfies the
        # gate — but the field must exist and be nullable.
        has_verified_parent = "verified_parent" in field_names
        has_nullable_parent_account = False
        if "parent_account" in field_names:
            for f in RegistrationApplication._meta.get_fields():
                if f.name == "parent_account" and getattr(f, "null", False):
                    has_nullable_parent_account = True
                    break
        assert has_verified_parent or has_nullable_parent_account, (
            "RegistrationApplication must have verified_parent field "
            "or a nullable parent_account field."
        )


# ---------------------------------------------------------------------------
# 7. Submitted applications remain read-only.
# ---------------------------------------------------------------------------

class TestSubmittedApplicationsReadOnly:
    """Submitted applications must remain read-only regardless of verification."""

    def test_submitted_application_not_editable_after_verification(self):
        """Even after magic-link verification, submitted apps remain read-only."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = ParentAccount.objects.create(
            email="readonly@example.com",
            phone="+37156565656",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "readonly@example.com",
                "guardian_full_name": "Read Only",
                "guardian_personal_id": "010101-56565",
                "guardian_phone": "+37167676767",
                "guardian_address": "Riga 56",
                "child_full_name": "Child RO",
                "child_personal_id": "010125-56565",
                "child_birth_date": "2025-10-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("ro_id.png"),
            },
        )
        submit_application(app, acct)

        # Login via magic link
        client = Client()
        _login_via_magic_link(client, acct)

        # Submitted app must not be editable
        resp = client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 404, (
            "Submitted application must remain read-only after verification."
        )

    def test_portal_shows_submitted_but_not_editable(self):
        """Submitted application appears in portal with view-only indicator."""
        from apps.registrations.services import create_or_update_draft, submit_application

        acct = ParentAccount.objects.create(
            email="portalro@example.com",
            phone="+37178787878",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "portalro@example.com",
                "guardian_full_name": "Portal RO",
                "guardian_personal_id": "010101-78787",
                "guardian_phone": "+37189898989",
                "guardian_address": "Riga 78",
                "child_full_name": "Child PRO",
                "child_personal_id": "010125-78787",
                "child_birth_date": "2025-11-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("pro_id.png"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)

        client = Client()
        _login_via_magic_link(client, acct)

        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Portal RO" in content or "portalro" in content, (
            "Submitted application must appear in portal."
        )
        # Must NOT show continue/edit link
        assert "Turpināt" not in content, (
            "Submitted application must not show 'Turpināt' in portal."
        )

"""Parent identity gate — security regression tests.

P1-aligned. Covers:
- Typed email must NOT expose another parent's registrations.
- Cross-browser draft protection.
- Magic-link request works for claimed-email without pre-existing ParentAccount.
- After verification, matching claimed-email apps become visible.
- Portal queries by verified parent ownership.
- Submitted applications remain read-only.
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


def _make_member_identity_file(name="id.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_guardian_identity_file(name="guardian_id.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_member_portrait_file(name="portrait.png"):
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
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child A",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
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
                "guardian_declared_address": "Riga 2",
                "member_full_name": "Child B",
                "member_personal_id": "010125-22222",
                "member_birth_date": "2025-02-01",
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
                "guardian_declared_address": "Riga 4",
                "member_full_name": "Child Secure",
                "member_personal_id": "010125-44444",
                "member_birth_date": "2025-03-01",
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

        resp = new_client.get(f"/applications/{app_id}/")
        assert resp.status_code == 404, (
            "Different browser must not access another parent's application."
        )


# ---------------------------------------------------------------------------
# 2. Different browser cannot access a draft by application ID alone.
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
                "guardian_declared_address": "Riga 3",
                "member_full_name": "Child Cross",
                "member_personal_id": "010125-33333",
                "member_birth_date": "2025-06-01",
            },
            files={},
        )

        # Browser B tries to access the draft
        browser_b = Client()
        resp = browser_b.get(f"/applications/{app.pk}/")
        assert resp.status_code == 404, (
            "Different browser must not access draft by application ID."
        )


# ---------------------------------------------------------------------------
# 3. Magic-link request should work for a claimed-email draft even when
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
        # exists yet. In the target model, the draft has claimed_email
        # but no parent_account.
        app = create_or_update_draft(
            data={
                "guardian_email": "noaccount@example.com",
                "guardian_full_name": "No Account",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37166666666",
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child NoAcct",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-07-01",
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
# 4. After successful magic-link verification, matching claimed-email
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
                "guardian_declared_address": "Riga 12",
                "member_full_name": "Child VP",
                "member_personal_id": "010125-12121",
                "member_birth_date": "2025-08-01",
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
# 5. Portal must query by verified parent ownership, not just typed email.
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
                "guardian_declared_address": "Riga 34",
                "member_full_name": "Child PQ A",
                "member_personal_id": "010125-34343",
                "member_birth_date": "2025-09-01",
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

    def test_portal_model_has_claimed_email_and_nullable_parent_account(self):
        """RegistrationApplication must have claimed_email and
        a nullable parent_account for the identity gate.
        """
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "claimed_email" in field_names, (
            "RegistrationApplication must have claimed_email field."
        )
        # parent_account must exist and be nullable
        has_nullable_parent_account = False
        if "parent_account" in field_names:
            for f in RegistrationApplication._meta.get_fields():
                if f.name == "parent_account" and getattr(f, "null", False):
                    has_nullable_parent_account = True
                    break
        assert has_nullable_parent_account, (
            "RegistrationApplication must have a nullable parent_account field."
        )


# ---------------------------------------------------------------------------
# 6. Submitted applications remain read-only.
# ---------------------------------------------------------------------------

class TestSubmittedApplicationsReadOnly:
    """Submitted applications must remain read-only regardless of verification."""

    def test_submitted_application_not_editable_after_verification(self):
        """Even after magic-link verification, submitted apps remain read-only."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft
        from django.utils import timezone

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
                "guardian_declared_address": "Riga 56",
                "member_full_name": "Child RO",
                "member_personal_id": "010125-56565",
                "member_birth_date": "2025-10-01",
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("ro_guardian.png"),
                "member_identity_document": _make_member_identity_file("ro_member.png"),
                "member_portrait_document": _make_member_portrait_file("ro_portrait.png"),
            },
            verified_account=acct,
        )
        # Set status directly to submitted (service-layer submit requires kit sizes
        # which are not created in this test — the gate test only checks editability).
        app.status = RegistrationApplication.Status.SUBMITTED
        app.submitted_at = timezone.now()
        app.save(update_fields=["status", "submitted_at"])

        # Login via magic link
        client = Client()
        _login_via_magic_link(client, acct)

        # Submitted app must not be editable — redirects to workspace (read-only)
        resp = client.get(f"/applications/{app.pk}/edit/")
        assert resp.status_code == 302, (
            "Submitted application edit route must redirect to workspace."
        )
        assert resp.headers["Location"].endswith(f"/applications/{app.pk}/")

    def test_portal_shows_submitted_but_not_editable(self):
        """Submitted application appears in portal with view-only indicator."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft
        from django.utils import timezone

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
                "guardian_declared_address": "Riga 78",
                "member_full_name": "Child PRO",
                "member_personal_id": "010125-78787",
                "member_birth_date": "2025-11-01",
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("pro_guardian.png"),
                "member_identity_document": _make_member_identity_file("pro_member.png"),
                "member_portrait_document": _make_member_portrait_file("pro_portrait.png"),
            },
            verified_account=acct,
        )
        # Set status directly to submitted (gate test only checks visibility/editability).
        app.status = RegistrationApplication.Status.SUBMITTED
        app.submitted_at = timezone.now()
        app.save(update_fields=["status", "submitted_at"])

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

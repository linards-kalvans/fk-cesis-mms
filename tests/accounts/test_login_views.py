"""Task 4 — magic-link request, verify, logout views + session RED tests."""

import pytest
from django.core import mail
from django.test import Client
from django.conf import settings

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Request view
# ---------------------------------------------------------------------------

class TestRequestMagicLinkView:

    def setup_method(self):
        self.client = Client()

    def test_post_sends_email(self):
        ParentAccount.objects.create(
            email="viewreq@example.com",
            phone="+3711111111",
        )
        resp = self.client.post(
            "/accounts/request-magic-link/",
            {"email": "viewreq@example.com"},
        )
        assert resp.status_code in (200, 302)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["viewreq@example.com"]

    def test_email_contains_verify_url(self):
        ParentAccount.objects.create(
            email="viewurl@example.com",
            phone="+3712222222",
        )
        self.client.post(
            "/accounts/request-magic-link/",
            {"email": "viewurl@example.com"},
        )
        body = mail.outbox[0].body.lower()
        assert "/accounts/verify/" in body

    def test_post_shows_debug_preview_link_in_debug_mode(self):
        ParentAccount.objects.create(
            email="preview@example.com",
            phone="+3715550000",
        )
        resp = self.client.post(
            "/accounts/request-magic-link/",
            {"email": "preview@example.com"},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Piekļuves saite nosūtīta" in content
        assert "/accounts/verify/" in content

    def test_debug_preview_link_uses_request_host_for_lan_uat(self):
        ParentAccount.objects.create(
            email="lanpreview@example.com",
            phone="+3715551111",
        )
        resp = self.client.post(
            "/accounts/request-magic-link/",
            {"email": "lanpreview@example.com"},
            HTTP_HOST="192.168.3.245:8000",
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "http://192.168.3.245:8000/accounts/verify/" in content

    def test_get_uses_parent_shell_and_latvian_copy(self):
        resp = self.client.get("/accounts/request-magic-link/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-parent-shell" in content
        assert "E-pasts" in content
        assert "Saņemt piekļuves saiti" in content


class TestMagicLinkCookieSettings:

    def test_request_page_sets_non_secure_csrf_cookie_for_local_uat(self):
        client = Client()
        resp = client.get("/accounts/request-magic-link/")
        assert resp.status_code == 200
        assert resp.cookies["csrftoken"]["secure"] is not True


# ---------------------------------------------------------------------------
# Verify (consume) view
# ---------------------------------------------------------------------------

class TestVerifyView:

    def setup_method(self):
        self.client = Client()

    def test_get_sets_session_key(self):
        from apps.accounts.services import issue_magic_link

        acct = ParentAccount.objects.create(
            email="verify@example.com",
            phone="+3713333333",
        )
        raw = issue_magic_link(acct)
        resp = self.client.get(f"/accounts/verify/{raw}/")
        assert resp.status_code == 302
        assert self.client.session[PARENT_ACCOUNT_SESSION_KEY] == acct.pk

    def test_invalid_token_returns_error(self):
        resp = self.client.get("/accounts/verify/nonexistenttoken/")
        assert resp.status_code in (200, 400, 404)

    def test_invalid_token_page_is_latvian(self):
        resp = self.client.get("/accounts/verify/nonexistenttoken/")
        content = resp.content.decode()
        assert "Nederīga vai noilgusi piekļuves saite" in content

    def test_verify_response_sets_non_secure_session_cookie_for_local_uat(self):
        from apps.accounts.services import issue_magic_link

        acct = ParentAccount.objects.create(
            email="verifycookie@example.com",
            phone="+3719999999",
        )
        raw = issue_magic_link(acct)
        resp = self.client.get(f"/accounts/verify/{raw}/")
        assert resp.status_code == 302
        assert resp.cookies[settings.SESSION_COOKIE_NAME]["secure"] is not True


# ---------------------------------------------------------------------------
# Logout view
# ---------------------------------------------------------------------------

class TestLogoutView:

    def setup_method(self):
        self.client = Client()
        from apps.accounts.services import issue_magic_link

        self.acct = ParentAccount.objects.create(
            email="logout@example.com",
            phone="+3714444444",
        )
        raw = issue_magic_link(self.acct)
        self.client.get(f"/accounts/verify/{raw}/")
        assert self.client.session[PARENT_ACCOUNT_SESSION_KEY] == self.acct.pk

    def test_post_clears_session(self):
        self.client.post("/accounts/logout/")
        assert PARENT_ACCOUNT_SESSION_KEY not in self.client.session


# ---------------------------------------------------------------------------
# Parent identity gate — magic-link for claimed-email without ParentAccount
# ---------------------------------------------------------------------------

class TestMagicLinkForClaimedEmail:
    """Magic-link request must work for emails without existing ParentAccount.

    This is the identity gate: a draft stores claimed_email, and the user
    can request a magic link to verify ownership and unlock portal access.
    """

    def setup_method(self):
        self.client = Client()

    def test_request_magic_link_without_existing_account_succeeds(self):
        """Requesting magic-link for an email with no ParentAccount must
        not fail with 'Konts ar šo e-pastu nav atrasts'.
        """
        resp = self.client.post(
            "/accounts/request-magic-link/",
            {"email": "newemail@example.com"},
        )
        assert resp.status_code == 200, (
            f"Magic-link request for non-existent account failed with {resp.status_code}. "
            "Expected 200 (debug preview mode)."
        )
        content = resp.content.decode()
        assert "Konts ar šo e-pastu nav atrasts" not in content, (
            "Form must not reject emails without existing ParentAccount."
        )

    def test_request_magic_link_creates_parent_account_on_verify(self):
        """After magic-link verification for a non-existent account,
        a ParentAccount must be created.
        """
        # Request magic link for new email
        resp = self.client.post(
            "/accounts/request-magic-link/",
            {"email": "newaccount@example.com"},
        )
        assert resp.status_code == 200

        # Extract verify URL from debug preview
        content = resp.content.decode()
        import re
        from urllib.parse import urlparse
        match = re.search(r'https?://[^"\' ]+/accounts/verify/[^"\' <]+', content)
        assert match is not None, "Debug verify URL not found in response."
        verify_path = urlparse(match.group(0)).path

        # Consume the token
        verify_resp = self.client.get(verify_path)
        assert verify_resp.status_code == 302

        # ParentAccount must now exist
        assert ParentAccount.objects.filter(
            email="newaccount@example.com"
        ).exists(), (
            "ParentAccount must be created after magic-link verification "
            "for a claimed-email draft."
        )

    def test_verify_redirects_to_parent_portal(self):
        """After verification, user is redirected to /portal/."""
        resp = self.client.post(
            "/accounts/request-magic-link/",
            {"email": "redirect@example.com"},
        )
        assert resp.status_code == 200

        import re
        from urllib.parse import urlparse
        content = resp.content.decode()
        match = re.search(r'https?://[^"\' ]+/accounts/verify/[^"\' <]+', content)
        assert match is not None
        verify_path = urlparse(match.group(0)).path

        verify_resp = self.client.get(verify_path)
        assert verify_resp.status_code == 302
        assert "portal" in verify_resp.url.lower(), (
            f"Verify redirect should go to portal. Got: {verify_resp.url}"
        )

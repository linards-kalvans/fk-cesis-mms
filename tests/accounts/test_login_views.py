"""Task 4 — magic-link request, verify, logout views + session RED tests."""

import pytest
from django.core import mail
from django.test import Client

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

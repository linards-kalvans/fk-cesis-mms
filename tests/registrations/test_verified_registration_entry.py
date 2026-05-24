"""P1 — Verified registration entry route (one-time code gate).

Tests the new code-verification flow for registration entry:
  1. GET /register/ shows guardian email entry page.
  2. POST /register/ accepts email, issues one-time code, stores pending
     verification email in session, redirects to /register/verify/.
  3. GET/POST /register/verify/ handles one-time code verification.
  4. Successful verification creates ParentAccount for new guardian email,
     logs guardian into verified session, redirects to /portal/.
  5. Typed email alone grants nothing; unverified users cannot access
     /portal/ or /applications/new/.
  6. Cross-account regression: verifying one account does not expose
     another account's registrations.
  7. Code lifecycle: single-use, expiry rejection, rate-limit rejection.

These tests target the one-time code verification method (P1), NOT
magic-link entry. Magic-link tests live in tests/accounts/.

Approved model: EmailVerificationCode in apps.accounts.models.
Approved session key: pending_verification_email (not pending_verify_email).
Approved routes: /register/, /register/verify/, /portal/, /applications/new/.
"""

import re

import pytest
from django.core import mail
from django.test import Client, override_settings

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY

pytestmark = pytest.mark.django_db

# Fixed routes — no HTML extraction needed.
REGISTER_ROUTE = "/register/"
VERIFY_ROUTE = "/register/verify/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_code_from_email():
    """Extract the 6-digit code from the latest email."""
    body = mail.outbox[-1].body
    match = re.search(r"\b\d{6}\b", body)
    assert match is not None, (
        f"No 6-digit code found in email body: {body[:300]}"
    )
    return match.group(0)


def _login_via_code(client, email):
    """Helper: POST /register/ then POST /register/verify/ with correct code
    to establish a verified parent session. Returns the ParentAccount.
    """
    client.post(REGISTER_ROUTE, {"email": email})
    code = _extract_code_from_email()
    client.post(VERIFY_ROUTE, {"code": code})
    return ParentAccount.objects.get(email=email)


# ---------------------------------------------------------------------------
# 1. GET /register/ is guardian email entry page
# ---------------------------------------------------------------------------

class TestRegisterEntryPage:

    def test_get_register_returns_200(self):
        """GET /register/ must return 200 (email entry page)."""
        resp = Client().get(REGISTER_ROUTE)
        assert resp.status_code == 200, (
            f"GET {REGISTER_ROUTE} returned {resp.status_code}, expected 200."
        )

    def test_get_register_shows_email_input(self):
        """GET /register/ must render an email input field."""
        resp = Client().get(REGISTER_ROUTE)
        content = resp.content.decode()
        assert "email" in content.lower(), (
            "Registration entry page must contain an email input."
        )

    def test_get_register_does_not_require_login(self):
        """GET /register/ must be accessible without prior login."""
        client = Client()
        assert PARENT_ACCOUNT_SESSION_KEY not in client.session
        resp = client.get(REGISTER_ROUTE)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. POST /register/ sends one-time code and redirects to verify page
# ---------------------------------------------------------------------------

class TestRegisterEntryPost:

    def setup_method(self):
        self.client = Client()

    def test_post_register_sends_one_time_code(self):
        """POST /register/ with email must send a one-time code via email."""
        resp = self.client.post(
            REGISTER_ROUTE,
            {"email": "newguardian@example.com"},
        )
        assert resp.status_code in (200, 302), (
            f"POST {REGISTER_ROUTE} returned {resp.status_code}."
        )
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["newguardian@example.com"]

    def test_post_register_stores_pending_verification_email_in_session(self):
        """POST /register/ must store pending_verification_email in session."""
        self.client.post(
            REGISTER_ROUTE,
            {"email": "sessiontest@example.com"},
        )
        assert "pending_verification_email" in self.client.session, (
            "Session must store pending_verification_email after POST /register/."
        )
        assert self.client.session["pending_verification_email"] == "sessiontest@example.com"

    def test_post_register_redirects_to_verify_page(self):
        """POST /register/ must redirect to /register/verify/."""
        resp = self.client.post(
            REGISTER_ROUTE,
            {"email": "redirecttest@example.com"},
        )
        if resp.status_code == 302:
            assert VERIFY_ROUTE in resp.url, (
                f"Redirect should go to {VERIFY_ROUTE}. Got: {resp.url}"
            )
        else:
            content = resp.content.decode()
            assert VERIFY_ROUTE in content, (
                "Response should contain a verify link."
            )

    def test_post_register_code_is_six_digits(self):
        """The one-time code sent via email must be a 6-digit number."""
        self.client.post(
            REGISTER_ROUTE,
            {"email": "codedigit@example.com"},
        )
        code = _extract_code_from_email()
        assert len(code) == 6
        assert code.isdigit()


# ---------------------------------------------------------------------------
# 3. GET/POST /register/verify/ handles one-time code verification
# ---------------------------------------------------------------------------

class TestVerifyPage:

    def setup_method(self):
        self.client = Client()

    def test_get_verify_page_requires_pending_email(self):
        """GET /register/verify/ without pending email in session must not
        allow verification.
        """
        resp = self.client.get(VERIFY_ROUTE)
        assert resp.status_code not in (200,), (
            f"GET {VERIFY_ROUTE} without pending_verification_email "
            f"should not return 200. Got {resp.status_code}."
        )

    def test_post_verify_with_wrong_code_fails(self):
        """Submitting a wrong one-time code must fail."""
        self.client.post(
            REGISTER_ROUTE,
            {"email": "wrongcode@example.com"},
        )
        resp = self.client.post(VERIFY_ROUTE, {"code": "000000"})
        assert resp.status_code in (200, 400), (
            f"Wrong code should return 200 or 400, got {resp.status_code}."
        )
        assert not ParentAccount.objects.filter(
            email="wrongcode@example.com"
        ).exists(), (
            "ParentAccount must not be created with wrong code."
        )

    def test_post_verify_with_empty_code_fails(self):
        """Submitting an empty code must fail."""
        self.client.post(
            REGISTER_ROUTE,
            {"email": "emptycode@example.com"},
        )
        resp = self.client.post(VERIFY_ROUTE, {"code": ""})
        assert resp.status_code in (200, 400), (
            f"Empty code should return 200 or 400, got {resp.status_code}."
        )


# ---------------------------------------------------------------------------
# 4. One-time code is the P1 verification method (not magic-link)
# ---------------------------------------------------------------------------

class TestCodeIsP1Method:
    """The registration entry gate uses one-time code, not magic-link."""

    def test_register_entry_does_not_use_magic_link_flow(self):
        """POST /register/ must NOT issue a magic-link token.
        It must issue a one-time code sent via email body.
        """
        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "p1method@example.com"},
        )
        assert len(mail.outbox) == 1
        body = mail.outbox[0].body
        assert re.search(r"\d{6}", body), (
            "Email body must contain a 6-digit numeric code."
        )
        assert "/accounts/verify/" not in body, (
            "Registration entry email must not contain magic-link verify URL."
        )


# ---------------------------------------------------------------------------
# 5. Successful verification creates ParentAccount for new guardian email
# ---------------------------------------------------------------------------

class TestParentAccountCreationOnVerify:

    def test_new_guardian_email_creates_parent_account(self):
        """Code verification for a never-seen email must create ParentAccount."""
        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "freshguardian@example.com"},
        )
        code = _extract_code_from_email()
        resp = client.post(VERIFY_ROUTE, {"code": code})
        assert resp.status_code == 302, (
            f"Code verification POST returned {resp.status_code}, expected 302."
        )
        acct = ParentAccount.objects.get(email="freshguardian@example.com")
        assert acct is not None
        assert acct.is_active is True

    def test_existing_guardian_email_reuses_parent_account(self):
        """Code verification for an existing ParentAccount email must reuse it."""
        existing = ParentAccount.objects.create(
            email="existingguardian@example.com",
            phone="+37120000000",
        )
        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "existingguardian@example.com"},
        )
        code = _extract_code_from_email()
        resp = client.post(VERIFY_ROUTE, {"code": code})
        assert resp.status_code == 302, (
            f"Code verification POST returned {resp.status_code}, expected 302."
        )
        assert ParentAccount.objects.filter(
            email="existingguardian@example.com"
        ).count() == 1
        assert ParentAccount.objects.get(
            email="existingguardian@example.com"
        ).pk == existing.pk


# ---------------------------------------------------------------------------
# 6. Successful verification logs guardian in and redirects to /portal/
# ---------------------------------------------------------------------------

class TestPostVerificationLogin:

    def test_verified_user_can_access_portal(self):
        """After code verification, user must be able to access /portal/."""
        client = Client()
        _login_via_code(client, "portalaccess@example.com")
        resp = client.get("/portal/")
        assert resp.status_code == 200, (
            f"Verified user must access /portal/ (200), got {resp.status_code}."
        )

    def test_session_contains_parent_account_id_after_verification(self):
        """After code verification, session must contain the parent account ID."""
        client = Client()
        _login_via_code(client, "sessionid@example.com")
        assert PARENT_ACCOUNT_SESSION_KEY in client.session
        acct = ParentAccount.objects.get(email="sessionid@example.com")
        assert client.session[PARENT_ACCOUNT_SESSION_KEY] == acct.pk

    def test_verification_redirects_to_portal(self):
        """After successful code verification, user is redirected to /portal/."""
        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "verifyredirect@example.com"},
        )
        code = _extract_code_from_email()
        resp = client.post(VERIFY_ROUTE, {"code": code})
        assert resp.status_code == 302
        assert "portal" in resp.url.lower(), (
            f"Verification redirect should go to /portal/. Got: {resp.url}"
        )


# ---------------------------------------------------------------------------
# 7. Typed email alone grants nothing; unverified users can't access
#    /portal/ or /applications/new/
# ---------------------------------------------------------------------------

class TestUnverifiedAccessBlocked:

    def test_unverified_user_cannot_access_portal(self):
        """User who typed email but did NOT verify code must not access /portal/."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "unverified@example.com"})
        resp = client.get("/portal/")
        assert resp.status_code in (302, 403, 404), (
            f"Unverified user must NOT access /portal/. Got {resp.status_code}."
        )

    def test_unverified_user_cannot_access_new_application_form(self):
        """GET /applications/new/ without verification must be blocked."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "noapp@example.com"})
        resp = client.get("/applications/new/")
        assert resp.status_code in (302, 403), (
            f"Unverified user must NOT access /applications/new/. Got {resp.status_code}."
        )

    def test_typed_email_grants_no_access(self):
        """Simply typing an email on the entry page must not log the user in."""
        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "grantsnothing@example.com"},
        )
        assert PARENT_ACCOUNT_SESSION_KEY not in client.session, (
            "Typing email must not establish a parent session."
        )


# ---------------------------------------------------------------------------
# 8. Cross-account regression: verifying one account does not expose
#    another account's registrations
# ---------------------------------------------------------------------------

class TestCrossAccountRegression:

    def test_verify_account_a_does_not_expose_account_b_registrations(self):
        """Verifying ParentAccount A via code must not show ParentAccount B's apps."""
        # Create two accounts
        acct_a = ParentAccount.objects.create(
            email="crossa@example.com",
            phone="+37111111111",
        )
        acct_b = ParentAccount.objects.create(
            email="crossb@example.com",
            phone="+37133333333",
        )

        # Create an application for account B
        from apps.registrations.services import create_or_update_draft

        app_b = create_or_update_draft(
            data={
                "guardian_email": "crossb@example.com",
                "guardian_full_name": "Cross B",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37144444444",
                "guardian_address": "Riga B",
                "child_full_name": "Child B",
                "child_personal_id": "010125-33333",
                "child_birth_date": "2025-02-01",
            },
            files={},
            verified_account=acct_b,
        )

        # Login as account A via code verification
        client = Client()
        _login_via_code(client, "crossa@example.com")

        # Access portal — should not show app_b
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Cross B" not in content and "crossb" not in content, (
            "Account A portal must NOT show account B's applications."
        )


# ---------------------------------------------------------------------------
# 9. Code lifecycle: single-use, expiry rejection, rate-limit rejection
# ---------------------------------------------------------------------------

class TestCodeLifecycle:

    def test_single_use_code_rejected_on_second_attempt(self):
        """A one-time code must be single-use; second verification attempt
        must fail.
        """
        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "singleuse@example.com"},
        )
        code = _extract_code_from_email()

        # First use — must succeed
        resp1 = client.post(VERIFY_ROUTE, {"code": code})
        assert resp1.status_code == 302, (
            f"First code use should redirect (302). Got {resp1.status_code}."
        )

        # Second use — must fail
        resp2 = client.post(VERIFY_ROUTE, {"code": code})
        assert resp2.status_code in (200, 400), (
            f"Second code use must fail (200/400), got {resp2.status_code}."
        )

    def test_expired_code_rejected(self):
        """A one-time code past its TTL must be rejected.

        Deterministic: manipulates persisted EmailVerificationCode record
        timestamps directly. No time.sleep().
        """
        from datetime import timedelta

        from apps.accounts.models import EmailVerificationCode

        client = Client()
        client.post(
            REGISTER_ROUTE,
            {"email": "expired@example.com"},
        )
        code = _extract_code_from_email()

        # Backdate the latest code record so it is expired
        latest = EmailVerificationCode.objects.filter(
            email__iexact="expired@example.com",
        ).order_by("-created_at").first()
        assert latest is not None, (
            "EmailVerificationCode record must exist for the emailed address."
        )
        latest.expires_at = latest.created_at - timedelta(seconds=1)
        latest.save(update_fields=["expires_at"])

        resp = client.post(VERIFY_ROUTE, {"code": code})
        assert resp.status_code in (200, 400), (
            f"Expired code must be rejected (200/400), got {resp.status_code}."
        )
        assert not ParentAccount.objects.filter(
            email="expired@example.com"
        ).exists(), (
            "Expired code must not create ParentAccount."
        )

    @override_settings(ONE_TIME_CODE_RATE_LIMIT_PER_MINUTE=1)
    def test_rate_limit_rejection(self):
        """Exceeding the one-time code rate limit must be rejected."""
        client = Client()

        # First code request — allowed
        client.post(
            REGISTER_ROUTE,
            {"email": "ratelimit@example.com"},
        )
        assert len(mail.outbox) == 1

        # Second code request within window — must be rejected
        client.post(
            REGISTER_ROUTE,
            {"email": "ratelimit@example.com"},
        )
        # Email count should still be 1 (second request blocked)
        assert len(mail.outbox) == 1, (
            "Rate-limited code request must not send a second email."
        )


class TestTask2VerifiedEntryStillWorks:
    """The full register→verify→portal flow must still work after Task 2."""

    def test_full_flow_register_verify_portal(self):
        """Full register→verify→portal flow must succeed."""
        client = Client()
        # Step 1: POST /register/
        resp = client.post(REGISTER_ROUTE, {"email": "flowtest@example.com"})
        assert resp.status_code == 302
        assert VERIFY_ROUTE in resp.url

        # Step 2: Extract code and POST /register/verify/
        code = _extract_code_from_email()
        resp = client.post(VERIFY_ROUTE, {"code": code})
        assert resp.status_code == 302
        assert "portal" in resp.url.lower()

        # Step 3: Verify portal is accessible
        resp = client.get("/portal/")
        assert resp.status_code == 200

    def test_verify_page_still_accepts_code(self):
        """Verify page POST must still accept correct code."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "codetest@example.com"})
        code = _extract_code_from_email()
        resp = client.post(VERIFY_ROUTE, {"code": code})
        assert resp.status_code == 302

    def test_verify_page_still_rejects_wrong_code(self):
        """Verify page POST must still reject wrong code."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "wrongcodetest@example.com"})
        resp = client.post(VERIFY_ROUTE, {"code": "000000"})
        assert resp.status_code in (200, 400)
        assert not ParentAccount.objects.filter(
            email="wrongcodetest@example.com"
        ).exists()

    def test_verify_page_still_rejects_empty_code(self):
        """Verify page POST must still reject empty code."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "emptycodetest@example.com"})
        resp = client.post(VERIFY_ROUTE, {"code": ""})
        assert resp.status_code in (200, 400)

    def test_session_established_after_verify(self):
        """After verify, session must contain PARENT_ACCOUNT_SESSION_KEY."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "sessiontest2@example.com"})
        code = _extract_code_from_email()
        client.post(VERIFY_ROUTE, {"code": code})
        assert PARENT_ACCOUNT_SESSION_KEY in client.session


# ===========================================================================
# Critical review follow-up: error state rendering in parent entry/verify flow
# ===========================================================================


class TestRegisterPageErrorStateRendering:
    """Register page must render visible error feedback on POST errors."""

    def test_empty_email_post_shows_error_text(self):
        """POST /register/ with empty email must render visible error feedback."""
        resp = Client().post(REGISTER_ROUTE, {"email": ""})
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Ievadiet e-pasta adresi" in content, (
            "Register page must render visible error text when email is empty."
        )

    def test_invalid_request_path_returns_error_context(self):
        """Register page must render error context when request is invalid."""
        resp = Client().post(REGISTER_ROUTE, {})
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Ievadiet e-pasta adresi" in content, (
            "Register page must render visible error text when email key is missing."
        )


class TestVerifyPageErrorStateRendering:
    """Verify page must render visible error feedback on POST errors."""

    def test_empty_code_post_shows_error_text(self):
        """POST /register/verify/ with empty code must render visible error feedback."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "errortest@example.com"})
        resp = client.post(VERIFY_ROUTE, {"code": ""})
        assert resp.status_code in (200, 400)
        content = resp.content.decode()
        assert "Ievadiet piekļuves kodu" in content, (
            "Verify page must render visible error text when code is empty."
        )

    def test_wrong_code_post_shows_error_text(self):
        """POST /register/verify/ with wrong code must render visible error feedback."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "wrongerrortest@example.com"})
        resp = client.post(VERIFY_ROUTE, {"code": "000000"})
        assert resp.status_code in (200, 400)
        content = resp.content.decode()
        assert "Nederīgs vai noilgušs kods" in content, (
            "Verify page must render visible error text when code is wrong."
        )


class TestVerifyPagePOSTErrorShowsPendingEmail:
    """Verify page POST error renders must still show pending_email."""

    def test_empty_code_post_shows_pending_email(self):
        """POST /register/verify/ with empty code must still display pending email."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "pendingerrortest@example.com"})
        resp = client.post(VERIFY_ROUTE, {"code": ""})
        assert resp.status_code in (200, 400)
        content = resp.content.decode()
        assert "pendingerrortest@example.com" in content, (
            "Verify page POST error must still show the pending verification email."
        )

    def test_wrong_code_post_shows_pending_email(self):
        """POST /register/verify/ with wrong code must still display pending email."""
        client = Client()
        client.post(REGISTER_ROUTE, {"email": "pendingwrongtest@example.com"})
        resp = client.post(VERIFY_ROUTE, {"code": "000000"})
        assert resp.status_code in (200, 400)
        content = resp.content.decode()
        assert "pendingwrongtest@example.com" in content, (
            "Verify page POST error must still show the pending verification email."
        )

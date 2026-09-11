"""RED tests — verification-code auto-check endpoint.

Contract under test (feature not yet implemented):

    POST /register/verify/check/  (root project url name ``register-verify-check``,
    mirroring the existing root-level ``register-verify`` public route —
    NOT namespaced under ``accounts:`` whose include sits below /accounts/)

    * CSRF-protected, POST-only JSON endpoint.
    * Reads ``code`` (POST form data) against session key
      ``pending_verification_email``.
    * ``{"valid": true}`` when an active, matching, unused six-digit
      EmailVerificationCode exists.
    * NEVER consumes or mutates the OTP — the regular verification form
      must still succeed with the same code afterwards.
    * Generic failure shape ``{"valid": false,
      "error": "Nederīgs vai noilgušs kods."}`` for missing session,
      empty/malformed code, wrong code, expired code, used code, and
      codes belonging to another email. No lifecycle detail leakage.
    * Non-POST methods rejected (405).

Uses the real entry flow (POST /register/ → extract code from email) as
fixtures wherever possible; ``issue_one_time_code`` (public service API)
for setups that need a code without a session.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import EmailVerificationCode, ParentAccount
from apps.accounts.services import issue_one_time_code
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY

pytestmark = pytest.mark.django_db

CHECK_URL_NAME = "register-verify-check"
CHECK_PATH = "/register/verify/check/"
VERIFY_FORM_PATH = "/register/verify/"
ENTRY_PATH = "/register/"

GENERIC_ERROR = "Nederīgs vai noilgušs kods."
FAILURE_PAYLOAD = {"valid": False, "error": GENERIC_ERROR}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_code_from_email() -> str:
    body = mail.outbox[-1].body
    match = re.search(r"\b\d{6}\b", body)
    assert match is not None, f"No 6-digit code in email body: {body[:200]}"
    return match.group(0)


def _start_verification(client: Client, email: str) -> str:
    """Real entry flow: POST /register/, return the emailed code.

    Leaves ``pending_verification_email`` set in the client session.
    """
    resp = client.post(ENTRY_PATH, {"email": email})
    assert resp.status_code == 302, f"entry POST setup failed: {resp.status_code}"
    assert client.session.get("pending_verification_email") == email
    return _extract_code_from_email()


def _check(client: Client, code: str):
    return client.post(reverse(CHECK_URL_NAME), {"code": code})


def _assert_generic_failure(resp) -> None:
    assert resp.status_code == 200, f"expected 200 JSON failure, got {resp.status_code}"
    assert resp["Content-Type"].startswith("application/json"), resp["Content-Type"]
    payload = json.loads(resp.content)
    # Exact shape: generic error, no lifecycle detail keys (reason/code/state).
    assert payload == FAILURE_PAYLOAD, payload


def _expire_codes(email: str) -> None:
    EmailVerificationCode.objects.filter(email=email).update(
        expires_at=timezone.now() - timedelta(minutes=5)
    )


def _consume_codes(email: str) -> None:
    EmailVerificationCode.objects.filter(email=email).update(
        used_at=timezone.now(),
    )


# ---------------------------------------------------------------------------
# Routing + method contract
# ---------------------------------------------------------------------------

class TestCheckEndpointRouting:
    def test_url_name_resolves_to_expected_path(self):
        assert reverse(CHECK_URL_NAME) == CHECK_PATH

    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_non_post_methods_rejected(self, method: str):
        client = Client()
        code = _start_verification(client, f"routing-{method}@example.com")
        assert code  # pending session is in place; rejection is method-only
        url = reverse(CHECK_URL_NAME)
        resp = getattr(client, method)(url, {"code": code})
        assert resp.status_code == 405, (
            f"{method.upper()} on {CHECK_PATH} must be rejected (POST-only), "
            f"got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# Valid code → {"valid": true}, OTP untouched, login NOT performed
# ---------------------------------------------------------------------------

class TestCheckValidCode:
    def test_valid_code_returns_json_true(self):
        client = Client()
        code = _start_verification(client, "checkok@example.com")

        resp = _check(client, code)

        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("application/json")
        assert json.loads(resp.content) == {"valid": True}

    def test_valid_check_does_not_log_in(self):
        client = Client()
        code = _start_verification(client, "checknologin@example.com")

        _check(client, code)

        assert PARENT_ACCOUNT_SESSION_KEY not in client.session, (
            "auto-check must NOT authenticate the session"
        )
        assert client.session.get("pending_verification_email") == (
            "checknologin@example.com"
        ), "auto-check must leave the pending session key intact"

    def test_valid_check_does_not_consume_or_mutate_the_otp(self):
        client = Client()
        email = "checkotp@example.com"
        code = _start_verification(client, email)

        _check(client, code)

        record = EmailVerificationCode.objects.get(email=email)
        assert record.used_at is None, "auto-check must not mark the code used"
        assert not ParentAccount.objects.filter(email=email).exists(), (
            "auto-check must not create the ParentAccount (that happens on "
            "form verification only)"
        )

    def test_form_verification_still_succeeds_after_check(self):
        """The headline regression: check first, then submit the form —
        same code still logs in and redirects to /portal/."""
        client = Client()
        email = "checkthenform@example.com"
        code = _start_verification(client, email)

        check_resp = _check(client, code)
        assert json.loads(check_resp.content) == {"valid": True}

        form_resp = client.post(VERIFY_FORM_PATH, {"code": code})
        assert form_resp.status_code == 302, (
            "code was consumed/mutated by the auto-check "
            f"(form got {form_resp.status_code})"
        )
        assert "/portal/" in form_resp.url, form_resp.url
        account = ParentAccount.objects.get(email=email)
        assert client.session[PARENT_ACCOUNT_SESSION_KEY] == account.pk


# ---------------------------------------------------------------------------
# Failure paths → identical generic JSON, no login, no leakage
# ---------------------------------------------------------------------------

class TestCheckFailurePaths:
    def test_missing_session_returns_generic_failure(self):
        """A real active code must still fail when this session has no
        pending_verification_email."""
        owner = Client()
        code = _start_verification(owner, "nosession@example.com")

        stranger = Client()
        resp = stranger.post(reverse(CHECK_URL_NAME), {"code": code})

        _assert_generic_failure(resp)
        assert PARENT_ACCOUNT_SESSION_KEY not in stranger.session

    @pytest.mark.parametrize(
        "bad_code,email",
        [
            ("", "malformed-empty@example.com"),
            ("12345", "malformed-five@example.com"),
            ("1234567", "malformed-seven@example.com"),
            ("abcdef", "malformed-alpha@example.com"),
            ("12a456", "malformed-mixed@example.com"),
            ("123 456", "malformed-space@example.com"),
            ("0000000", "malformed-zeros@example.com"),
        ],
        ids=["empty", "five-digits", "seven-digits", "alpha", "mixed",
             "inner-space", "seven-zeros"],
    )
    def test_empty_or_malformed_code_returns_generic_failure(
        self, bad_code: str, email: str
    ):
        client = Client()
        _start_verification(client, email)  # real code exists

        resp = _check(client, bad_code)

        _assert_generic_failure(resp)
        assert PARENT_ACCOUNT_SESSION_KEY not in client.session

    def test_wrong_code_returns_generic_failure_without_consuming_real_code(self):
        client = Client()
        email = "wrongcode@example.com"
        real_code = _start_verification(client, email)

        bad = "000000" if real_code != "000000" else "000001"
        resp = _check(client, bad)

        _assert_generic_failure(resp)
        assert EmailVerificationCode.objects.get(email=email).used_at is None
        # Real code still verifies through the form afterwards.
        form_resp = client.post(VERIFY_FORM_PATH, {"code": real_code})
        assert form_resp.status_code == 302

    def test_code_for_different_email_returns_generic_failure(self):
        client = Client()
        _start_verification(client, "session-owner@example.com")
        other_code = issue_one_time_code("someone-else@example.com")

        resp = _check(client, other_code)

        _assert_generic_failure(resp)
        assert EmailVerificationCode.objects.get(
            email="someone-else@example.com"
        ).used_at is None

    def test_expired_code_returns_generic_failure(self):
        client = Client()
        email = "expiredcheck@example.com"
        code = _start_verification(client, email)
        _expire_codes(email)

        resp = _check(client, code)

        _assert_generic_failure(resp)
        assert PARENT_ACCOUNT_SESSION_KEY not in client.session

    def test_used_code_returns_generic_failure(self):
        client = Client()
        email = "usedcheck@example.com"
        code = _start_verification(client, email)
        _consume_codes(email)  # simulate the form having consumed it already

        resp = _check(client, code)

        _assert_generic_failure(resp)

    def test_expired_and_used_and_wrong_share_identical_response(self):
        """Lifecycle-indistinguishable: no signal that lets a caller tell
        an expired code apart from a used or wrong one."""
        responses = []

        c1 = Client()
        e1 = "lifecycle1@example.com"
        code1 = _start_verification(c1, e1)
        _expire_codes(e1)
        responses.append(_check(c1, code1))
        _consume_codes(e1)
        responses.append(_check(c1, code1))

        c2 = Client()
        _start_verification(c2, "lifecycle2@example.com")
        responses.append(_check(c2, "999999"))

        bodies = {r.content for r in responses}
        assert len(bodies) == 1, f"failure responses leaked lifecycle detail: {bodies}"
        for r in responses:
            _assert_generic_failure(r)


# ---------------------------------------------------------------------------
# CSRF protection (real Django middleware, enforcing client)
# ---------------------------------------------------------------------------

class TestCheckEndpointCsrf:
    def _pending_client(self, email: str) -> tuple[Client, str]:
        client = Client(enforce_csrf_checks=True)
        code = issue_one_time_code(email)
        session = client.session
        session["pending_verification_email"] = email
        session.save()
        return client, code

    def test_post_without_csrf_token_is_rejected(self):
        client, code = self._pending_client("csrfmissing@example.com")

        resp = client.post(reverse(CHECK_URL_NAME), {"code": code})

        assert resp.status_code == 403, (
            "endpoint must be CSRF-protected; token-less POST returned "
            f"{resp.status_code}"
        )
        assert EmailVerificationCode.objects.filter(
            email="csrfmissing@example.com", used_at__isnull=True
        ).exists(), "rejected request must not touch the code"

    def test_post_with_csrf_token_succeeds(self):
        """CSRF is enforced, not bypassed: the same client with a proper
        cookie+header token gets the JSON verdict."""
        client, code = self._pending_client("csrfok@example.com")
        page = client.get(VERIFY_FORM_PATH)  # mint the csrftoken cookie
        assert page.status_code == 200
        token = client.cookies["csrftoken"].value

        resp = client.post(
            reverse(CHECK_URL_NAME), {"code": code}, HTTP_X_CSRFTOKEN=token
        )

        assert resp.status_code == 200, (
            f"CSRF-token-bearing POST must pass middleware, got {resp.status_code}"
        )
        assert json.loads(resp.content) == {"valid": True}

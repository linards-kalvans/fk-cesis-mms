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
from hashlib import sha256

import pytest
from django.core import mail
from django.core.exceptions import FieldDoesNotExist
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import EmailVerificationCode, ParentAccount
from apps.accounts.services import (
    is_one_time_code_valid,
    issue_one_time_code,
    verify_one_time_code,
)
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
        """CSRF client whose session is persisted first, then issued an
        OTP bound to that same session key (approved design: endpoint
        session scoping must accept the origin session's own code)."""
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session.save()
        origin_key = session.session_key
        assert origin_key, "client session must be persisted before issuing the OTP"
        code = issue_one_time_code(email, origin_session_key=origin_key)
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


# ===========================================================================
# OTP duplicate-submit fix — session-bound codes (RED for approved design)
#
# Approved contract under test (NOT yet implemented):
#   * EmailVerificationCode.origin_session_key — nullable, indexed,
#     max_length 40 (small migration).
#   * issue_one_time_code(email, *, origin_session_key=...) persists it.
#   * is_one_time_code_valid(email, code, *, origin_session_key=...) only
#     accepts an active, unused code belonging to that session.
#   * verify_one_time_code(email, code, *, origin_session_key=...) is
#     atomic-row-locked and idempotent ONLY for an unexpired code bound to
#     the same session: first call consumes, repeat returns the same
#     ParentAccount; another session gets ValueError.
#   * verify view + check endpoint pass the current session key.
# ===========================================================================

ORIGIN_KEY_A = "originsessionkeyaaaa0000000001"
ORIGIN_KEY_B = "othersessionkeybbbb0000000002"


class TestOtpSessionBindingService:
    """issue_* persists the origin session key; storage stays hashed."""

    def test_issue_persists_origin_session_key(self):
        email = "issuebind@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        assert re.fullmatch(r"\d{6}", code), "issue must still return the raw code"
        record = EmailVerificationCode.objects.get(email=email)
        assert record.origin_session_key == ORIGIN_KEY_A, (
            "issue_one_time_code must persist the originating session key "
            "on the EmailVerificationCode row"
        )

    def test_model_field_nullable_maxlength_40_indexed(self):
        try:
            field = EmailVerificationCode._meta.get_field("origin_session_key")
        except FieldDoesNotExist:
            pytest.fail(
                "EmailVerificationCode must gain an origin_session_key field "
                "(nullable CharField, max_length=40, indexed) via a small "
                "migration — approved OTP duplicate-submit design"
            )
        assert field.null is True, "origin_session_key must be nullable"
        assert field.max_length == 40, "origin_session_key max_length must be 40"
        indexed = field.db_index or any(
            "origin_session_key" in idx.fields
            for idx in EmailVerificationCode._meta.indexes
        )
        assert indexed, "origin_session_key must be indexed"

    def test_service_stores_only_hash_never_plaintext(self):
        """No plaintext-OTP exposure: binding the session key must not
        weaken the hashed-at-rest posture.

        Deterministic assertions only — a raw 6-digit OTP can appear
        coincidentally inside a SHA-256 hex digest, so scanning stored
        hash text for the code substring is invalid.
        """
        email = "hashonly@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        record = EmailVerificationCode.objects.get(email=email)
        assert record.code_hash == sha256(code.encode()).hexdigest()
        assert record.code_hash != code
        attnames = {
            f.attname for f in EmailVerificationCode._meta.get_fields() if f.concrete
        }
        plaintext_otp_fields = attnames & {
            "code",
            "raw_code",
            "one_time_code",
            "otp",
            "plaintext_code",
        }
        assert not plaintext_otp_fields, (
            f"EmailVerificationCode must store no plaintext-OTP field: {plaintext_otp_fields}"
        )
        assert code not in str(record)


class TestIsOneTimeCodeValidSessionScoped:
    """Read-only validity is session-scoped."""

    def test_valid_only_for_origin_session(self):
        email = "validscope@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        assert is_one_time_code_valid(
            email, code, origin_session_key=ORIGIN_KEY_A
        ) is True, "active unused code must be valid in its own session"
        assert is_one_time_code_valid(
            email, code, origin_session_key=ORIGIN_KEY_B
        ) is False, (
            "a code bound to another session must never be valid here "
            "(duplicate-submit fix session scoping)"
        )

    def test_still_read_only_for_origin_session(self):
        email = "validreadonly@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        assert is_one_time_code_valid(
            email, code, origin_session_key=ORIGIN_KEY_A
        ) is True
        record = EmailVerificationCode.objects.get(email=email)
        assert record.used_at is None, "validity check must not consume"


class TestVerifyOneTimeCodeSameSessionIdempotency:
    """The heart of the duplicate-submit fix at service level."""

    def test_first_verify_consumes_and_returns_account(self):
        email = "idemfirst@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        account = verify_one_time_code(
            email, code, origin_session_key=ORIGIN_KEY_A
        )

        assert isinstance(account, ParentAccount)
        assert account.email == email
        record = EmailVerificationCode.objects.get(email=email)
        assert record.used_at is not None, "first verify must consume the code"

    def test_same_session_repeat_returns_same_account_not_error(self):
        """Concurrent/rapid double submit: both requests share one session
        key; the loser of the row lock must still get the account, not the
        generic invalid-code failure."""
        email = "idemrepeat@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        first = verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_A)
        second = verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_A)

        assert second.pk == first.pk, (
            "repeat same-session verify of a consumed, unexpired, "
            "same-session code must return the same ParentAccount "
            "(idempotency), not raise"
        )
        assert ParentAccount.objects.filter(email=email).count() == 1

    def test_expired_used_code_not_idempotent_for_same_session(self):
        """Idempotency window is bounded by expiry: after the code expires
        even the origin session gets the generic failure again."""
        email = "idemexpired@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_A)
        _expire_codes(email)

        with pytest.raises(ValueError):
            verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_A)

    def test_expired_active_code_rejected_for_same_session(self):
        email = "expiredbefore@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)
        _expire_codes(email)

        with pytest.raises(ValueError):
            verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_A)
        assert not ParentAccount.objects.filter(email=email).exists()


class TestVerifyOneTimeCodeCrossSessionRejected:
    """Another session/device must never gain reuse."""

    def test_foreign_session_rejected_after_use(self):
        email = "foreignused@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)
        verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_A)

        with pytest.raises(ValueError):
            verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_B)

    def test_foreign_session_cannot_preempt_active_bound_code(self):
        """An active code bound to session A must be generically invalid
        for session B — and must NOT be consumed there (A can still use
        it in its own session)."""
        email = "foreignactive@example.com"
        code = issue_one_time_code(email, origin_session_key=ORIGIN_KEY_A)

        with pytest.raises(ValueError):
            verify_one_time_code(email, code, origin_session_key=ORIGIN_KEY_B)

        record = EmailVerificationCode.objects.get(
            email=email, code_hash=sha256(code.encode()).hexdigest()
        )
        assert record.used_at is None, (
            "a rejected foreign-session verify must not consume the code"
        )
        assert not ParentAccount.objects.filter(email=email).exists(), (
            "foreign session must not obtain a ParentAccount from a "
            "code bound to another session"
        )
        # The origin session can still verify normally afterwards.
        account = verify_one_time_code(
            email, code, origin_session_key=ORIGIN_KEY_A
        )
        assert account.email == email


class TestCheckEndpointSessionScoped:
    """Endpoint/session scoping with real clients + real /register/ flow."""

    def test_check_rejects_code_bound_to_foreign_session(self):
        owner = Client()
        email = "scopedcheck@example.com"
        code = _start_verification(owner, email)  # bound to owner's session

        stranger = Client()
        resp = stranger.post(ENTRY_PATH, {"email": email})
        assert resp.status_code == 302, "stranger needs its own pending email"

        check = stranger.post(reverse(CHECK_URL_NAME), {"code": code})
        assert json.loads(check.content) == FAILURE_PAYLOAD, (
            "a code bound to another session must be generically invalid "
            f"at the check endpoint, got: {check.content!r}"
        )

    def test_check_same_session_used_code_stays_generic_failure(self):
        """Even the origin session must not see a consumed code as valid
        through the read-only check endpoint."""
        client = Client()
        email = "scopedused@example.com"
        code = _start_verification(client, email)

        assert json.loads(_check(client, code).content) == {"valid": True}
        form_resp = client.post(VERIFY_FORM_PATH, {"code": code})
        assert form_resp.status_code == 302

        _assert_generic_failure(_check(client, code))


class TestVerifyViewDuplicateSubmit:
    """View-level acceptance with real clients."""

    def test_resubmit_same_session_after_consumption_redirects_to_portal(self):
        """Acceptance: same browser session, code already consumed by the
        first submit (e.g. the second request of a duplicate double-click
        whose session snapshot still carried the pending email) must land
        on the portal redirect, NOT the generic invalid-code page."""
        client = Client()
        email = "dupsubmit@example.com"
        code = _start_verification(client, email)

        first = client.post(VERIFY_FORM_PATH, {"code": code})
        assert first.status_code == 302 and "/portal/" in first.url, first.url

        second = client.post(VERIFY_FORM_PATH, {"code": code})
        assert second.status_code == 302, (
            "second same-session submit of the same valid code must be "
            f"idempotent (redirect), got {second.status_code}: "
            f"{second.content.decode()[:200] if second.status_code == 200 else ''}"
        )
        assert "/portal/" in second.url, second.url

        account = ParentAccount.objects.get(email=email)
        assert ParentAccount.objects.filter(email=email).count() == 1
        assert client.session[PARENT_ACCOUNT_SESSION_KEY] == account.pk

    def test_second_session_cannot_verify_first_sessions_active_code(self):
        """Cross-device reuse is impossible: B (with its own pending
        session for the same email) submitting A's still-active code must
        get the generic invalid page, no login, and must not consume or
        bypass it — A can still verify in its own session."""
        email = "crossdevice@example.com"
        a = Client()
        code_a = _start_verification(a, email)

        b = Client()
        resp = b.post(ENTRY_PATH, {"email": email})
        assert resp.status_code == 302

        verify_b = b.post(VERIFY_FORM_PATH, {"code": code_a})
        assert verify_b.status_code in (200, 400), (
            f"foreign-session verify must not succeed, got {verify_b.status_code}"
        )
        content = verify_b.content.decode()
        assert "Nederīgs vai noilgušs kods" in content, content[:300]
        assert PARENT_ACCOUNT_SESSION_KEY not in b.session
        assert not ParentAccount.objects.filter(email=email).exists()
        code_a_record = EmailVerificationCode.objects.get(
            email=email, code_hash=sha256(code_a.encode()).hexdigest()
        )
        assert code_a_record.used_at is None

        verify_a = a.post(VERIFY_FORM_PATH, {"code": code_a})
        assert verify_a.status_code == 302 and "/portal/" in verify_a.url

    def test_used_code_stays_generically_invalid_in_other_session(self):
        """Regression guard: a code consumed in session A must keep the
        current generic invalid behavior for session B (never idempotent
        there)."""
        email = "usedother@example.com"
        a = Client()
        code_a = _start_verification(a, email)
        assert a.post(VERIFY_FORM_PATH, {"code": code_a}).status_code == 302

        b = Client()
        assert b.post(ENTRY_PATH, {"email": email}).status_code == 302
        resp = b.post(VERIFY_FORM_PATH, {"code": code_a})
        assert resp.status_code in (200, 400)
        assert "Nederīgs vai noilgušs kods" in resp.content.decode()
        assert PARENT_ACCOUNT_SESSION_KEY not in b.session

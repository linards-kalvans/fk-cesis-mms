# Verification Code Auto-check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically preflight a six-digit registration verification code, including pasted codes, then submit the existing verification form on success.

**Architecture:** A read-only Django endpoint checks the session-bound OTP without consuming it. A small page-specific script calls that endpoint from the code input's `input` event; only an accepted response invokes the current form submission, which retains ownership of consumption, login, analytics, and redirect behavior.

**Tech Stack:** Django 5, pytest/pytest-django, vanilla browser JavaScript, Django static files.

---

### Task 1: Server-side read-only preflight

**Files:**
- Modify: `apps/accounts/services.py`
- Modify: `apps/accounts/views.py`
- Modify: `fk_cesis_mms/urls.py`
- Test: `tests/accounts/test_verify_code_check_endpoint.py`

- [ ] Add a failing service/view test proving an active code reports valid without setting `used_at`; wrong, expired, missing-session, and malformed code report the generic invalid response.
- [ ] Run targeted tests and confirm red phase before implementation.
- [ ] Add `is_one_time_code_valid(email: str, code: str) -> bool`, using the same email, code hash, unused, and expiry semantics as `verify_one_time_code` without any write.
- [ ] Add a CSRF-protected POST-only `verify_one_time_code_check_view` returning `{ "valid": true }` or `{ "valid": false, "error": "Nederīgs vai noilgušs kods." }`; add named route `register-verify-check` at `register/verify/check/`.
- [ ] Re-run targeted tests and confirm green phase.

### Task 2: Verification-page auto-check behavior

**Files:**
- Modify: `templates/registrations/verify_code.html`
- Create: `static/js/verify_code.js`
- Test: `tests/registrations/test_visual_contract.py` or focused `tests/registrations/test_verify_code_autocheck.py`

- [ ] Add failing template/static-source tests for form hooks, error live region, CSRF-aware endpoint reference, `input` handling, six-digit gate, request lock, error retention, and `requestSubmit()` success handoff.
- [ ] Run targeted tests and confirm red phase.
- [ ] Add minimal semantic `data-*` hooks and an initially empty inline `aria-live="polite"` error region. Load the page-specific static script through `extra_js`.
- [ ] Implement the script: listen for `input` (therefore paste/autofill); require `/^\d{6}$/`; avoid overlapping checks for same value; POST URL-encoded `code` plus CSRF token; preserve value and show generic Latvian retry/invalid error on failure; call `form.requestSubmit()` only after a valid reply.
- [ ] Re-run targeted tests and confirm green phase.

### Task 3: Verification

**Files:**
- No production files beyond Tasks 1–2.

- [ ] Run focused accounts and registration tests.
- [ ] Run `uv run pytest -q -m "not slow"`, `uv run ruff check .`, `uv run mypy .`, and `uv run python manage.py makemigrations --check`.
- [ ] Confirm no migration, OTP issuance, rate-limit, portal, or unrelated parent-flow behavior changes.

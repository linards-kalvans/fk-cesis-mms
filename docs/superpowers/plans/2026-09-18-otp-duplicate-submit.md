# OTP duplicate-submit implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind newly issued browser OTPs to the originating Django session and make same-session replay of a consumed-but-unexpired code idempotent, eliminating the double-submit race.

**Architecture:** A nullable `origin_session_key` field on `EmailVerificationCode` stores the Django session key. The lookup in `verify_one_time_code` and `is_one_time_code_valid` is scoped to the caller's session key. The view passes `request.session.session_key` to both services. The JS script owns the submit event to prevent a second POST from reaching the server.

**Tech Stack:** Django 5, pytest/pytest-django, vanilla browser JavaScript, Django static files.

---

### Task 1: Database migration

**Files:**
- Create: `apps/accounts/migrations/0006_emailverificationcode_origin_session_key.py`
- Modify: `apps/accounts/models.py`

- [ ] Add `origin_session_key = CharField(max_length=40, null=True, blank=True, db_index=True)` to `EmailVerificationCode`.
- [ ] Run `uv run python manage.py makemigrations --check` — confirm clean (migration already exists, this validates the schema match).
- [ ] Run `uv run pytest -q` — confirm baseline green before changes.

---

### Task 2: Service layer — session-scoped OTP lookup

**Files:**
- Modify: `apps/accounts/services.py`

- [ ] Add `_code_session_scope(origin_session_key: str | None) -> Q`: when `origin_session_key` is provided, returns `Q(origin_session_key=origin_session_key) | Q(origin_session_key__isnull=True)`; when `None`, returns `Q(origin_session_key__isnull=True)`.
- [ ] Update `issue_one_time_code(email, *, origin_session_key=None)` to persist `origin_session_key` on the created `EmailVerificationCode`.
- [ ] Update `is_one_time_code_valid(email, code, *, origin_session_key=None)` to filter with `_code_session_scope(origin_session_key)` — same semantics as verify, no writes.
- [ ] Update `verify_one_time_code(email, code, *, origin_session_key=None)`:
  - Wrap the entire function body in `@transaction.atomic`.
  - Use `select_for_update()` on the ORM query.
  - Add `_code_session_scope(origin_session_key)` to the filter.
  - After `used_at is not None`, add an idempotent-replay branch: when `origin_session_key is not None` and `record.origin_session_key == origin_session_key`, return the `ParentAccount` (get_or_create) instead of raising. Legacy NULL-bound rows and foreign sessions still raise.

---

### Task 3: View layer — pass session key

**Files:**
- Modify: `apps/accounts/views.py`

- [ ] In `verify_one_time_code_view`: pass `origin_session_key=request.session.session_key` to `verify_one_time_code()`.
- [ ] In `verify_one_time_code_check_view`: pass `origin_session_key=request.session.session_key` to `is_one_time_code_valid()`.

---

### Task 4: Frontend — duplicate-submit guard

**Files:**
- Create/Modify: `static/js/verify_code.js`

- [ ] Add a `submit` event listener on the form that blocks any submission beyond the first.
- [ ] State machine: `idle → checking (preflight in flight, UI locked) → submitting (valid verdict handoff) | idle (invalid/network)`.
- [ ] A valid preflight arms a one-shot `allowProgrammaticSubmit` flag; the submit listener allows exactly one `form.requestSubmit()` then sets `submitting = true`.
- [ ] Manual clicks/Enter while `inFlight` or `submitting` are prevented via `event.preventDefault()`.
- [ ] Invalid verdict or network failure restores editable state (unlocks button + input).
- [ ] Stale verdicts (digits edited while request in flight) are discarded without submitting or showing error; the live input value gets its own check once the request settles.

---

### Task 5: Tests

**Files:**
- Modify: `tests/accounts/test_verify_code_check_endpoint.py`

- [ ] `TestOtpSessionBindingService.test_issue_persists_origin_session_key` — code issued with `origin_session_key` stores it.
- [ ] `TestOtpSessionBindingService.test_model_field_nullable_maxlength_40_indexed` — schema contract.
- [ ] `TestOtpSessionBindingService.test_service_stores_only_hash_never_plaintext` — no plaintext OTP field.
- [ ] `TestIsOneTimeCodeValidSessionScoped.test_valid_only_for_origin_session` — same session returns true, foreign returns false.
- [ ] `TestVerifyOneTimeCodeSameSessionIdempotency.test_first_verify_consumes_and_returns_account` — first call consumes, returns account.
- [ ] `TestVerifyOneTimeCodeSameSessionIdempotency.test_same_session_repeat_returns_same_account_not_error` — concurrent double submit: loser gets account, not ValueError.
- [ ] `TestVerifyOneTimeCodeSameSessionIdempotency.test_expired_used_code_not_idempotent_for_same_session` — idempotency bounded by expiry.
- [ ] `TestVerifyOneTimeCodeCrossSessionRejected.test_foreign_session_rejected_after_use` — foreign session gets ValueError.
- [ ] `TestVerifyOneTimeCodeCrossSessionRejected.test_foreign_session_cannot_preempt_active_bound_code` — foreign session cannot consume an active bound code.
- [ ] `TestCheckEndpointSessionScoped.test_check_rejects_code_bound_to_foreign_session` — check endpoint returns generic failure for foreign session.
- [ ] `TestVerifyViewDuplicateSubmit.test_resubmit_same_session_after_consumption_redirects_to_portal` — acceptance: second POST returns 302 to portal.
- [ ] `TestVerifyViewDuplicateSubmit.test_second_session_cannot_verify_first_sessions_active_code` — cross-device reuse impossible.
- [ ] `TestVerifyViewDuplicateSubmit.test_used_code_stays_generically_invalid_in_other_session` — consumed code stays invalid for other session.

---

### Task 6: Verification

**Files:**
- No production files beyond Tasks 1–5.

- [ ] Run focused accounts tests: `uv run pytest tests/accounts/test_verify_code_check_endpoint.py -q` — confirm green.
- [ ] Run full fast lane: `uv run pytest -q -m "not slow"` — confirm green.
- [ ] Run `uv run ruff check .` — confirm clean.
- [ ] Run `uv run mypy .` — confirm clean (may require a single typing adjustment for the `origin_session_key` parameter).
- [ ] Run `uv run python manage.py makemigrations --check` — confirm no pending migrations.
- [ ] Confirm no migration, OTP issuance, rate-limit, portal, or unrelated parent-flow behavior changes.

---

### Verification evidence

- Focused accounts tests: **105 passed** (all session-scoping + idempotency + view-level acceptance).
- Full pytest initial gate: **2598 passed**.
- `ruff check .`: clean.
- `mypy .`: clean (after single test typing adjustment).
- `makemigrations --check`: clean (migration committed).
- Concurrent DB row locking guarantee (`select_for_update()`) applies to PostgreSQL; SQLite does not enforce `select_for_update` — the reuse path is validated sequentially.

---

### Out of scope

- General OTP attempt rate limiting or oracle mitigation.
- Analytics event de-duplication.
- OTP TTL or code-format changes.

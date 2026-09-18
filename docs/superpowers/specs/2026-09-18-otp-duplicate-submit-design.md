# OTP duplicate-submit design

## Goal

Eliminate the race condition where a parent's browser issues two verification
POSTs for the same OTP — one 200 (generic "invalid code") and one 302
(redirect to `/portal/`) — within ~160 ms. The fix binds newly issued browser
OTPs to the originating Django session and makes same-session replay of a
consumed-but-unexpired code idempotent at the service layer.

## Production incident evidence

A valid preflight was followed by two verification POSTs:

| # | Endpoint | Method | Status | Latency |
|---|----------|--------|--------|---------|
| 1 | `/register/verify/` | POST | 200 (generic error) | — |
| 2 | `/register/verify/` | POST | 302 (`/portal/`) | 160 ms after #1 |

The first POST consumed the OTP and logged the session in; the second POST
arrived while the session snapshot still carried `pending_verification_email`
and hit the "code already used" path, surfacing the generic invalid-code error
instead of the portal redirect.

## Root cause

`verify_code.js` (the auto-check script) calls `form.requestSubmit()` on a
valid preflight verdict. A manual button click or Enter keypress on the same
page races that programmatic submit. Both fire as independent POSTs to the
same endpoint. The first wins the row lock, consumes the OTP, and logs in.
The second arrives after consumption but before the session is cleared, hits
the `used_at is not None` branch, and raises `ValueError("Invalid code")`.

## Design

### Data model

`EmailVerificationCode.origin_session_key` — a nullable `CharField(max_length=40,
db_index=True)` storing the Django session key of the browser that requested
the code. Nullable so legacy rows issued before the binding keep their original
strict one-time semantics until normal expiry. No backfill is performed.

### Service: `verify_one_time_code`

The lookup is serialised with `select_for_update()` inside `transaction.atomic()`.
The session-scoped lookup is:

- **Caller has a session key:** accept rows bound to that exact key **plus**
  legacy NULL-bound rows (pre-binding codes keep prior behaviour).
- **Caller has no session key:** accept only legacy NULL-bound rows — a
  session-bound row is never verifiable without its origin session.

Within the expiry window, re-verifying an already-consumed code **from its own
origin session** is idempotent — it returns the same `ParentAccount` instead of
raising. This is the core duplicate-submit fix. Legacy NULL-bound rows and
codes bound to another session never get a second use.

### Service: `is_one_time_code_valid`

The read-only preflight mirrors the same session-scoped lookup semantics but
performs **no writes**: it never marks the code used, never creates an account,
and never mutates the session.

### Security

- **Same-session only:** a foreign session cannot consume or reuse a code bound
  to another session.
- **Expired codes:** idempotency is bounded by expiry. After expiry the origin
  session also gets the generic failure.
- **Plaintext OTP remains absent:** the fix only adds a session-key reference;
  the OTP hash-at-rest posture is unchanged.
- **Legacy NULL-bound rows:** keep strict one-time semantics. They are never
  retroactively bound and never get idempotent replay.

### Frontend state flow

```
idle → checking (six digits, preflight fired; button+input locked)
  → submitting (valid verdict handoff; page navigates)
  → idle (invalid verdict or network failure; button+input unlocked)
```

The script owns the button and input state. A `submit` event listener blocks
any duplicate manual submission. A valid preflight arms a one-shot pass that
allows exactly one `form.requestSubmit()`. Invalid or network failures restore
editable state so the parent can retry. The no-JS fallback stays native.

### View: `verify_one_time_code_view`

Passes `origin_session_key=request.session.session_key` to the service layer.
When `pending` is absent but the session already holds `PARENT_ACCOUNT_SESSION_KEY`
(the first submit logged in and cleared pending), the view redirects to the
portal — this is the safety net for the rare case where the service-layer
idempotency did not catch the race.

## Acceptance criteria

1. A valid preflight followed by two rapid POSTs: both return 302 to `/portal/`
   (no generic error page in the response stream).
2. A foreign session (different browser/device) can never consume or replay a
   session-bound OTP.
3. Expired consumed codes are no longer idempotent — even the origin session
   gets the generic failure.
4. Legacy NULL-bound OTP rows keep strict one-time semantics.
5. The manual submit path works unchanged with JavaScript disabled.
6. No plaintext OTP is stored or exposed by the binding mechanism.

## Out of scope

- General OTP attempt rate limiting or oracle mitigation.
- Analytics event de-duplication.
- OTP TTL or code-format changes.

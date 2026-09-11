# Verification-code auto-check design

## Goal

Validate a parent registration one-time code automatically when six digits are
entered or pasted, without consuming it before the existing login submission.

## Scope

Applies only to `/register/verify/`. The existing manual submit path remains
the no-JavaScript and retry fallback. OTP issuance, expiry, rate limiting,
email content, and `/portal/` presentation are unchanged.

## Flow

```text
input or paste -> exactly six digits -> AJAX preflight
                                      -> invalid: inline Latvian error, retain input
                                      -> valid: normal form POST
                                                -> consume OTP, log in, redirect /portal/
```

## Design

`POST /register/verify/check/` receives `code` under the normal Django CSRF
contract. It reads the session's `pending_verification_email` and returns JSON:
`{"valid": true}` for an active matching code, otherwise
`{"valid": false, "error": "Nederīgs vai noilgušs kods."}`. The check does
not mutate the verification-code row or session.

The browser script listens to the code input's `input` event. This captures
ordinary typing, paste, mobile OTP autofill, and similar value insertion. It
only requests a check for six ASCII digits, prevents overlapping checks, shows
an inline live-region error on rejection, and uses `form.requestSubmit()` after
a valid result. The normal existing POST remains the only operation that
consumes a code, creates/logs in an account, records analytics, and redirects.

## Security and error handling

The preflight response uses the same generic invalid-or-expired wording as the
existing form. It does not expose account state or code lifecycle detail.
Requests remain CSRF-protected. Network failures retain entered digits and show
a generic inline retry error; manual submit remains available.

## Acceptance criteria

1. Entering or pasting exactly six digits starts one AJAX preflight request.
2. A valid preflight does not consume the code, then submits the existing form
   normally and reaches the existing `/portal/` redirect.
3. An invalid or expired result displays a Latvian inline error and preserves
   the entered code.
4. The manual submit flow remains functional with JavaScript disabled.
5. No preflight response leaks account or OTP lifecycle details.

# Parent Identity Verification Design

**Date:** 2026-05-05
**Status:** Approved — security design for parent identity binding
**Reference:** Brainstorming outcome approved by project owner
**Related:** `docs/superpowers/specs/2026-05-05-registration-design-and-integrations-design.md`

---

## 1. Problem Statement

### Current Security Issue

The current registration draft flow auto-links a `ParentAccount` when a typed email matches an existing account. This creates two problems:

1. **Identity-binding flaw:** Any user who can see the registration form and type an email address belonging to another person can cause that person's existing registrations to become visible in the draft-editing session. The typed email is treated as proof of ownership without verification.
2. **Unauthorized cross-registration visibility:** A user in a different browser or after logout can access registrations that belong to a different parent simply by re-typing the email address.

This is a real security bug in the current design. Typed email must not be treated as ownership proof.

### Risks in Current Design

- A malicious or curious user can discover registrations belonging to another parent by guessing or reusing an email address.
- Draft data from one parent can be silently associated with another parent's account.
- No verification step exists before granting account-wide registration visibility.

---

## 2. Approved Target Model

The system must enforce **two distinct layers**:

| Layer | Purpose | Access Condition |
|---|---|---|
| **Unverified draft layer** | Browser/session-bound draft storage. Stores a *claimed* email address. | Available to any anonymous or returning user in the same browser session. |
| **Verified parent identity layer** | Account-wide visibility of all registrations belonging to the parent. | Available only after verified identity (email code/link, or future social login). |

### Core Principles

1. **Typed email is a claim, not proof of ownership.** The system must never auto-link a `ParentAccount` based on an email address alone.
2. **Portal access is based on verified identity only.** A parent can see all their registrations only after completing a verified authentication step.
3. **Draft ownership is separate from verified account ownership.** Browser-session drafts are not automatically promoted to account-wide visibility.
4. **Email delivery architecture is separate from the identity model.** The mechanism for sending verification codes/links (SMTP, API provider, debug preview) is an infrastructure concern. The identity gate is a domain concern.
5. **Future social login can satisfy the same verified-identity gate.** Any provider that confirms email ownership (or other identity assertion) can unlock the verified parent identity layer.

---

## 3. User Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Anonymous user visits /register/                          │
│    → Can fill form, save draft                               │
│    → Typed email stored as "claimed_email" on draft          │
│    → NO ParentAccount lookup or linking                      │
├─────────────────────────────────────────────────────────────┤
│ 2. Same browser session continues editing                    │
│    → Can return to draft without verification                │
│    → Can submit application                                  │
│    → Submitted application is view-only (cannot edit)        │
├─────────────────────────────────────────────────────────────┤
│ 3. User requests portal access (same or different browser)  │
│    → System sends verification code/link to claimed email    │
│    → User enters code or clicks link                         │
│    → On success: verified parent identity created/linked     │
│    → Verified parent sees ALL registrations for that email   │
├─────────────────────────────────────────────────────────────┤
│ 4. Different browser/device                                  │
│    → Can continue editing draft (same claimed_email)         │
│    → Requires verification to unlock account-wide access     │
│    → After verification: same verified identity as step 3    │
└─────────────────────────────────────────────────────────────┘
```

### Flow Details

- **Step 1 — Anonymous draft creation:** User fills registration form. On save-draft, system stores the form data and the claimed email address on a `RegistrationApplication` with `status=draft`. No `ParentAccount` is created or looked up.
- **Step 2 — Same-browser continuity:** User returns to the same browser, navigates to their draft. System resolves the draft by session + claimed email (or session token). User can continue editing or submit. Submitted applications are view-only.
- **Step 3 — Verification gate:** User clicks "My registrations" or similar portal entry. System sends a one-time verification code or magic link to the claimed email. User completes verification. System creates a `ParentAccount` (if none exists) or links to existing one. Verified parent identity now unlocks full registration visibility.
- **Step 4 — Cross-device:** Same flow as step 3. Different browser cannot access draft without the claimed email + verification.

---

## 4. Architecture

### Data Model Changes

```
RegistrationApplication
  - claimed_email: EmailField (nullable, stores typed email for draft)
  - verified_parent: ForeignKey to ParentAccount (nullable, set after verification)
  - status: draft | submitted | approved | rejected

ParentAccount
  - email: EmailField (unique, verified)
  - is_verified: BooleanField (derived from successful auth)
  - registrations: reverse relation via verified_parent on RegistrationApplication
```

### Key Rules

- `claimed_email` is set on draft save. It is **never** used to look up or link a `ParentAccount`.
- `verified_parent` is set only after successful verification (email code/link or social login).
- Portal queries filter by `verified_parent`, not by `claimed_email`.
- Draft resolution uses session token + `claimed_email` for same-browser continuity.

### Authentication / Verification Layer

```
VerificationService
  - send_verification_email(email) -> sends code/link via delivery adapter
  - verify_code(email, code) -> bool
  - verify_magic_link(token) -> bool

EmailDeliveryAdapter (protocol/ABC)
  - send(to: str, subject: str, body: str) -> None

  Concrete implementations:
    - DebugPreviewDeliveryAdapter  (dev only, logs email content)
    - SmtpDeliveryAdapter          (SMTP relay, production)
    - ApiDeliveryAdapter           (third-party API provider, production)
```

### Provider Configuration

- Email delivery provider is configured via environment variables (`EMAIL_BACKEND`, `SMTP_HOST`, `API_KEY`, etc.).
- Debug preview adapter is active only when `DEBUG=True`.
- Provider switching requires no domain-model changes — only adapter configuration.

---

## 5. Implementation Steps (Incremental, Safe)

1. **Stop auto-linking ParentAccount by typed email.** Remove the email-lookup-and-link logic from draft save. Keep `claimed_email` on the draft model.
2. **Add `verified_parent` field to `RegistrationApplication`.** Migrate existing data: set to `NULL` for all current drafts.
3. **Update portal views to query by `verified_parent`.** Remove `claimed_email`-based visibility from portal queries.
4. **Implement verification flow:** email code or link, using the delivery adapter abstraction.
5. **On successful verification:** create or link `ParentAccount`, set `verified_parent` on matching drafts, grant account-wide visibility.
6. **Same-browser draft continuity:** resolve drafts by session token + `claimed_email` for returning anonymous users.
7. **Cross-device handling:** if user verifies from a different browser, link verified identity to existing drafts with matching `claimed_email`.

### Safety Guarantees

- No existing data is exposed during migration.
- Portal access is strictly gated behind verification.
- Drafts remain accessible in the originating browser session without verification.
- Verification tokens are single-use, short-TTL, and rate-limited.

---

## 6. Acceptance Criteria

- [ ] Typing an existing parent's email on a new draft does **not** auto-link or expose that parent's registrations.
- [ ] Anonymous user can save and resume a draft in the same browser without any verification step.
- [ ] A verified parent can see all registrations associated with their verified email address.
- [ ] A different browser/device cannot access a draft without the claimed email and verification.
- [ ] Portal queries use `verified_parent`, never `claimed_email`, for registration visibility.
- [ ] Email delivery is abstracted behind a provider interface; debug preview works in `DEBUG=True` only.
- [ ] Social login (when implemented) can satisfy the same verified-identity gate and unlock account-wide access.
- [ ] Verification tokens are single-use, expire within 15 minutes, and are rate-limited.

---

## 7. Future Considerations

- **Social login:** Google, Facebook, or other OAuth providers can satisfy the verified-identity gate. The provider returns a confirmed email address, which unlocks the verified parent layer. The same `ParentAccount` linking logic applies.
- **Multi-email accounts:** A parent may have multiple verified emails. Design should allow adding secondary verified emails to an existing `ParentAccount`.
- **GDPR:** Verification emails contain time-limited tokens. Token storage and deletion must comply with data retention policies.

# P19 — Daily Submitted-Registration Digest: Design

**Date:** 2026-07-27
**Status:** Approved — implementation landed and code review accepted. CI exposed a PostgreSQL lock regression; its root-cause fix passed the full CI-equivalent PostgreSQL suite locally (1855 tests) on 2026-07-27. GitHub CI rerun and LAN acceptance pending.

## 1. Problem

Staff responsible for reviewing registration applications have no proactive notification when new applications are submitted. They must manually check the admin changelist. For a growing club with multiple reviewers, this creates a gap where submissions can sit unreviewed until someone visits the admin UI.

## 2. Requirements

| # | Requirement |
|---|-------------|
| R1 | Once daily, send one plain-text email to configured active staff summarising every submitted application that has not yet been included in a digest. |
| R2 | The email lists child name, guardian name, submission date/time (Riga local), current status, and an admin link per application. |
| R3 | The email contains only the required child and guardian names, submission time, status, and admin link; it omits contact, identity-document, address, and review-message data. |
| R4 | Every initial submit and every correction (fix → resubmit) clears the per-row delivery flag so the next day's digest includes the event. |
| R5 | The email is sent Bcc to all configured recipients so no recipient sees the others. |
| R6 | Staff select recipients in Django admin (active staff Users only). |
| R7 | The digest job runs via a django-q2 daily Schedule, configurable in admin (default 08:00 Riga). |
| R8 | On send failure (SMTP error, misconfiguration, no recipients), flags are **not** cleared — the job retries the next day. |
| R9 | Only superusers may view/change the singleton settings. |

## 3. Design Decisions

### 3.1 Per-row flag vs singleton-only

**Decision:** `RegistrationApplication.submission_digest_sent_at` nullable DateTimeField.

**Why:** A singleton flag would only track "was the last batch delivered?" — it would not distinguish which applications were included, and a correction resubmit (status flips `submitted → fix_requested → submitted`) would need a different mechanism to re-arm. A per-row flag is trivial (one column), survives status transitions naturally (cleared on every submit), and makes the data queryable (`WHERE submission_digest_sent_at IS NULL`) for ad-hoc staff checks.

### 3.2 Bcc, not To

**Decision:** All recipients in `bcc`.

**Why:** Staff who share a review queue should not see each other's email addresses. Bcc ensures one email, one body, zero exposure.

### 3.3 At-least-once delivery

**Decision:** Flags are cleared **only** on successful `EmailMessage.send()` returning `1`. On any failure (SMTP exception, `sent != 1`, no recipients, blank email), the job returns `0` and leaves flags untouched.

**Why:** This gives at-least-once semantics — if the SMTP server drops the message or the job crashes mid-send, the next daily run retries the same applications. The operator can verify delivery via the singleton `last_successful_at` timestamp. Duplicate emails (rare, from SMTP retry) are acceptable; lost submissions are not.

### 3.4 Status-agnostic selection

**Decision:** Selects all applications with `submitted_at IS NOT NULL` and `submission_digest_sent_at IS NULL`, regardless of current status.

**Why:** Applications transition `submitted → fix_requested → submitted → approved/rejected`. A correction resubmit clears the flag (R4). Filtering on a single status would miss applications that moved through intermediate states. The flag is the source of truth for "has this submission event been reported?"

### 3.5 Singleton settings with M2M recipients

**Decision:** One `RegistrationSubmissionDigestSettings` row (pk=1, seeded by migration), with a ManyToMany to active staff Users.

**Why:** A singleton is simpler than per-user preferences for a small club. M2M allows selecting multiple reviewers. The migration seeds the singleton so the job has a known default.

### 3.6 Data minimisation in the email body

**Decision:** The email template includes only: child name, guardian name, Riga submission datetime, current status display string, and the admin change-page URL.

**Why:** Names are necessary personal data for staff to identify the application. Staff already have admin access to full details, so the digest is a **notification**, not a replacement for the admin UI. Omitting contact details, PID, address, review content, and documents limits impact if a message is forwarded or retained in an inbox.

### 3.7 `select_for_update()` on pending rows

**Decision:** The job acquires row-level locks on the selected applications.

**Why:** Prevents two concurrent qcluster workers from both picking the same pending rows. The lock scope is narrow (only undelivered rows) and short-lived (only until the email sends).

### 3.8 No admin UI for the digest body

**Decision:** The email template is a plain-text file at `templates/emails/registrations/submission_digest.txt`. No admin settings for subject or body.

**Why:** The content is small (five fields per row) and unlikely to need frequent changes. Subject includes the count (`"Jauni iesniegtie pieteikumi (N)"`). If the template needs changes, a code deploy is the mechanism — appropriate for a club-level tool.

## 4. Data and State Flow

```
┌──────────────┐
│ Parent submits│
│ application   │
└──────┬───────┘
       │ submit_application()
       │ sets submitted_at, clears submission_digest_sent_at
       ▼
┌──────────────┐     django-q2 Schedule (daily)    ┌──────────────┐
│ Registration  │ ─────────────────────────────────►│ send_digest  │
│ Application   │                                   │ task         │
│               │                                   │              │
│ submission_   │◄──────────────────────────────────│              │
│ digest_sent_  │    on success: stamp per-row       │              │
│ at: NULL      │    + singleton last_successful_at  │              │
└──────────────┘                                   └──────────────┘
                                                      │
                                                      │ EmailMessage(bcc=[…])
                                                      ▼
                                               ┌──────────────┐
                                               │ Staff inboxes│
                                               │ (Bcc hidden) │
                                               └──────────────┘
```

## 5. Security and Privacy

| Concern | Mitigation |
|---------|-----------|
| Personal data in email | Template limits content to names, datetime, status, and admin URL; it omits email, phone, PID, address, docs, and review messages. |
| Recipient exposure | Bcc — no recipient sees others. |
| Admin access to settings | `has_view_permission` and `has_change_permission` return `True` only for `is_superuser`. |
| Recipient selection | `limit_choices_to` + `formfield_for_manytomany` restrict to `is_active=True, is_staff=True`. |
| Audit trail | Digest sends do not create `AuditEvent` rows because routine automated success is out of the audit baseline scope. |
| Template rendering | Uses `render_to_string` (no request context), so no CSRF/session leakage. |

## 6. Operational Controls

| Control | Mechanism |
|---------|-----------|
| Schedule time | django-q2 `Schedule` row (`registrations-submission-digest`), editable in admin. Default: 08:00 Europe/Riga (migration seed). |
| Recipient management | Django admin → Registrations → Iesniegto pieteikumu kopsavilkuma iestatījumi. Superuser-only. |
| Delivery verification | Singleton `last_successful_at` in admin. Staff checks this to confirm the job ran. |
| Failure handling | Fixed ERROR messages contain no personal data. Pending flags stay untouched, so the next daily run retries. |
| Idempotency | Per-row flag ensures each submission event is reported once. Re-submissions re-arm the flag. |

## 7. Retry and At-Least-Once Caveat

The system provides **at-least-once** delivery semantics:

- If the SMTP server returns an error, flags stay `NULL` → next day retries.
- If `EmailMessage.send()` returns `0` (unexpected), flags stay `NULL` → next day retries.
- If the SMTP server *delivers* but the job crashes *after* `send()` returns `1` but *before* the DB update, the next run retries (the flag was never stamped).

**Acceptable duplicate:** In the rare case the SMTP server retries internally and the job also retries from a fresh run, a staff member may receive two identical emails for the same submission. This is acceptable — the alternative (silent loss) is not.

## 8. Scope

### In scope

- Per-row `submission_digest_sent_at` field on `RegistrationApplication`.
- `RegistrationSubmissionDigestSettings` singleton model.
- `send_submitted_registration_digest()` django-q2 job.
- Daily Schedule seeded by migration.
- Admin interface (superuser-only) for recipient selection.
- Plain-text Latvian email template.
- Flag clearing on every submit (initial + correction).

### Out of scope

- Per-staff preferences (frequency, recipient groups).
- HTML email or rich formatting.
- Digest of approved/rejected applications (only submitted events).
- Real-time or near-real-time notification (daily batch only).
- Webhook or Slack/Teams integration.
- Digest content customisation per staff member.
- Read receipts or delivery confirmations beyond `last_successful_at`.
- Batching by group or status.

## 9. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | After migration, `RegistrationSubmissionDigestSettings` singleton exists (pk=1). |
| AC2 | A django-q2 Schedule named `registrations-submission-digest` exists, pointing to `apps.registrations.tasks.send_submitted_registration_digest`, schedule type DAILY. |
| AC3 | Submitting a draft application sets `submitted_at` and clears `submission_digest_sent_at` to `NULL`. |
| AC4 | Running `send_submitted_registration_digest()` with configured recipients and pending rows sends one Bcc email and stamps `submission_digest_sent_at` on all included rows + `last_successful_at` on the singleton. |
| AC5 | The email body contains only child name, guardian name, Riga datetime, status, and admin URL; it omits emails, phone, PID, address, docs, and review messages. |
| AC6 | With no recipients configured, the job returns `0` and leaves flags unchanged. |
| AC7 | With a send failure (SMTP error), the job returns `0` and leaves flags unchanged (retry next day). |
| AC8 | Resubmitting a fix_requested application clears `submission_digest_sent_at` so it appears in the next digest. |
| AC9 | Only superusers can access the digest settings in Django admin. |
| AC10 | The recipient picker shows only active staff Users. |

# P7 Slice A — Audit baseline

*Design spec. Status: approved for planning. Date: 2026-06-13.*

## 1. Problem

The app has **no audit trail**. `apps/core/audit.py` is an empty placeholder; there is no
`AuditEvent` model and nothing is recorded. Sensitive staff and system actions — approving/
rejecting registrations, viewing/downloading minors' identity documents, deleting documents,
agreement state changes, Invoice Ninja push/payment-sync — leave no record of *who did what,
when, from where*. This is the oldest outstanding debt (flagged since M1) and the foundation
for P7 items 4 (audit coverage), 8 (sensitive actions staff-only **and audited**), and 9
(audit safety). The `actor` parameter is already plumbed through `assign_training_group` and
the agreement services "for the P7 audit hook," so the recording call sites are partly
prepared.

This slice is **Slice A of P7**. Slices B (CSV export) and C (admin operations polish) are
separate specs; the export in B and the admin actions in C will themselves be audited via the
machinery built here.

## 2. Approach (chosen)

**Explicit recording calls + a denormalized target snapshot.**

- An `AuditEvent` model stores one row per meaningful action.
- A `record_audit_event(...)` helper is called **explicitly** at each action site (reusing the
  plumbed `actor` params). Explicit calls — not signals — because only the call site knows the
  *intent* (an "approve" vs a generic status write), has the request (for IP/user-agent), and
  is straightforward to test.
- The target is stored as **denormalized strings** (`target_type`, `target_id`, `target_repr`),
  not a ForeignKey or GenericForeignKey. An audit log is append-only and must survive the
  target's deletion — we specifically audit deletions, so a FK/GFK to a deleted row would
  dangle or cascade. The string snapshot is immortal and decoupled from every app.

Rejected: signals-based recording (no request, no intent, hard to test); GenericForeignKey
target (breaks on the very deletions we audit).

## 3. Scope

In scope: the `AuditEvent` model, the `record_audit_event` helper, wiring the
**milestone-critical action set** (§5), a read-only staff admin viewer, and a configurable
nightly retention prune.

Out of scope:
- Field-level diffing of all model writes.
- Auditing parent-portal reads / routine browsing.
- Auditing **routine automated sync successes** (every nightly payment-sync row, every
  per-invoice send) — only state changes and failures are recorded.
- Exporting the audit log (Slice B / export territory).
- Tamper-proofing / cryptographic signing of the log.

## 4. Data model

`AuditEvent` (new, in `apps/core/`). It is **append-only and immutable**, so it does **not**
extend `TimeStampedModel` (no `updated_at`) — just its own `created_at`:

| Field | Type | Notes |
|-------|------|-------|
| `actor` | `FK(settings.AUTH_USER_MODEL, null=True, on_delete=SET_NULL, related_name="audit_events")` | Staff user; **null** for system/automated events. |
| `actor_label` | `CharField` | Identity snapshot at event time (`"admin@example.com"`, `"system: send_due_invoices"`, `"parent: …@…"`) so the trail stays readable if the user is later deleted. |
| `action` | `CharField(choices=Action)` | The event-type enum (§5). |
| `target_type` | `CharField(blank)` | Model label, e.g. `"registrationapplication"`, `"document"`, `"agreement"`, `"billingrecord"`. |
| `target_id` | `CharField(blank)` | Target PK as string (survives deleted rows / type variance). |
| `target_repr` | `CharField(blank)` | Human snapshot, e.g. `"App #42 — Jānis B."`, `"Document #7 (guardian_identity)"`. **No full personal IDs.** |
| `metadata` | `JSONField(default=dict, blank)` | Small, **redacted** context: `{"from_status":"submitted","to_status":"approved"}`, `{"error_code":"unavailable"}`, `{"training_group":"U-12"}`. Never personal IDs, document contents, email bodies, or tokens. |
| `ip_address` | `GenericIPAddressField(null=True, blank=True)` | Request-originated events only; null for system jobs. |
| `user_agent` | `CharField(max_length=400, blank=True, default="")` | Truncated; request-originated only. |
| `created_at` | `DateTimeField(auto_now_add=True, db_index=True)` | Event time; indexed for retention + ordering. |

Indexes: `created_at`; `(target_type, target_id)` (for "all events for this object"); `action`.
Default ordering: `-created_at`.

`Action` is a `models.TextChoices` enum (the catalog in §5), so adding events later is a
one-line, migration-light change.

## 5. Event catalog (initial)

The milestone-critical set. Each entry: `action` value → where it's recorded → actor.

**Review actions** (`apps/registrations/services.py`, staff actor already passed):
- `application_approved` → `approve_application` → staff. `metadata`: `{from_status, to_status, member_id}`.
- `application_rejected` → `reject_application` → staff. `metadata`: `{from_status}` + reason presence (not the full message text).
- `application_fix_requested` → `request_application_fix` → staff.

**Members** (`apps/members/services.py`, actor plumbed):
- `training_group_assigned` / `training_group_cleared` → `assign_training_group` → staff. `metadata`: `{group}`.

**Documents** (request-originated, staff, with IP/user-agent):
- `document_previewed` → `admin_document_preview` view.
- `document_downloaded` → `admin_document_download` view.
- `document_deleted` → the **soft-delete-on-replace** path in
  `apps/registrations/services.py::_handle_document_upload` (the real deletion path; actor is
  the editing party — a parent → null user + `actor_label="parent: …"`), **and** any staff
  hard-delete via `DocumentAdmin` (`delete_model`/`delete_queryset`, staff actor). `metadata`:
  `{kind, reason: "replaced"|"admin_delete"}`.

**Agreement state** (`apps/agreements/services.py`):
- `agreement_sent` → `mark_agreement_sent` → staff (or system for the electronic optimistic path).
- `agreement_signed` → `mark_agreement_signed` → **system** (arrives via the DocuSeal webhook,
  `apps/agreements/webhooks.py`, with `actor=None`).
- `agreement_voided` → `void_agreement` → staff.
- `agreement_sync_failed` → the DocuSeal create/sync failure branch in
  `apps/integrations/tasks.py` → system. `metadata`: `{error_code}`.

**Billing** (staff-triggered actions + failures; **not** routine automated successes):
- `billing_push_triggered` → `BillingRecordAdmin.push_to_invoice_ninja` action → staff.
- `payment_sync_triggered` → `BillingRecordAdmin.sync_payments` action → staff.
- `invoice_push_failed` / `invoice_send_failed` / `payment_sync_failed` → the corresponding
  failure branches in `apps/integrations/tasks.py` → system. `metadata`: `{error_code}`.

The catalog is explicitly extensible; Slices B and C will add `data_exported`, etc.

## 6. Recording helper

`apps/core/audit.py`:

```
record_audit_event(
    *,
    action: str,                  # an Action choice
    actor=None,                   # User instance, or None for system
    actor_label: str = "",        # overrides/sets the snapshot (e.g. "system: <job>")
    target=None,                  # a model instance — derives target_type/id/repr
    target_type: str = "", target_id: str = "", target_repr: str = "",  # or set explicitly
    metadata: dict | None = None,
    request=None,                 # if given, extract ip_address + user_agent
) -> AuditEvent | None
```

Behavior:
- If `target` is a model instance, derive `target_type` (model label), `target_id` (`str(pk)`),
  and `target_repr` (`str(target)`, truncated) unless explicitly overridden.
- If `request` is given, extract `ip_address` (client IP, honoring a single trusted
  `X-Forwarded-For` hop consistent with the project's proxy setup) and a truncated `user_agent`;
  if `actor` is unset and the request has an authenticated staff user, use it.
- Derive `actor_label` from `actor` when not provided.
- **Auditing must never break the audited action.** The whole body is wrapped in
  `try/except Exception`; on failure it logs a warning and returns `None`. An audit-write error
  must not raise into — or roll back — an approval/download/etc. (Tested explicitly.)

## 7. Admin viewer

`AuditEventAdmin` in `apps/core/admin.py`:
- **Read-only**: `has_add_permission`, `has_change_permission`, `has_delete_permission` all
  return `False` (the log is append-only even for superusers, via the admin).
- `list_display`: `created_at`, `action`, `actor_label`, `target_type`, `target_repr`, `ip_address`.
- `list_filter`: `action`, `target_type`, `created_at`. `date_hierarchy = "created_at"`.
- `search_fields`: `actor_label`, `target_repr`, `target_id`.
- Staff-only by virtue of Django admin; no new permission surface for parents.

## 8. Retention prune

- Setting `AUDIT_RETENTION_DAYS` (env, default **730** = 2 years), read in `settings.py` with the
  project's existing `int(os.environ.get(...))` idiom.
- `prune_audit_events()` task (in `apps/core/` or `apps/integrations/tasks.py`) deletes
  `AuditEvent` rows with `created_at < now - AUDIT_RETENTION_DAYS`. Logs the deleted count.
- Registered as a **daily django-q `Schedule`** (`audit-retention-prune`) via an idempotent data
  migration that mirrors `apps/billing/migrations/0005_billing_payment_sync_schedule.py`
  (same `get_or_create` + reverse-delete + `django_q` dependency pattern), at a configurable
  hour (`AUDIT_PRUNE_HOUR`, default **2**, offset from the billing schedules at 3 and 4).

## 9. Security / data handling

- `metadata` and `target_repr` are **redacted by construction**: never store personal IDs,
  document file contents, email bodies, OTP codes, magic-link tokens, or API keys. Status
  values, error codes, group names, kinds, and PKs only.
- IP/user-agent are stored only for forensic value on request-originated events; pruned with the
  rest of the row by retention.
- No new public surface: the viewer is Django-admin (staff-only). Parents never see audit data.

## 10. Testing

- **Helper:** creates a row with correct fields; derives `target_type/id/repr` from an instance;
  extracts `ip_address`/`user_agent` from a request; sets `actor_label` from actor; system event
  (no actor) stores null actor + provided label.
- **Never raises:** a forced write error inside `record_audit_event` is swallowed + logged; the
  caller proceeds (e.g. `approve_application` still approves).
- **Wiring (representative):** approve/reject/fix each emit their event with from/to status;
  `assign_training_group` emits assigned/cleared; document preview + download emit events with IP;
  the replace path emits `document_deleted`; `mark_agreement_signed` via the webhook emits a
  system-actor `agreement_signed`; the billing admin actions emit `*_triggered`; a simulated push
  failure emits `invoice_push_failed`.
- **Admin:** add/change/delete permissions are all denied.
- **Prune:** deletes events older than `AUDIT_RETENTION_DAYS`, keeps recent ones, honors the
  setting; idempotent schedule migration creates exactly one `Schedule` row.

## 11. Acceptance

1. An `AuditEvent` model + `record_audit_event` helper exist; recording never raises into the
   audited action.
2. Every event in the §5 catalog is recorded at its action site with the correct actor
   (staff vs system), target snapshot, and redacted metadata; request-originated events carry
   IP + user-agent.
3. Routine automated sync successes are **not** recorded; only state changes and failures are.
4. A read-only, staff-only admin viewer lists/filters/searches events; it cannot add, change, or
   delete.
5. `AUDIT_RETENTION_DAYS` (default 730) drives a daily prune job registered as a django-q
   Schedule; old events are deleted, recent kept.
6. No personal IDs / document contents / tokens appear in any audit field.
7. Full suite, ruff, and mypy green.

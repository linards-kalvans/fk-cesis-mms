# P8 — Agreement lifecycle

*Design spec. Status: approved for planning. Date: 2026-06-30.*

## 1. Problem

The current agreement model handles the first approval-to-agreement path: generated, sent, signed,
and void. It does not safely handle what happens after signing when real club operations change:

- staff need to fix or amend an active signed agreement while preserving the signed original;
- staff need to discontinue a member's participation with an effective date and reason;
- billing side effects must be explicit and safe, especially once invoices were pushed or sent;
- parents need to see understandable current status and lifecycle history.

P9 billing-plan lifecycle depends on these rules. Without P8, renewals and plan changes would need
ad-hoc agreement assumptions.

## 2. Chosen approach

Build one lifecycle layer that covers both agreement amendments and membership discontinuation.

- Minor amendments are note-only lifecycle events: no re-signing, no state change, parent-visible
  history, no parent email.
- Material amendments preserve the old signed agreement as `superseded` and create a new current
  generated agreement that follows the normal electronic/paper signing path.
- Discontinuation marks the current agreement and member as discontinued, with effective date,
  reason, audit trail, parent-visible status, and parent email.
- Staff selects which billing invoices are affected. Paid invoices block the flow; unsent local
  draft invoices are cancelled locally; sent unpaid/partial invoices create real Invoice Ninja
  credit notes and auto-apply them where the API supports it.

Rejected:

- Reusing `void` for replacements: it loses the distinction between cancellation and replacement.
- Negative invoices: they are not credit notes and create confusing accounting/payment semantics.
- Full refund automation: paid invoice refunds stay manual in Invoice Ninja for P8.

## 3. Scope

In scope:

- New agreement lifecycle states and history rows.
- Member `active` / `discontinued` status.
- Staff admin actions for minor amendment, material amendment, and discontinuation.
- Parent portal status and agreement history.
- Real Invoice Ninja credit-note integration for selected unpaid sent invoices.
- Audit events for lifecycle and credit-note actions.
- Sandbox Invoice Ninja validation evidence.

Out of scope:

- P9 plan assignment and renewals.
- P10 full parent invoice list/payment links.
- P11 custom one-off invoices.
- Automatic refunds for paid invoices.
- Coach/attendance/training-group lifecycle changes.
- Parent self-service cancellation.

## 4. Agreement lifecycle model

Extend `Agreement.State`:

| State | Meaning | Current? |
|---|---|---|
| `generated` | Current agreement prepared, not sent/signed yet | yes |
| `sent` | Current agreement sent for signature | yes |
| `signed` | Current active signed agreement | yes |
| `void` | Cancelled before replacement; existing behaviour | yes until regenerated |
| `superseded` | Previously signed agreement replaced by material amendment | no |
| `discontinued` | Membership/agreement ended | yes |

Rules:

- The existing partial unique constraint (`one_current_agreement_per_member`) remains.
- Material amendment requires a currently signed agreement.
- Material amendment updates the old agreement to `superseded`, `is_current=False`, and creates a
  new `generated`, `is_current=True` agreement for the same member.
- Discontinuation requires the current agreement to be signed. The discontinued agreement remains
  current so staff and parents see the terminal current status.
- Regeneration from `void` keeps its current behaviour and does not mean amendment.

## 5. Lifecycle history model

Add `AgreementLifecycleEvent` in `apps/agreements`.

| Field | Type | Notes |
|---|---|---|
| `agreement` | FK to `Agreement` | The agreement this event describes. |
| `event_type` | choices | `minor_amendment`, `material_amendment_started`, `superseded`, `discontinued`, `credit_note_created`, `credit_note_failed`, `credit_note_applied`. |
| `note` | text | Staff note/reason, parent-visible where applicable. |
| `effective_date` | date nullable | Required for discontinuation. |
| `actor_label` | char | Display snapshot for business history. AuditEvent remains the forensic trail. |
| `metadata` | JSON | Redacted IDs and status context only. |
| `created_at` | datetime | Event timestamp. |

Why not only `AuditEvent`: audit is immutable operator trail; lifecycle history is domain state and
parent-facing status. They serve different readers.

## 6. Member lifecycle

Add fields to `Member`:

| Field | Type | Notes |
|---|---|---|
| `status` | choices | `active` (default), `discontinued`. |
| `discontinued_effective_date` | date nullable | Staff-entered effective date. |
| `discontinuation_reason` | text blank | Parent-visible reason. |
| `discontinued_at` | datetime nullable | Timestamp staff confirmed discontinuation. |

No other member workflows change in P8.

## 7. Billing and credit-note flow

### 7.1 Staff invoice selection

Discontinuation form shows proposed `BillingInvoice` rows for the member with:

- billing record/season;
- sequence and due date;
- amount;
- external invoice id;
- external status and sent timestamp;
- payment status;
- proposed action.

Staff selects rows to include.

### 7.2 Invoice rules

For each selected invoice:

| Invoice state | P8 behaviour |
|---|---|
| Paid | Block before any state change. Staff handles refund manually in Invoice Ninja. |
| No external invoice id and not sent | Mark locally cancelled; no Invoice Ninja call. |
| Sent/unpaid or sent/partial with external invoice id | Create Invoice Ninja credit note and auto-apply to target invoice when supported. |
| External state unclear/failed | Block with a Latvian warning until staff retries/cleans the invoice state. |

Confirmed or synced invoices are never silently mutated.

Add local cancellation fields to `BillingInvoice`:

| Field | Type | Notes |
|---|---|---|
| `cancelled_at` | datetime nullable | Set only for local unsent invoices cancelled by discontinuation. |
| `cancellation_reason` | text blank | Staff reason/effective-date summary. |

Cancelled local invoices are excluded from future autosend/push retry selections.

### 7.3 Local adjustment model

Add `BillingAdjustment` in `apps/billing`.

| Field | Type | Notes |
|---|---|---|
| `billing_record` | FK | Parent billing record. |
| `invoice` | FK nullable | Target `BillingInvoice`. |
| `agreement_event` | FK nullable | Discontinuation/history event that created it. |
| `kind` | choices | `credit_note`. |
| `amount` | decimal | Positive credit amount. |
| `reason` | text | Redacted staff/parent-safe reason. |
| `external_credit_id` | char blank | Invoice Ninja credit id. |
| `external_status` | char blank | `pending`, `created`, `applied`, `failed`, etc. |
| `external_error_code` | char blank | Existing Invoice Ninja error-code pattern. |
| `applied_to_external_invoice_id` | char blank | Target invoice id when auto-apply succeeds. |
| `requires_staff_apply` | bool | True if credit created but API auto-apply was unavailable/unsafe. |
| `created_by` | FK user nullable | Staff actor snapshot helper still comes from audit/history. |

## 8. Invoice Ninja credit integration

The current docs available through Context7 do not provide enough concrete credit-note API detail.
Therefore implementation starts with a required live sandbox spike:

1. Create a sandbox invoice in local app / Invoice Ninja.
2. Discover exact create-credit endpoint and payload.
3. Discover exact apply-credit-to-invoice mechanism.
4. Confirm response shape and status fields.
5. Confirm duplicate/idempotent lookup strategy, preferably deterministic number or searchable custom field.
6. Update adapter tests to match observed live API before building admin flow.

Adapter shape extends `apps/integrations/invoice_platform.py`:

- `create_credit_note(adjustment) -> CreditResult`
- `apply_credit_to_invoice(credit_id, invoice_id, amount) -> CreditApplyResult`
- `sync_credit_note(credit_id) -> CreditResult` if needed by live API shape

Provider follows existing Invoice Ninja conventions:

- `X-Api-Token`, `X-Requested-With`, `Accept: application/json` headers;
- terminal vs transient exception mapping;
- no PII-heavy payload logging;
- background job retry for transient failures.

## 9. Admin UX

Use Django admin only.

Member change page:

- show member status badge;
- show discontinuation fields when discontinued;
- provide `Pārtraukt dalību` action for active members with signed current agreement;
- link related agreements, billing records, and adjustments.

RegistrationApplication change page:

- extend current agreement module;
- show lifecycle history;
- add minor amendment form;
- add material amendment form;
- link/start discontinuation for approved member.

Agreement change page:

- read lifecycle history;
- link to member and source application;
- no direct destructive lifecycle action unless it reuses the same service layer.

Billing admin:

- show adjustment rows and sync-health badges;
- retry failed credit-note jobs;
- filter by failed/pending/applied adjustment state.

## 10. Parent UX and emails

Parent portal shows, per approved child/member:

- current agreement status;
- member discontinued status where applicable;
- lifecycle history list: signed, minor amendments, superseded/replaced agreements, discontinued.

P8 does not add the full invoice list. That remains P10.

Emails:

- Minor amendment: no email.
- Material amendment: existing sent/signed notifications cover the new agreement path.
- Discontinuation: always send parent email with effective date, reason, and a concise credit-note
  summary. If credit creation is pending/failed, say staff will follow up; do not expose internal
  error codes.

## 11. Error handling and transactions

- Paid selected invoice blocks before any local state change.
- Local discontinuation state change is atomic: agreement, member, lifecycle event, and local
  adjustment rows are created together.
- Invoice Ninja credit creation runs in background jobs after local state is committed.
- Failed credit jobs do not roll back discontinuation; they mark `BillingAdjustment` failed and
  create admin-visible retry work.
- If auto-apply is unsupported or fails terminally after credit creation, mark
  `requires_staff_apply=True` and show staff action needed.

## 12. Audit events

Add `AuditEvent.Action` values:

- `AGREEMENT_MINOR_AMENDED`
- `AGREEMENT_MATERIAL_AMENDMENT_STARTED`
- `AGREEMENT_SUPERSEDED`
- `MEMBER_DISCONTINUED`
- `BILLING_CREDIT_CREATED`
- `BILLING_CREDIT_FAILED`
- `BILLING_CREDIT_APPLIED`

Metadata stays redacted: ids, statuses, amounts, error codes, no personal IDs or document data.

## 13. Tests

Service tests:

- minor amendment creates lifecycle event, does not change agreement state, sends no email;
- material amendment requires signed agreement;
- material amendment supersedes old agreement and creates new current generated agreement;
- discontinuation requires signed current agreement;
- discontinuation sets agreement and member status;
- paid selected invoice blocks before state change;
- unsent draft invoice is cancelled locally;
- sent unpaid invoice creates `BillingAdjustment`;
- failed credit job is retryable/visible without reverting discontinuation;
- locally cancelled invoice is excluded from send/push candidate queries.

Adapter/provider tests:

- create-credit payload and normalization;
- apply-credit payload and normalization;
- duplicate/idempotent lookup;
- transient and terminal error mapping.

Admin tests:

- lifecycle actions visible only in valid states;
- Latvian validation errors;
- staff/CSRF permissions;
- adjustment sync-health badges and retry action.

Parent tests:

- current status and history render for owner;
- other guardian cannot see lifecycle history;
- discontinuation email includes effective date, reason, and credit summary.

Live validation:

- sandbox Invoice Ninja credit note created;
- credit note auto-applied to unpaid invoice, or unsupported path documented and staff-apply flag verified;
- paid invoice selection blocks before API call;
- duplicate/retry case validated where safely possible.

## 14. Acceptance criteria

P8 is complete when:

1. Staff can record a minor amendment without requiring re-signing.
2. Staff can start a material amendment; the old signed agreement is preserved as superseded and a
   new current agreement follows the normal signing path.
3. Staff can discontinue a member/agreement with effective date and reason.
4. Staff selects affected invoice rows during discontinuation.
5. Paid selected invoices block the operation with a Latvian warning.
6. Unsent draft invoices are marked locally cancelled and excluded from future send/push candidates.
7. Sent unpaid/partial invoices create real Invoice Ninja credit notes and auto-apply where the API
   supports it.
8. Parent portal shows current agreement/member status and lifecycle history.
9. Discontinuation email is sent to the parent.
10. Audit events cover lifecycle and credit-note changes.
11. Automated tests, `ruff`, and `mypy` pass.
12. Sandbox Invoice Ninja validation evidence is committed.

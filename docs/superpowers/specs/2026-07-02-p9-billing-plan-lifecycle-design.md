# P9 — Billing plan lifecycle

*Design spec. Status: approved for planning. Date: 2026-07-02.*

## 1. Problem

Current billing draft creation still has one important hidden choice: when an agreement is signed, `create_draft_billing_for_member()` picks the latest active `MembershipPlan`. That worked for the first MVP season, but it is unsafe once staff can stage next-season plans, renew members, or adjust draft billing.

P9 makes billing-plan intent explicit before draft billing exists.

Goals:

- New signed agreements never rely on "latest active plan wins" silently.
- Staff can see and change the billing plan on the agreement before signing.
- Staff can renew selected existing members into a new plan/season without creating a new agreement.
- Staff can reassign draft billing records safely.
- Confirmed/synced billing records and Invoice Ninja invoices are never silently mutated.

## 2. Chosen approach

Use the existing domain models and admin surfaces. Add only the fields needed to persist billing intent.

- `MembershipPlan` gets one explicit default marker and a billing-start cutoff day.
- `Agreement` stores the chosen billing plan and first billing month before signing.
- `BillingRecord` snapshots the chosen first billing month.
- Member admin gets a selected-members renewal action.
- BillingRecord admin gets a draft-only reassignment/regeneration action.

Rejected:

- Admin-only transient plan choice: not durable, hard to audit, easy to lose before signing.
- A new assignment/batch model: useful later for recurring renewal campaigns, but too much for current needs.
- Parent portal billing changes in P9: parent invoice visibility is P11.

## 3. Scope

In scope:

- Default billing-plan configuration.
- Agreement-level billing-plan selection before signing.
- First billing month derivation from cutoff day, with staff override.
- Billing-only renewal for selected members.
- Draft-only billing-record reassignment/regeneration.
- Mutation audit events for plan assignment, renewal creation, and draft reassignment.
- Admin-only UX and tests.

Out of scope:

- Parent-facing invoice/billing UI.
- Custom one-off invoices.
- Renewal agreement creation or DocuSeal signing for renewal.
- Recurring automatic yearly renewal jobs.
- Bulk "all active members" renewal without explicit selection.
- Mutating confirmed/synced Invoice Ninja invoices.

## 4. Data model

### 4.1 MembershipPlan

Add fields:

| Field | Type | Notes |
|---|---|---|
| `is_default` | boolean | Exactly one default active plan should exist. Used to prefill new agreements. |
| `billing_start_cutoff_day` | positive small int | 1–31. Decides current vs next first billing month. |

Rules:

- A default plan must be active.
- Only one default plan can exist.
- Admin validation should show a Latvian error for invalid default setup.
- DB constraints enforce single default and `is_default -> is_active`; service/admin validation still gives friendly errors.

First-month rule:

- If `today.day <= billing_start_cutoff_day`, first billing month is the current month.
- If `today.day > billing_start_cutoff_day`, first billing month is the next month.
- Store month as `YYYY-MM`.
- Existing `skip_months` and due-day rules still apply when materializing invoices.

### 4.2 Agreement

Add fields:

| Field | Type | Notes |
|---|---|---|
| `billing_plan` | FK to `MembershipPlan`, nullable/protect | Prefilled from default active plan. Staff can change before signing. Signing requires it. |
| `first_billing_month` | char, blank, `YYYY-MM` | Prefilled from plan cutoff. Staff can override before signing. |

Rules:

- Agreement creation preselects the current default active plan, if one exists.
- If no default exists, agreement is still created with empty billing fields.
- Marking an agreement signed is blocked until `billing_plan` is set.
- Staff can change `billing_plan` and `first_billing_month` while agreement is not signed.
- After signing, normal billing mutation guards apply; changing the agreement billing fields must not mutate confirmed/synced billing.

### 4.3 BillingRecord

Add field:

| Field | Type | Notes |
|---|---|---|
| `first_billing_month` | char, blank, `YYYY-MM` | Snapshot from agreement, renewal form, or draft reassignment. |

Rules:

- New draft records use this month when materializing `BillingInvoice` rows.
- If blank, existing plan schedule behaviour remains as fallback for legacy records.
- Confirmed/synced records do not change silently.

## 5. Service behaviour

### 5.1 Default plan lookup

Add a small billing service helper:

```python
def get_default_billing_plan() -> MembershipPlan | None: ...
```

Returns the active default plan, or `None`.

No fallback to latest active plan in new agreement signing flow.

### 5.2 First billing month derivation

Add a pure helper:

```python
def derive_first_billing_month(plan: MembershipPlan, today: date | None = None) -> str: ...
```

Returns `YYYY-MM` using the cutoff rule.

### 5.3 Agreement draft billing creation

Change `create_draft_billing_for_member(member, agreement)`:

- Use `agreement.billing_plan`.
- If missing, raise `ValueError("billing plan required")`; signing catches it and shows a clear Latvian admin error.
- Create or return existing `(member, plan.season)` draft as today does.
- Snapshot `first_billing_month` from `agreement.first_billing_month`.
- Preserve existing sibling-discount and payment-mode logic.

### 5.4 Renewal creation

Add service:

```python
def renew_member_billing(member, plan, *, first_billing_month: str = "", actor=None) -> BillingRecord | None: ...
```

Rules:

- Billing-only renewal; no new agreement.
- Creates a draft `BillingRecord` for `plan.season` when missing.
- Returns `None` when a record already exists for `(member, plan.season)`.
- Uses current signed agreement as `agreement` when available.
- Skips discontinued members at admin-action level.
- Audits only created records.

### 5.5 Draft reassignment/regeneration

Add service:

```python
def reassign_draft_billing_record(record, plan, *, first_billing_month: str = "", actor=None) -> None: ...
```

Rules:

- Allowed only when `record.status == draft`.
- Block if any related invoice has `external_invoice_id` or was sent.
- Update plan, season, first billing month, and snapshotted amounts.
- Recreate local unpushed invoice rows when needed.
- Preserve manual override only if staff explicitly chooses to keep it; otherwise recompute natural amount.
- Audit successful reassignment.

## 6. Admin UX

### 6.1 MembershipPlan admin

- Show `is_default` and `billing_start_cutoff_day` in list/detail.
- Friendly validation:
  - default must be active;
  - only one default plan.

### 6.2 Agreement module

Add billing setup block to the existing agreement admin module:

- selected billing plan;
- first billing month (`YYYY-MM`);
- save action for billing setup;
- warning when missing plan blocks signing.

Signing buttons must show a clear Latvian error if plan is missing.

### 6.3 Member admin renewal action

Selected-members admin action:

1. Staff selects members.
2. Confirmation page asks for target `MembershipPlan` and optional first billing month (`YYYY-MM`).
3. Action creates missing draft records.
4. Existing target-season records are skipped and counted.
5. Discontinued members are skipped and counted.

No mutation of existing records happens in renewal action.

### 6.4 BillingRecord reassignment action

Draft-only admin action/button:

- choose new plan;
- optional first billing month (`YYYY-MM`);
- confirm regeneration.

Do not show/allow action for confirmed records, synced records, or records with external/sent invoices.

## 7. Audit

Add `AuditEvent.Action` values:

- `BILLING_PLAN_ASSIGNED`
- `BILLING_RECORD_RENEWED`
- `BILLING_RECORD_REASSIGNED`

Rules:

- Audit only successful mutations.
- Do not audit skipped renewal rows.
- Metadata must stay redacted: plan id/season, record id, old/new plan id, first billing month, counts where useful. No personal IDs or document data.

## 8. Parent-facing behaviour

No parent UI changes in P9.

Parent-facing billing and invoice visibility remains P11.

## 9. Error handling

- Missing billing plan blocks signing with a Latvian admin message.
- Invalid `YYYY-MM` input returns form validation error; no mutation.
- Renewal skips existing target-season records and reports count.
- Draft reassignment blocks confirmed/synced/pushed records with clear admin error.
- Existing Invoice Ninja push, send, and payment-sync retries remain unchanged.

## 10. Testing strategy

Tests should cover:

- default plan validation and uniqueness;
- default plan preselected on agreement creation;
- first billing month cutoff rule;
- signing blocked without billing plan;
- draft billing uses agreement plan and first billing month;
- legacy blank first billing month still uses plan schedule fallback;
- selected-members renewal creates missing records;
- renewal skips existing target-season records;
- renewal skips discontinued members;
- draft reassignment changes plan/month and regenerates local unpushed invoices;
- confirmed/synced/pushed records cannot be reassigned;
- audit events are emitted for real mutations only;
- parent portal remains unchanged.

## 11. Acceptance criteria

P9 is complete when:

1. New agreements do not rely on latest active plan selection.
2. Agreement signing is blocked until a billing plan is selected.
3. Default active billing plan preselects new agreement billing setup.
4. Staff can set default plan and cutoff day in admin.
5. First billing month is derived from cutoff day and can be overridden as `YYYY-MM`.
6. Selected-member renewal creates missing draft records and skips existing target-season records.
7. Draft billing records can be reassigned/regenerated with plan and month override.
8. Confirmed/synced/pushed records are not silently mutated.
9. Mutation audit events exist for plan assignment, renewal creation, and draft reassignment.
10. Tests cover all P9 acceptance cases.

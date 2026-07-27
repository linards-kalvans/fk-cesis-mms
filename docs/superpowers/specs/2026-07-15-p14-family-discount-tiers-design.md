# Family discount tiers design

Date: 2026-07-15
Status: approved (2026-07-15)

## Problem

The current sibling discount applies a flat percentage (configured on `MembershipPlan.sibling_discount_percent`) to every child beyond the first in a guardian's family. FK Cēsis needs a graduated tier structure: 0 % → 50 % → 75 % → 100 %. The discount schedule is fixed club policy, not configurable per plan.

## Goals

- Apply graduated tiers to billing records created after delivery.
- Apply the same tiers to P9 billing-only renewals using a guardian's current signed family, even when the target renewal plan is for a later season.
- Remove the obsolete `sibling_discount_percent` configuration from `MembershipPlan`.
- Snapshot each record's computed tier atomically under a guardian-row lock.
- 100 % tier records exist locally for history but do not materialize, push, send, or sync Invoice Ninja invoices.
- Staff can override draft record totals with a required reason (audited; reason text excluded from audit metadata).
- Full backward compatibility: existing records retain their stored snapshots.

## Non-goals

- Different family policies or configurable tiers.
- Re-pricing existing billing records or invoices.
- Credits / refunds for old invoices.
- Any parent-facing UI change.
- P15 calendar-year partial billing.

## Tier map

| Family rank | Discount % | Invoice Ninja |
|-------------|-----------|---------------|
| 1st child   | 0 %       | full amount   |
| 2nd child   | 50 %      | half amount   |
| 3rd child   | 75 %      | quarter amount|
| 4th+ child  | 100 %     | no invoice    |

## Billable sibling definition

A sibling is **billable** for a candidate plan's year/season when all of the following hold:

1. The member has a current `Agreement` with `state == "signed"` and `is_current == True`.
2. On the normal signing path, that agreement's `billing_plan` matches the candidate plan's `season`.
3. The member does **not** have a discontinuation whose `discontinued_effective_date` falls on or before the candidate record's first billable due date (`discontinued_effective_date <= first_due_date`). A discontinued member whose effective date is strictly after `first_due_date` is included.
4. Defensive exclusion: any `Member` with `status == "DISCONTINUED"` and no `discontinued_effective_date` is excluded.

The candidate member itself is included in the ordered family set. Not all eligible members have active status; discontinued members with a future effective date are included.

### P9 billing-only renewal exception

`renew_member_billing()` creates a target-season record without creating a new agreement. For that path only, rank the guardian's current signed family **without** filtering agreements by the target plan's season. This carries the known current family rank into the new billing season. The same signing-time order and discontinuation rules apply. A renewal member with no current signed agreement is outside this cohort and falls back to rank 0/full price, preserving the existing legacy renewal behavior.

## Ordering rules

Order billable siblings by:

1. **Signed time:** `Agreement.signed_at` ascending (earliest signed first).
2. **Tie-break:** `Member.pk` ascending (stable when signed times are identical).

Guardian isolation: the ranking is computed within a single `Guardian`'s children. A parent with two guardians (two `ParentAccount` rows) is not a supported scenario — the current architecture enforces 1:1 `Guardian` ↔ `ParentAccount`.

Season isolation: normal signing-path ranking considers only siblings whose current signed agreement's `billing_plan` matches the candidate plan's `season`. A sibling enrolled in a different season's plan does not occupy a rank in that family set. The P9 billing-only renewal exception above intentionally uses the current signed family across plan seasons.

## Opt-out rank preservation

A parent's opt-out (`support_club_instead_of_multi_child_discount = True`) makes **only that child's record full-price**. The child still occupies its computed family rank for sibling-discount purposes — it does not shift other siblings' ranks.

Implementation: the opt-out flag is checked at billing-record creation time. The tier is computed from the ordered family set; the record stores `discount_amount=0`, `final_amount=base_amount`, `is_full_price=True`, and `full_price_opt_out=True`. The opt-out record still occupies rank; its declined tier percentage is not stored.

## Snapshot semantics

The computed tier (discount percent, discount amount, final amount, `is_full_price`) is **snapshotted** on `BillingRecord` at creation time. Later changes to the family composition, plan settings, or signing order do not retroactively alter older records.

`BillingRecord` already carries:
- `sibling_discount_percent_applied` — actual applied percent at creation (0 % for opt-out).
- `discount_amount` — the monetary discount at creation.
- `final_amount` — the net amount at creation.
- `manual_amount_override` — staff override (overrides the computed total).
- `manual_override_reason` — required when override is set.
- `is_full_price` — boolean flag.
- `full_price_opt_out` — boolean flag when the parent opted out of the sibling discount.

These fields are preserved for backward compatibility. The new tier percent is stored in `sibling_discount_percent_applied`. Snapshot recompute/reassign uses the stored actual applied percent; no unused opt-out variable logic.

## Zero-invoice rule

A 100 % tier record has `final_amount == 0`. The record exists locally with status `DRAFT` for history and audit. It must **not**:

- Materialize `BillingInvoice` rows.
- Be pushed to Invoice Ninja.
- Be sent to the parent.
- Appear in payment sync.

`create_draft_billing_for_member` does not materialize installments. `materialize_installments` returns `[]` immediately when `record.final_amount == 0` (no rows created). `push_billing_record` detects zero amount after fetching/confirmed-state guards but before it sets pending or ensures product/client: it sets `external_status="synced"`, clears `external_error_code`, saves, and returns. This is the approved local terminal state. No provider calls and no `BillingInvoice` rows are created.

## Manual override

Staff can override only a **DRAFT** record's total amount:

- Use existing `manual_amount_override` + `manual_override_reason` fields.
- A non-empty trimmed `manual_override_reason` is required whenever `manual_amount_override` is non-null, including when the override is `0`.
- The override replaces the computed total **before** invoice creation.
- Override changes `final_amount`.
- Non-DRAFT records preserve the existing override but block any amount or reason modification.
- Override change is audited with `BILLING_RECORD_AMOUNT_OVERRIDDEN`.
- Audit metadata must **not** contain the reason free text.
- Override audit merges into the existing admin status audit (single `save_model` path).

### Override validation and audit

- **Validation:** a `BillingRecordAdminForm` overrides `clean()` to require a non-empty trimmed `manual_override_reason` when `manual_amount_override` is non-null (including `0`), and to reject changing an existing override/reason on non-DRAFT records. The form also sets `self.instance.final_amount = override` when override is non-null so save persists the total used by invoices.
- **Audit:** `BillingRecordAdmin.save_model()` fetches the persisted original **before** `super().save_model()`, delegates normal status auditing without losing it, and emits `record_audit_event(action=str(AuditEvent.Action.BILLING_RECORD_AMOUNT_OVERRIDDEN), actor=request.user, request=request, target=obj, metadata={"old_override": ..., "new_override": ...})` when override/reason changes. Never include reason text in metadata.
- **Confirmed records:** existing overrides on confirmed records are preserved but cannot be altered (the form's `clean()` rejects any change). Not all confirmed records lack overrides — existing overrides remain, only modifications lock.

## Concurrency guard

The tier computation and billing-record creation must happen under a **guardian-row lock** (`select_for_update()`) so that concurrent sibling signings or renewals cannot claim the same rank. The lock is held during the entire `create_draft_billing_for_member` or `renew_member_billing` call.

## Data model changes

### New audit event

Add `BILLING_RECORD_AMOUNT_OVERRIDDEN` to `AuditEvent.Action`. Migration `apps/core/migrations/0007_alter_auditevent_action.py` (choices-only).

### Remove `sibling_discount_percent`

Drop `MembershipPlan.sibling_discount_percent` via a schema field-removal migration: `apps/billing/migrations/0014_remove_membershipplan_sibling_discount_percent.py`. No data migration is needed — `BillingRecord.sibling_discount_percent_applied` already contains historical snapshots for every existing record.

## Service behavior

### `compute_family_tier(member, plan, first_due_date, *, season_scoped=True) -> int`

Pure function. Given a `Member`, `MembershipPlan`, and the candidate record's first billable due date (`first_due_date` is a `date` derived from the record's snapshotted first billing month plus skip months):

1. Root the query in `Agreement`: filter to current signed agreements matching `member__guardian_id == member.guardian_id`.
2. When `season_scoped=True` (normal signing path), filter `billing_plan__season=plan.season`. When `False` (P9 renewal only), omit that filter.
3. Exclude members discontinued on or before `first_due_date` (exclude where `discontinued_effective_date <= first_due_date`).
4. Defensive exclusion: exclude members with `status == "DISCONTINUED"` and a null `discontinued_effective_date`.
5. `select_related("member")` and `order_by("signed_at", "member_id")`.
6. Iterate the ordered result, find the candidate's position.
7. Return the tier index (0-based rank) clamped to `max(TIER_MAP.keys())`. Return 0 when the candidate is absent, preserving the legacy no-current-agreement full-price fallback.

Side effects: none.

```python
from django.db.models import Q

candidates = (
    Agreement.objects.filter(
        is_current=True,
        state=Agreement.State.SIGNED,
        member__guardian_id=member.guardian_id,
    )
    .exclude(
        Q(member__discontinued_effective_date__isnull=False, member__discontinued_effective_date__lte=first_due_date)
        | Q(member__status=Member.Status.DISCONTINUED, member__discontinued_effective_date__isnull=True)
    )
    .select_related("member")
    .order_by("signed_at", "member_id")
)

if season_scoped:
    candidates = candidates.filter(billing_plan__season=plan.season)
```

### `create_draft_billing_for_member(member, agreement)`

1. Resolve `plan` from `agreement.billing_plan` or legacy fallback (unchanged from current).
2. Compute `first_due_date` — a `date` derived from the agreement's snapshotted `first_billing_month` + skip months via `derive_installment_schedule(plan, Decimal("0.00"), first_billing_month=first_billing_month)`, taking the first due date from the resulting schedule.
3. Acquire `Guardian` row lock via `select_for_update()`.
4. Call `compute_family_tier(member, plan, first_due_date)` under the lock.
5. Map the tier index to a discount percent via `TIER_MAP`.
6. Compute base amount, discount, final amount using the tier percent.
7. Persist `BillingRecord` with snapshot fields.
8. Return the record (unchanged return path).

`create_draft_billing_for_member` does **not** materialize installments; only `push_billing_record` materializes invoice rows.

### `renew_member_billing(member, plan, *, first_billing_month="", actor=None)`

1. Keep P9's billing-only renewal contract: no agreement is created and an existing `(member, season)` record remains a no-op.
2. Acquire the guardian-row lock before checking/creating the record.
3. Compute the record snapshot with `compute_family_tier(..., season_scoped=False)`: current signed family across plan seasons.
4. If the renewal member has no current signed agreement, `compute_family_tier` returns 0, so the record is full-price.
5. Preserve the existing `BILLING_RECORD_RENEWED` audit contract.

### `recompute_billing_record(record)`

Re-reads the plan and re-derives amounts for a DRAFT record. Uses the stored `sibling_discount_percent_applied` (actual applied percent) to calculate a fresh base/discount/final amount. Manual override wins for `final_amount`. Never reruns family-rank query. The stored tier snapshot is preserved — later family changes do not alter old record prices.

### `materialize_installments(record)`

Returns `[]` immediately when `record.final_amount == 0` (no rows created).

### `push_billing_record(record)`

Detects zero amount after fetching/confirmed-state guards but before it sets pending or ensures product/client. It sets `external_status="synced"`, clears `external_error_code`, saves, and returns. This is the approved local terminal state. No provider calls and no `BillingInvoice` rows.

## Test strategy

### Tier computation

- Parametric tests for each tier: 1st child → 0 %, 2nd → 50 %, 3rd → 75 %, 4th+ → 100 %. All four require signed agreements.
- Signed-time ordering: verify that a later-signed child gets a higher rank. All four require signed agreements.
- Tie-break: verify that equal signed times resolve by `Member.pk`. All four require signed agreements.
- Guardian isolation: two guardians' children do not mix ranks. All four require signed agreements.
- Season isolation: siblings in different seasons do not share ranks. All four require signed agreements.
- Renewal exception: two members with current signed agreements from an old season create next-season P9 renewal records at 0 % and 50 %; no new agreement is created.
- Opt-out rank: opt-out child is full-price but occupies its rank for siblings. All four require signed agreements.
- Discontinuation exclusion: a discontinued member (or one with effective date ≤ first due date) is excluded. All four require signed agreements.

### Snapshot stability

- Create a record, then add a new sibling; verify the old record's stored tier is unchanged.
- Recompute a record; verify the stored tier is preserved.

### Concurrency

- Two concurrent signings: acquire the guardian lock; verify no rank collision.
- Verify `select_for_update` is exercised via code-level assertion (patching `QuerySet.select_for_update`); SQLite does not emit `SELECT FOR UPDATE` — the real row lock is enforced by PostgreSQL at deploy time.

### Zero-invoice rule

- Create a 4th-child record; verify `BillingInvoice` count is zero. Requires signed agreement.
- Push a 4th-child record; mock the provider and assert no Invoice Ninja call, record stays in local status. Requires signed agreement.

### Override

- Override a DRAFT record with reason → audited, reason excluded from metadata.
- Override a CONFIRMED record → rejected by form validation.
- Override without reason → rejected by form validation.

### Field removal

- `MembershipPlan.sibling_discount_percent` column is gone.
- `BillingRecord.sibling_discount_percent_applied` still exists and is readable.

## Acceptance criteria

- All four tiers verified with tests (all require signed agreements).
- Signed-time ordering + pk tie-break verified.
- Guardian and season isolation verified.
- P9 renewal ranks current signed family across target-plan seasons, while a renewal member without a current signed agreement remains full-price.
- Opt-out rank preserved.
- Discontinuation-before-first-due exclusion verified.
- Snapshot stability verified.
- Concurrency guard verified.
- Zero-record never produces an invoice or provider call.
- Override/reason/locking/audit verified.
- Old plan discount field gone.
- Full project gate: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`

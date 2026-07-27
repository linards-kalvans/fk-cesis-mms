# P15 — Calendar-year Partial Billing (Design)

> **Status:** DEV COMPLETE (2026-07-21). LAN acceptance pending.
> **Plan:** `docs/superpowers/plans/2026-07-21-p15-calendar-year-partial-billing.md`

## Problem

When staff confirm a `first_billing_month` on a new agreement that falls mid-calendar-year, the parent should only be charged for the remaining billable installments in that calendar year — not the full annual amount. Existing billing records and invoices are untouched.

## Scope

**In scope:**
- Partial-year base calculation for new `BillingRecord` rows created during the `agreement_signed` signal when `first_billing_month` is non-blank.
- `BillingRecord.scheduled_installment_count` — nullable snapshot of the calendar-year billable count.
- Normalization of staff-set `first_billing_month` past skip months, no-backdate guard, and next-year rollover block.
- Recompute and explicit draft reassign honour the saved count / partial base.
- Default plan preselection adapts to the cutoff year (leave empty when normalized month crosses into next year).
- Admin UI: native `<input type="month">` on registration review, billing reassign, and family hub.
- Latvian error messages including the exact next-year string: `Nākamajam gadam izvēlieties aktīvu norēķinu plānu.`

**Out of scope (explicitly):**
- Custom invoices (P16).
- Parent-facing UI changes.
- Renewal flow changes (`renew_member_billing` is unchanged).
- Backfill or repricing of existing `BillingRecord` / `BillingInvoice` rows.
- Invoice Ninja behaviour changes.
- New background jobs or dependencies.
- New audit action (existing `BILLING_PLAN_ASSIGNED` and `BILLING_RECORD_REASSIGNED` reused).

## Data model

### `BillingRecord.scheduled_installment_count`

```
PositiveSmallIntegerField(null=True, blank=True)
```

- **NULL** → legacy full-plan materialization (uses `plan.installment_count`).
- **Non-NULL** → P15 partial-year cap; materialization creates exactly this many rows.

Migration: `apps/billing/migrations/0015_billingrecord_scheduled_installment_count.py` — schema-only, no backfill.

## Partial-year base formula

```
scheduled_count = count_calendar_year_billable_installments(plan, first_billing_month)
partial_base = annual_amount × scheduled_count ÷ plan.installment_count   (HALF_UP to cents)
```

`scheduled_count` is the number of rows the plan's own `derive_installment_schedule` would emit in the `first_billing_month`'s calendar year (skip months excluded, capped at `plan.installment_count`). The count is derived from the **existing schedule**, not a manual month walk.

Example: 10-installment plan from August with `skip_months="7,12"` → Aug–Nov = 4 rows; one-installment plan from September → 1 row (never exceeds annual total).

The P14 fixed family tier is applied **after** the partial base:

```
discount = partial_base × tier_percent ÷ 100
final = partial_base − discount
```

**Every non-blank `first_billing_month` gets the partial base**, regardless of alignment with `plan.first_installment_month`. There is no "month equals first_installment_month → full annual" exception. For example, `first_billing_month='2026-09'` on a plan with `first_installment_month=9` and `skip_months='7,12'` yields 3 remaining billable months and `partial_base = annual × 3/10`.

The `scheduled_installment_count` snapshot is **always** written whenever `first_billing_month` is non-blank — both for mid-year starts and for starts that align with the plan's normal first installment month.

## Schedule derivation

`count_calendar_year_billable_installments(plan, first_billing_month)`:

1. Calls `derive_installment_schedule(plan, Decimal("0.00"), first_billing_month=…)`.
2. Filters rows whose `due_date.year` matches the parsed `first_billing_month` year.
3. Returns the count (already capped at `plan.installment_count` by the schedule function).

This means a one-installment plan starting in September returns 1, not the three Sep/Oct/Nov months that a manual calendar walk would count.

## Staff month selection

### `set_billing_setup` validation order (new agreement)

All validation runs **before** any write. Steps:

1. **Non-blank required** — blank → `ValueError("first billing month required")`.
2. **Plan active** — inactive → `ValueError("billing plan inactive")`.
3. **Parse** — malformed `YYYY-MM` → `ValueError("first billing month must use YYYY-MM")`.
4. **Skip-month normalization** — advances past plan skip months (e.g. `2026-07` → `2026-08` for a plan that skips July+December).
5. **No-backdate** — normalized month must not be before the cutoff-derived default (`derive_first_billing_month(plan)`). A raw month that advances past a skip to land on the floor is valid.
6. **Year match** — normalized month year must equal the plan's season start year (`_plan_season_start_year(plan)`). Rollover → `ValueError("next year plan required")`.

On success, the persisted `first_billing_month` is the **normalized** form, not the raw input. Audit metadata carries `scheduled_installment_count`.

### `mark_agreement_signed` signing guard

Pre-mutation guards (all raise before any mutation):

1. State is `generated` or `sent`.
2. `billing_plan` is set (P9 missing-plan guard).
3. `first_billing_month` is non-blank (P15 required-month guard).
4. Plan is active (P15 inactive-plan guard).
5. The staff-confirmed month normalizes into the plan's season start year (P15 next-year guard).

The admin surfaces the exact Latvian copy: `Nākamajam gadam izvēlieties aktīvu norēķinu plānu.`

No current-date re-derivation — the staff-confirmed month is the source of truth. The `agreement_signed` signal only fires after every guard has passed.

### `create_agreement_for_member` default plan preselection

The cutoff-derived month (from `derive_first_billing_month`) is normalized past skip months. If the normalized month's year equals the plan's season start year, both `billing_plan` and `first_billing_month` are preselected. Otherwise both stay empty — staff must explicitly pick a next-year plan.

## Draft record creation paths

`create_draft_billing_for_member(member, agreement)`:

- **Agreement with non-blank `first_billing_month`** → P15 path: snapshot `scheduled_count`, compute partial base, apply P14 tier on top.
- **Agreement with blank `first_billing_month`** → legacy full annual base + NULL count. This branch only fires for non-signing calling patterns (backfill, signal, tests) — the signing transition is blocked at `mark_agreement_signed` for blank months.
- **No agreement** → legacy full annual base + full-price (rank 0).

**New agreement setup and signing reject blank `first_billing_month`.** Legacy existing rows with NULL count retain the full-plan schedule.

## Recompute

`recompute_billing_record(record)`:

- When `scheduled_installment_count` is set → partial base from saved count + stored tier.
- When NULL → full annual base.
- The saved count itself is preserved.

## Draft reassignment

`reassign_draft_billing_record(record, plan, *, first_billing_month="")`:

- **Non-blank month** → normalized, year-matched, **no-backdate enforced**, count recomputed, partial base used. This is a deliberate P15 transformation — a legacy NULL-count row is upgraded.
- **Blank month** → legacy full annual base + NULL count preserved.
- P14 stored tier + manual override always preserved.
- Hard guards: not DRAFT, no pushed invoices, no sent invoices.

## Materialization

`materialize_installments(record)`:

- When `scheduled_installment_count` is set → passes it as `installment_count` to `derive_installment_schedule`, capping rows at the saved count.
- When NULL → falls back to `plan.installment_count`.
- P14 zero-total (final_amount == 0) still produces no invoices.

## Manual override

`manual_amount_override` splits across the saved `scheduled_installment_count` (legacy NULL rows split across the plan's full count).

## Audit

Existing audit actions are reused:

- `BILLING_PLAN_ASSIGNED` — `set_billing_setup` success (metadata carries `scheduled_installment_count` when known).
- `BILLING_RECORD_REASSIGNED` — `reassign_draft_billing_record` success (metadata carries `scheduled_installment_count` when set).

No new audit action.

## Admin UI

All three admin surfaces use native `<input type="month" required>`:

1. **Registration review** — `_agreement_module.html`: `first_billing_month` input inside the billing setup form.
2. **BillingRecord reassign** — `reassign_confirm.html`: `first_billing_month` input.
3. **Family Hub** — `family_hub.html`: `first_billing_month` input.

`BillingRecordAdmin` exposes `scheduled_installment_count` as a read-only field.

## Verification evidence

- Focused P15/admin-family test suite: **66 passed** (controller report).
- Full suite: **1825 passed** before a final deterministic test-only pin (controller report).
- `ruff check .` → clean.
- `mypy .` → clean.
- `makemigrations --check` → no changes.

**Note:** Final full verification remains pending until the controller reruns the full suite after all test/docs revisions are complete. Do not treat the 1825 result as final.

## Implementation decisions

1. **Partial base applies whenever `first_billing_month` is non-blank**, regardless of alignment with `first_installment_month`. A September start on a plan whose `first_installment_month` is also 9 still produces a partial base (the calendar-year count may be less than the full plan count due to skip months). There is no "== first_installment_month → full annual" exception. The `scheduled_installment_count` snapshot is **always** written whenever `first_billing_month` is set.

2. **Reassign enforces no-backdate on non-blank months.** The no-backdate check lives in both `set_billing_setup` and `reassign_draft_billing_record` when a non-blank month is supplied. Blank reassign preserves the legacy path.

3. **Explicit reassign upgrades legacy NULL rows.** A non-blank replacement month on a legacy draft (NULL count) triggers the full P15 path — normalization, count derivation, partial base. Blank reassign keeps legacy.

4. **Blank `first_billing_month` on new setup/signing is rejected.** The signing guard (`mark_agreement_signed`) requires a non-blank month. Legacy existing rows with NULL count retain the full-plan schedule.

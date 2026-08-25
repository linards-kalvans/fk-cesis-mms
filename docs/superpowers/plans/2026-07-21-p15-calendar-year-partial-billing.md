# P15 — Calendar-year Partial Billing: Implementation Plan

> **Status:** DEV COMPLETE (2026-07-21). LAN acceptance pending.
> **Spec:** `docs/superpowers/specs/2026-07-21-p15-calendar-year-partial-billing-design.md`

## Interfaces (final)

### `apps/billing/services.py`

**`count_calendar_year_billable_installments(plan, first_billing_month: str) -> int`**
- Calls `derive_installment_schedule(plan, Decimal("0.00"), first_billing_month=…)`.
- Filters rows whose `due_date.year` matches the parsed `first_billing_month` year.
- Returns the count (already capped at `plan.installment_count`).
- No manual month walk. One-installment plan from September returns 1.

**`partial_base_amount(plan, scheduled_count: int) -> Decimal`**
- `annual_amount × scheduled_count ÷ plan.installment_count` (HALF_UP to cents).
- When `scheduled_count == plan.installment_count` → equals `annual_amount`.

**`create_draft_billing_for_member(member, agreement)`** — extended P15 path:
- Non-blank `first_billing_month` → snapshot `scheduled_count`, compute partial base, apply P14 tier.
- Blank `first_billing_month` → legacy full annual + NULL count (non-signing callers only).
- No agreement → legacy full annual + full-price (rank 0).

**`recompute_billing_record(record)`** — P15 aware:
- `scheduled_installment_count` set → partial base from saved count + stored tier.
- NULL → full annual base.

**`reassign_draft_billing_record(record, plan, *, first_billing_month="")`** — P15 aware:
- Non-blank month → normalized, year-matched, no-backdate enforced, count recomputed, partial base used. Upgrades legacy NULL rows.
- Blank month → legacy full annual + NULL count preserved.

### `apps/agreements/services.py`

**`set_billing_setup(agreement, billing_plan, first_billing_month, actor)`** — P15 validation:
- Non-blank required. Plan active. Parse `YYYY-MM`. Normalize past skip months. No-backdate. Year match.
- Persisted month is normalized form. Audit metadata carries `scheduled_installment_count`.

**`mark_agreement_signed(agreement, actor)`** — P15 signing guard:
- Pre-mutation: state ok, billing_plan set, first_billing_month non-blank, plan active, year match.
- Exact Latvian error: `Nākamajam gadam izvēlieties aktīvu norēķinu plānu.`

### `apps/billing/models.py`

**`BillingRecord.scheduled_installment_count`** — `PositiveSmallIntegerField(null=True, blank=True)`
- NULL → legacy. Non-NULL → P15 partial-year cap.

### `apps/billing/migrations/0015_billingrecord_scheduled_installment_count.py`

Schema-only migration. No backfill. NULL default.

## Tests

**Focused P15/admin-family suite: 66 tests**
- `test_partial_base_amount` — parametric (1/10, 3/10, 5/10, 10/10, 1/1, 0 → 0).
- `test_count_calendar_year` — 10-install Aug-skip-Jul-Dec=4, 1-install Sep=1.
- `test_create_draft_billing_p15_path` — non-blank month → partial base + tier; blank → legacy full annual.
- `test_recompute_p15_honors_count` — partial base preserved on recompute.
- `test_reassign_nonblank_upgrades_legacy` — NULL-count row → P15 path on non-blank reassign.
- `test_reassign_blank_preserves_legacy` — NULL-count row → full annual on blank reassign.
- `test_set_billing_setup_validation` — next-year block, no-backdate, skip normalization, inactive plan, blank rejection.
- `test_mark_agreement_signed_p15_guard` — blank month rejected, next-year rejected, signing blocked without month.
- `test_default_plan_preselection` — cutoff year match → preselected; cutoff crosses year → empty.
- `test_materialize_p15_count` — scheduled count caps rows; NULL → plan count.
- `test_manual_override_split` — override splits across scheduled count or plan count.
- `test_family_hub_set_billing` — admin handler with Latvian error mapping.
- `test_reassign_draft_billing_record_p15` — guards (not DRAFT, pushed invoices, sent invoices).
- `test_create_draft_billing_no_agreement` — legacy full annual + rank 0.
- 50+ P15 tests total across the focused suite.

**Full suite: 1956 passed** (deterministic test-only clock pin applied).

## Acceptance criteria (final)

- [x] Partial base uses existing schedule rows (plan installment cap + skip months) in first-month year.
- [x] P14 tier applied after partial base.
- [x] Nullable `scheduled_installment_count`; migration `billing/0015`, no backfill; NULL legacy fallback.
- [x] Active + nonblank + normalized + cutoff no-backdate + season-year guards before new agreement signing mutation.
- [x] Next-year exact Latvian message: `Nākamajam gadam izvēlieties aktīvu norēķinu plānu.`
- [x] Recompute uses snapshot count; explicit reassign nonblank uses same guards and upgrades old NULL draft; blank legacy reassign stays legacy.
- [x] Month UI is required native input in registration review, billing reassign, Family Hub.
- [x] No parent UI, renewal change, Invoice Ninja behavior, custom invoices, jobs, dependencies, audit action.

## Verification

- Focused P15/admin-family test suite: **66 passed**.
- Full suite: **1956 passed**.
- `ruff check .` → clean.
- `mypy .` → clean.
- `makemigrations --check` → no changes.

Deterministic test-only clock pin applied to the P15 no-backdate tests; production billing rules unchanged. Full verification: `uv run pytest -q` → 1956 passed; `ruff`, `mypy`, and `makemigrations --check` clean. LAN acceptance remains pending.

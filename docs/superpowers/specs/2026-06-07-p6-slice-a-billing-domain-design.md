# P6 Slice A — Billing domain model + sibling-discount engine (design)

**Date:** 2026-06-07
**Phase:** P6 (Billing / Invoice Ninja sync), Slice A of three
**Status:** approved design, ready for implementation plan

## 1. Context

P6 delivers membership billing with Invoice Ninja sync. The full P6 acceptance
list (milestones.md §6) is too large for one spec, so it is decomposed into
three independently shippable, independently verifiable slices:

- **Slice A (this spec)** — billing domain model + sibling-discount engine,
  local only, no Invoice Ninja calls. Nails down the money math and the
  agreement→billing trigger with zero external risk.
- **Slice B** — Invoice Ninja adapter (`billing_platform.py` boundary +
  `invoice_ninja.py` provider, mirroring `agreement_platform.py`/`docuseal.py`)
  + admin-confirmed push to the live instance, with live validation.
- **Slice C** — scheduled payment-status read-back + admin sync health.

`apps/billing` is currently a bare scaffold (`apps.py` + `__init__.py`, no
models). The agreement state machine in `apps/agreements` already terminates at
`signed` via `mark_agreement_signed` (called by both the DocuSeal webhook and
the manual paper mark), giving Slice A a single clean trigger point.
`Member.guardian` is an FK with `related_name="members"`, so a guardian's
siblings are `guardian.members.all()`.

### Confirmed business rules (brainstorm 2026-06-07)

1. **Fee:** configurable annual amount per child (default €300), payable
   **upfront** or in **fixed equal installments** across a configurable season
   window, recurring per season.
2. **Plan assignment:** a **single active plan**, one price for all. Full-price
   child = earliest-registered active member per guardian; the rest are
   discounted.
3. **Sibling discount:** configurable **percentage** off each child after the
   first.
4. **Opt-out:** parent chooses **full-price opt-out at registration** (flag on
   the application).
5. **Manual exception:** **admin-only**, per billing record (custom amount +
   reason).
6. **Trigger:** agreement reaching `signed` **auto-prepares a local draft**
   billing record with computed amounts + discount; the push to Invoice Ninja
   is admin-confirmed (Slice B).
7. **Integration:** the live Invoice Ninja API is available; it is wired in
   Slice B behind an adapter with a stub mode for tests.
8. **Data-model approach:** two models (`MembershipPlan` + `BillingRecord`) plus
   a pure discount engine; installment rows are **not** materialized in Slice A
   (derived on demand) — deferred until Slice B's live API dictates their shape.

## 2. Data model

New `apps/billing` domain: `models.py`, `services.py`, `presentation.py`,
`admin.py`, `messages.py`, `apps.py` (with `ready()` for the signal receiver),
`management/commands/backfill_billing.py`.

### `MembershipPlan` — staff-editable config, one active at a time

| field | type | notes |
|---|---|---|
| `name` | CharField | e.g. "Sezonas maksa 2026/2027" |
| `season` | CharField | e.g. `"2026/2027"`; identifies the billing season |
| `currency` | CharField | default `"EUR"` |
| `annual_amount` | DecimalField(max_digits=8, decimal_places=2) | default `300.00`, full price per child |
| `sibling_discount_percent` | DecimalField(max_digits=5, decimal_places=2) | e.g. `50.00`, % off each child after the first |
| `installment_count` | PositiveSmallIntegerField | number of equal installments |
| `first_installment_month` | PositiveSmallIntegerField | 1–12; billing-start month |
| `is_active` | BooleanField | default `False`; exactly one active expected |
| `TimeStampedModel` | | created/updated |

Per-installment due dates/amounts are **derived on demand** by a helper
(`derive_installment_schedule(plan, total) -> list[(due_date, amount)]`), not
stored. Exact day-of-month and cross-calendar-year anchoring are finalized in
Slice B; Slice A's helper produces N monthly entries from
`first_installment_month`, equal amounts summing to the total (last entry
absorbs the rounding remainder).

### `BillingRecord` — one per `(member, season)`, created at agreement-signed

| field | type | notes |
|---|---|---|
| `member` | FK(Member, PROTECT) | |
| `plan` | FK(MembershipPlan, PROTECT) | |
| `agreement` | FK(agreements.Agreement, SET_NULL, null=True) | the signed agreement that triggered creation |
| `season` | CharField | snapshot from plan |
| `base_amount` | DecimalField | snapshot: plan full price at creation |
| `is_full_price` | BooleanField | whether this child is the full-price child |
| `sibling_discount_percent_applied` | DecimalField | 0 or plan's discount % |
| `discount_amount` | DecimalField | computed |
| `final_amount` | DecimalField | `manual_amount_override` if set else `base − discount` |
| `payment_mode` | CharField(choices) | `upfront` \| `installments` |
| `full_price_opt_out` | BooleanField | snapshot from the application |
| `manual_amount_override` | DecimalField(null=True, blank=True) | admin exception |
| `manual_override_reason` | TextField(blank, default="") | admin exception reason |
| `status` | CharField(choices) | `draft` \| `confirmed` (Slice B adds `sent`/`synced`/`failed`) |
| `TimeStampedModel` | | |

**Constraints:** partial `UniqueConstraint(fields=["member", "season"])` — one
record per member per season. (No `is_current` flag in Slice A: a member has at
most one record per season; cross-season re-billing is future scope.)

**Snapshot philosophy:** money fields are copied at creation so later plan edits
never silently mutate existing drafts. The admin "recompute" action
(§5) re-derives them on demand for `draft` records only.

### New registration fields (`apps/registrations`, one migration)

Both parent-facing, both nullable/defaulted so existing in-flight drafts are
unaffected:

- `full_price_opt_out` — BooleanField, default `False`.
- `preferred_payment_mode` — CharField(choices `upfront`|`installments`),
  default `installments` (matches the existing `preferred_agreement_signing`
  capture pattern).

## 3. Sibling-discount engine

Pure function in `apps/billing/services.py`, no DB writes:

```
compute_billing_amounts(member, plan) -> BillingAmounts
```

`BillingAmounts` is a frozen dataclass: `base_amount`, `is_full_price`,
`discount_percent_applied`, `discount_amount`, `final_amount` (all Decimal,
rounded to cents with `ROUND_HALF_UP`).

**Member → source application:** a `Member` reaches its registration application
via the `approved_member` reverse relation
(`RegistrationApplication.objects.filter(approved_member=member)`). The engine
reads `full_price_opt_out` (and the record creation reads `preferred_payment_mode`)
from that application. `Member` itself has no `is_active` flag — the system has
no member-deactivation concept yet, so **all** of a guardian's members count as
siblings (`guardian.members.all()`).

**Rule:**

1. **Full-price child** = the earliest-created `Member` of the guardian, by
   creation order (`pk` ascending). Determined independently per record, so it
   is stable regardless of *signing* order and existing records never need
   recompute when a later sibling signs.
2. The full-price child → `base_amount`, no discount.
3. Every other child → `sibling_discount_percent` off `base_amount`.
4. **Opt-out override:** if the child's source application has
   `full_price_opt_out=True`, force full price regardless of position.
5. **Manual exception** is applied at the *record* level, not in the engine: the
   engine computes the natural amount; `BillingRecord.final_amount` uses
   `manual_amount_override` when set, else the engine's `final_amount`.

**Edge case — decided rule (a), family-structure:** the full-price child is the
earliest-created member of the guardian **regardless of whether that child is
being billed**. If the eldest child is never billed, younger siblings are still
discounted and no one pays full price for that family. Accepted as simpler and
snapshot-safe; the admin-confirm step (Slice B) catches anomalies. (Rejected
alternative (b): "earliest among billed members" — guarantees one full-price
payer but requires recompute of unconfirmed drafts when an earlier sibling is
later billed.)

## 4. Trigger wiring

**Single integration point:** `mark_agreement_signed` in
`apps/agreements/services.py` (covers electronic webhook + manual paper mark).

**Mechanism — Django signal, to keep the dependency direction clean:**

- `apps/agreements` defines and emits a custom `agreement_signed` signal inside
  `mark_agreement_signed`. Agreements does **not** import billing.
- `apps/billing.AppConfig.ready()` connects a receiver that calls
  `create_draft_billing_for_member(member, agreement)`.
- Dependency direction: billing depends on agreements (natural), not vice versa.

**`create_draft_billing_for_member(member, agreement)`:**

- Looks up the single `is_active=True` `MembershipPlan`.
- Computes amounts via §3 and snapshots them into a new
  `BillingRecord(status="draft")` for `(member, plan.season)`, copying
  `payment_mode` and `full_price_opt_out` from the member's source application.
- **Idempotent:** `get_or_create` on `(member, season)`; a re-signed/regenerated
  agreement never duplicates, and an existing draft (possibly admin-edited) is
  left untouched.
- **Fail-safe:** if no active plan exists, log a warning and no-op. Signing must
  never break because billing config is missing.

**Backfill (in Slice A):** `manage.py backfill_billing` creates draft records for
already-signed agreements whose member lacks a record for the active season.
Idempotent; safe to re-run; no-op when no active plan.

## 5. Surfaces

### Admin (Django admin shell, consistent with P5)

- **`MembershipPlanAdmin`** — full staff CRUD; this is the configurable
  amount/discount/installments/window surface.
- **`BillingRecordAdmin`** — draft-review surface:
  - List: member, guardian, season, `final_amount`, `is_full_price`,
    `payment_mode`, `status`; filters on season + status.
  - Detail: computed money fields + opt-out + payment mode **read-only**
    (snapshots); **editable** `manual_amount_override`, `manual_override_reason`,
    and `status` (`draft`→`confirmed`).
  - Action **"Pārrēķināt no plāna"** — recomputes natural amounts for selected
    `draft` records (picks up plan edits / new siblings); never touches
    `confirmed`.

### Parent registration

The two new fields render in the existing review/consent step as a small
"Maksājuma izvēles" block: full-price opt-out checkbox + upfront/installments
choice. Latvian copy goes through the existing strings pattern (no hardcoded
template strings). No new wizard step.

### Out of Slice A scope

- Any Invoice Ninja call/adapter (Slice B).
- The "confirm & send" push action (Slice B).
- Parent-facing payment *amounts* or *status* (Slice C). Parents only set
  preferences in Slice A.

## 6. Testing (TDD)

- **Discount engine** (`tests/billing/test_discount_engine.py`): single child →
  full; two → first full + second discounted; three+; opt-out forces full;
  opt-out on the first child; cents rounding; members of a different guardian
  excluded; edge case (a) — eldest unbilled, younger still discounted.
- **Trigger/signal** (`test_billing_trigger.py`): signed (electronic + paper)
  creates a correct snapshot draft; idempotent on re-sign; no active plan →
  no-op + warning, signing still succeeds; existing draft untouched.
- **Models** (`test_billing_models.py`): `(member, season)` uniqueness;
  `final_amount` honors override; defaults.
- **Plan config** (`test_membership_plan.py`): installment-schedule helper
  produces N due entries summing to the total (remainder in the last entry).
- **Admin** (`test_billing_admin.py`): recompute action touches only drafts;
  read-only vs editable fields.
- **Registration fields** (`test_billing_registration_fields.py`): opt-out +
  payment-mode persist from the form and render in the workspace; Latvian copy
  contract holds.
- **Backfill** (`test_backfill_billing.py`): creates drafts for already-signed
  agreements lacking one; idempotent.

## 7. Scope boundaries & migrations

- **In:** `apps/billing` (models, services, presentation, admin, messages,
  backfill command), the `agreement_signed` signal in `apps/agreements`, two
  registration fields.
- **Out:** Invoice Ninja adapter/calls (B), payment-status read-back +
  scheduling (C), parent-facing amounts (C).
- **Migrations:** one in `apps/billing` (new app: `MembershipPlan` +
  `BillingRecord`), one in `apps/registrations` (two new nullable/defaulted
  fields).
- **No** change to the agreement state machine, OCR, documents, or deploy
  pipeline.

## 8. Verification gate

`uv run pytest -q && uv run ruff check . && uv run mypy .` clean, then manual LAN
smoke at `http://192.168.3.245:8000`: the parent "Maksājuma izvēles" fields
persist; signing an agreement produces a `draft` `BillingRecord` with the right
amounts; the admin recompute action and manual override behave; `backfill_billing`
populates pre-existing signed agreements.

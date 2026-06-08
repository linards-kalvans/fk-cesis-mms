# P6 Slice C — Payment read-back + scheduled sync + sync health

**Date:** 2026-06-08
**Status:** design approved (pending spec review)
**Closes:** P6 acceptance items 7, 8, 9 (and verifies 1, 2). Completes P6.

## 1. Goal

Slice A built the local billing domain; Slice B built the admin-confirmed **push**
to Invoice Ninja (IN). Slice C closes the loop: Django reads invoice/payment state
**back** from IN on a scheduled sweep, surfaces payment + sync health to staff with a
manual retry path, folds in the deferred Slice-B crash-window hardening, and is
**validated end-to-end against the live IN instance** (Slice B push was only
stub-verified).

IN remains the source of truth for invoices and payment state (acceptance item 7);
Django mirrors a read-only projection.

## 2. Decisions locked during brainstorming

1. **Trigger gating (items 1–2): verify only.** Agreement `signed` (DocuSeal
   webhook-driven) is treated as the "completed" final state. Slice A's
   `agreement_signed` → auto-draft `BillingRecord` signal already satisfies
   "billing starts after completed." Slice C adds a test + AGENTS.md note asserting
   this; it does **not** rebuild the trigger.
2. **Payment detail: status + amounts + paid date.** Persist per-invoice
   `payment_status`, `paid_to_date`, `balance`, `last_payment_date`.
3. **Scheduling: django-q2 `Schedule` row.** An idempotent data migration registers
   a daily `Schedule`; the already-running `qcluster` fires it. Cadence is
   configurable via a setting and editable in Django admin (no OS cron).
4. **Read-back fetch strategy: per-invoice GET** by `external_invoice_id`. Precise,
   idempotent, mirrors the deterministic-number idempotency. Invoice counts per
   record are tiny (≤ installment_count), so request volume is a non-issue.
5. **Live-IN validation is in scope** — a real end-to-end run validating both the
   Slice B push and the Slice C read-back paths, expected to surface integration
   bugs the stub hid (per the P3/P5 live-validation lesson).

## 3. Data model

Migration `apps/billing/migrations/0004_*` adds payment-projection fields.

**`BillingInvoice`** (one row per installment):
- `payment_status` — CharField, choices `unpaid` / `partial` / `paid`, blank default.
- `paid_to_date` — DecimalField(max_digits=8, decimal_places=2, default 0.00).
- `balance` — DecimalField(max_digits=8, decimal_places=2, null=True, blank=True).
- `last_payment_date` — DateField(null=True, blank=True).
- `last_synced_at` — DateTimeField(null=True, blank=True).

**`BillingRecord`** (rolled-up projection):
- `payment_status` — CharField, choices `unpaid` / `partial` / `paid`, blank default.
  Roll-up rule: `paid` when every `BillingInvoice` is `paid`; `unpaid` when none have
  any payment; otherwise `partial`.
- `payment_synced_at` — DateTimeField(null=True, blank=True).

A second migration `0005_*` registers the django-q2 `Schedule` (see §6).

Latvian labels for the new `payment_status` choices live alongside the existing
TextChoices labels; admin-facing copy goes through `apps/billing/messages.py`.

## 4. Provider / adapter boundary

### `apps/integrations/invoice_platform.py` (abstraction)
- New frozen dataclass
  `PaymentResult(external_invoice_id, payment_status, amount, paid_to_date, balance, last_payment_date)`.
- New `fetch_invoice_payment(external_invoice_id) -> PaymentResult` dispatching on
  `settings.INVOICE_PROVIDER_MODE` (`stub` / `invoiceninja`).
- **Stub mode** returns deterministic data: `payment_status="unpaid"`,
  `paid_to_date=0.00`, `balance=amount`, `last_payment_date=None`. Keeps tests and
  LAN stub-mode fully exercisable. (Stub may accept an override hook if a test needs
  a `paid` projection — kept minimal.)

### `apps/integrations/invoice_ninja.py` (concrete provider)
- `fetch_invoice_payment` performs `GET /api/v1/invoices/{id}` via the existing
  `_request` (reusing the status→exception map incl. 429→Transient) and `_unwrap`.
- Maps IN's `status_id` to `payment_status`:
  `4 → paid`, `3 → partial`, anything else (1 draft / 2 sent / …) → `unpaid`.
  Also derives `payment_status` defensively from amounts when `status_id` is absent
  (`balance == 0 and paid_to_date > 0 → paid`; `paid_to_date > 0 → partial`).
- Reads `amount`, `paid_to_date`, `balance`; extracts the latest payment date from
  the invoice payment data when present (else `None`).
- **Exact IN field names + payment-date location are confirmed against the live
  instance during validation** — the mapping above is the design intent; live
  validation may correct field paths (this is the expected P3/P5-style fix loop).

### Deferred Slice-B hardening (folded in here)
- `ensure_product`: look up an existing product by `product_key` (the derived
  `membership_plan_product_key`) **before** creating; reuse the found id. Closes the
  crash-window where the IN POST succeeds but the Django `save()` fails.
- `ensure_client`: send `custom_value1=guardian.pk` on create and look up an existing
  client by it before creating; reuse the found id. Same crash-window closure.

## 5. Sync jobs

### `apps/integrations/tasks.py`
- `sync_billing_payments()` — **scheduled batch sweep** (nightly entry point):
  - Iterates `BillingInvoice` rows that have an `external_invoice_id`.
  - For each: `fetch_invoice_payment`, write the payment fields + `last_synced_at`.
  - Per-row transient/terminal errors are **caught and logged**; the row keeps its
    prior projection and is retried next run. One bad row never aborts the sweep.
  - After processing, rolls up `payment_status` + `payment_synced_at` on each touched
    `BillingRecord`.
  - Does **not** raise `RetryableInvoiceError` — it is a scheduled sweep, not a
    single-record retryable task.
- `sync_billing_record_payments(record_id)` — **manual single-record** entry point
  for the admin action:
  - Same per-invoice fetch + write + roll-up, scoped to one record.
  - Terminal errors **are** surfaced onto `BillingRecord.external_error_code` (via the
    existing Latvian mapping) so the manual action gives visible feedback.
  - `enqueue_sync_billing_record_payments(record_id)` helper mirrors the existing
    `enqueue_push_billing_record` pattern (swallows `RetryableInvoiceError` in sync
    mode the same way).

## 6. Schedule registration

Idempotent data migration `apps/billing/migrations/0005_*`:
- `django_q.models.Schedule.objects.get_or_create(name="billing-payment-sync", defaults={...})`
  with `func="apps.integrations.tasks.sync_billing_payments"`,
  `schedule_type=Schedule.DAILY`, and `next_run` computed at the configured hour.
- New setting `BILLING_PAYMENT_SYNC_HOUR` (default `3`, i.e. 03:00 local) feeds the
  `next_run` time. The created `Schedule` row remains editable in Django admin →
  satisfies "configurable cadence" (item 9). At-least-nightly via `DAILY`.
- Reverse migration deletes the named `Schedule` row only.

## 7. Admin sync health + retry

### `BillingRecordAdmin`
- New confirmed-only action **"Pārbaudīt maksājumus (Invoice Ninja)"** →
  `enqueue_sync_billing_record_payments`. Drafts skipped with a Latvian warning
  (mirrors the push action).
- `payment_status` + `payment_synced_at` added to `list_display` and read-only detail;
  `list_filter` on `payment_status`.
- Push-side sync health/retry already exists from Slice B (`external_status` /
  `external_error_code` columns + the push action re-enqueuing `failed` confirmed
  records) — item 8 is therefore covered for both push and read-back.

### `BillingInvoice` (inline on the record, or detail)
- Surface per-invoice `payment_status`, `paid_to_date`, `balance`,
  `last_payment_date`, `last_synced_at` so staff see exactly which installment is
  outstanding.

## 8. Trigger verification (items 1–2) + cosmetic debt

- Test asserting: an electronic agreement reaching `signed` (the "completed" final
  state) auto-creates a draft `BillingRecord` via the existing `agreement_signed`
  signal. Documents "signed = completed." No trigger rebuild.
- AGENTS.md note recording the "signed = completed" interpretation.
- `backfill_billing` honest created-count fix (it currently over-reports by counting
  already-existing matching records).

## 9. Live Invoice Ninja validation (in scope)

Because the IN instance now exists and the Slice B push path was only stub-verified,
Slice C includes a real end-to-end run against it (`INVOICE_PROVIDER_MODE=invoiceninja`):

1. **Push path (Slice B):** confirm a `BillingRecord` → push action → verify in IN that
   the product, client, and per-installment invoices are created with correct numbers,
   `product_key`, net amounts, and the Latvian sibling-discount note; verify idempotent
   re-push; verify the dedup hardening (no duplicate product/client on a forced retry).
2. **Read-back path (Slice C):** mark an invoice paid/partial in IN → run
   `sync_billing_payments` (and the manual action) → verify the projection
   (`payment_status`, `paid_to_date`, `balance`, `last_payment_date`) lands on
   `BillingInvoice` and rolls up to `BillingRecord`.
3. **Schedule:** confirm the `Schedule` row fires under the running `qcluster`.

Expect this to surface integration bugs the stub hid (auth/header/field-name/response-
shape — the recurring P3/P5 pattern). Fix and re-verify live before sign-off. Evidence
recorded in AGENTS.md (and a short `docs/` note if the bug set is non-trivial).

## 10. Testing (stub-mode, repo conventions)

HTTP + enqueue spies use `unittest.mock.patch` / `monkeypatch` (the repo does **not**
use `responses` / `pytest-mock`). Reuse conftest fixtures from their existing homes.

- adapter: stub vs real-mode dispatch; `PaymentResult` shape.
- `fetch_invoice_payment`: `status_id` → `payment_status` mapping; amount-derived
  fallback; transient (429/5xx/timeout) → exception; auth/404 mapping.
- `sync_billing_payments`: multi-invoice roll-up; per-row error isolation (one bad row
  doesn't abort); `last_synced_at` / `payment_synced_at` set.
- `sync_billing_record_payments`: terminal error surfaced on `external_error_code`.
- `ensure_product` / `ensure_client`: dedup-lookup reuses existing id; create only when
  absent; `custom_value1=guardian.pk` sent.
- schedule migration: idempotent `get_or_create`; reverse deletes only the named row.
- trigger verification: signed electronic agreement → draft `BillingRecord`.
- `backfill_billing`: honest created-count.

## 11. Out of scope

- Real-time payment webhooks from IN (nightly sweep is the agreed mechanism for item 9).
- Void / regenerate-after-push of invoices.
- Any agreement-side change (P5 is closed).
- New billing business rules beyond the payment projection.

## 12. Gate

`uv run pytest -q` green, `uv run ruff check .` clean, `uv run mypy .` clean, plus the
live-IN validation evidence (§9) before P6 sign-off.

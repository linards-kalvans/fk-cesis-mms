# P6 Slice B — Invoice Ninja push integration (design)

**Date:** 2026-06-07
**Status:** Design approved, pending spec review
**Predecessor:** P6 Slice A (local billing domain + sibling-discount engine, delivered + LAN-signed-off 2026-06-07)

## Purpose

Push the local billing domain to a self-hosted Invoice Ninja (IN) instance so the club
can issue and collect membership-fee invoices. Slice B is **push-only and
admin-confirmed**: staff confirm a `BillingRecord`, then deliberately push it, which
syncs the plan as an IN product, ensures the guardian exists as an IN client, and
creates one IN invoice per installment. Payment read-back, webhooks, and sync-health
reconciliation are **Slice C** and explicitly out of scope here.

## Decisions (locked during brainstorming)

1. **Direction of truth.** Django is the source of truth for prices, amounts, and
   schedules. It pushes invoices to IN. IN pushes payment status back — but that is
   Slice C. Slice B is one-way (Django → IN).
2. **Guardian → IN Client.** The payer is the guardian, not the child. Invoices bill the
   guardian-as-client; the child appears only as line-item text.
3. **MembershipPlan → IN Product (mirrored).** Each plan is mirrored as an IN product,
   synced from Django, referenced on invoice lines by `product_key`. Django stays the
   price authority; the product is its mirror.
4. **BillingRecord → N discrete invoices.** Upfront mode = 1 invoice. Installments =
   one IN invoice per `derive_installment_schedule()` row (incl. the unequal last one),
   each with that row's `due_date` and net amount. IN computes nothing.
5. **Per-child invoices (no consolidation).** Each child's `BillingRecord` produces its
   own invoice stream to the guardian-client. 1 invoice = 1 `BillingInvoice` row = a
   slice of 1 `BillingRecord`, keeping payment read-back and retries trivial and
   matching the staggered per-child signing trigger.
6. **Discount display = net amount + note.** Each line bills the actual net amount owed
   and references the product by key; the sibling discount is conveyed in a Latvian
   line/invoice note, not IN's native discount field. Uniform across upfront and
   installments (no per-installment discount splitting). Discount reporting already
   lives in Django (`BillingRecord.discount_amount`).

## Architecture

Mirrors the proven DocuSeal integration in `apps/integrations/`.

| Layer | DocuSeal (existing) | Invoice Ninja (new) |
|-------|--------------------|--------------------|
| Boundary: exception taxonomy + stub/real dispatch + frozen result dataclasses | `apps/integrations/agreement_platform.py` | `apps/integrations/invoice_platform.py` |
| Concrete HTTP provider | `apps/integrations/docuseal.py` | `apps/integrations/invoice_ninja.py` |
| Background jobs (django-q2) | `apps/integrations/tasks.py` | extend `apps/integrations/tasks.py` |
| Mode + credentials (settings/env) | `AGREEMENT_PROVIDER_MODE`, `DOCUSEAL_API_URL/KEY` | `INVOICE_PROVIDER_MODE`, `INVOICE_NINJA_API_URL/KEY`, `INVOICE_NINJA_NUMBER_PREFIX` |

**Provider modes:** `stub` (default; deterministic, no network) and `invoiceninja`
(real). Real auth = `X-Api-Token` header against `{INVOICE_NINJA_API_URL}` (e.g.
`https://host/api/v1`).

**Settings (env-driven, mirroring the existing block in `fk_cesis_mms/settings.py`):**
```python
INVOICE_PROVIDER_MODE   = os.environ.get("INVOICE_PROVIDER_MODE") or "stub"
INVOICE_NINJA_API_URL   = os.environ.get("INVOICE_NINJA_API_URL", "")
INVOICE_NINJA_API_KEY   = os.environ.get("INVOICE_NINJA_API_KEY", "")
INVOICE_NINJA_NUMBER_PREFIX = os.environ.get("INVOICE_NINJA_NUMBER_PREFIX") or "MMS"
```

## Data model changes

```
Guardian        + external_client_id    CharField(blank)     ← IN client id
MembershipPlan  + external_product_id   CharField(blank)     ← IN product id
BillingRecord   + external_status       "" | pending | synced | failed   (mirrors Agreement.external_state)
                + external_error_code   CharField(blank)

NEW  BillingInvoice(TimeStampedModel)    ← one row per installment (upfront = N=1)
       billing_record       FK → BillingRecord, related_name="invoices"
       sequence             PositiveSmallIntegerField   (1-based)
       due_date             DateField
       amount               DecimalField                (net; from derive_installment_schedule)
       external_invoice_id  CharField(blank)
       external_status      "" | created | failed       ← Slice C adds payment status here
       external_error_code  CharField(blank)
       Meta: UniqueConstraint(fields=["billing_record", "sequence"])
```

- `product_key` is **not a stored column** — it is derived deterministically from
  `plan.season` by a single helper (e.g. `2026/2027` → `biedra-maksa-2026-2027`), so
  there is no risk of drift between Django and the IN product reference. Only
  `external_product_id` is persisted.
- `BillingInvoice` rows are **materialized at push time** from
  `derive_installment_schedule(final_amount)` — draft records stay clean until staff
  confirm + push. The table is the natural home for Slice C per-installment payment
  status.
- Migrations: one for the `Guardian`/`MembershipPlan`/`BillingRecord` field additions,
  one for the new `BillingInvoice` model (or a single combined migration).

## The push flow

**Trigger — admin-confirmed.** `BillingRecordAdmin` action
**"Izrakstīt rēķinus (Invoice Ninja)"**:
- Acts only on `status=confirmed` records; a draft selection is refused with a Latvian
  message (`Vispirms apstipriniet ierakstu.`).
- Enqueues one django-q job per selected record.
- Optional companion `MembershipPlanAdmin` action **"Sinhronizēt produktu"** to
  pre-create/update the IN product; not required because the push job ensures the
  product anyway.

**Job `push_billing_record(record_id)`** (in `apps/integrations/tasks.py`), ordered so
each step is independently idempotent:

1. **Ensure product.** If `plan.external_product_id` is empty, create an IN product
   from the plan (`product_key`, price = `annual_amount`, Latvian notes) and store the
   id; else skip (optionally update price).
2. **Ensure client.** If `guardian.external_client_id` is empty, create an IN client
   from the guardian (name + email contact) and store the id; else skip.
3. **Materialize installments.** If `record.invoices` is empty, create the
   `BillingInvoice` rows from `derive_installment_schedule(final_amount)` (upfront →
   single row, due = first installment date).
4. **Create invoices.** For each `BillingInvoice` lacking an `external_invoice_id`:
   create one IN invoice and store the returned id + `external_status="created"`.
5. **Roll up.** Set `record.external_status = "synced"` if every row succeeded, else
   `"failed"` with the first error code.

**Per-invoice payload:**
```
line = { product_key: plan.product_key,
         notes: "Biedra maksa — {child} — {season}"  (+ "  Ietverta {p}% atlaide — {n}. bērns" if sibling),
         cost: installment.amount,    quantity: 1 }
invoice = { client_id: guardian.external_client_id,
            number: "{INVOICE_NINJA_NUMBER_PREFIX}-{record}-{seq}",
            date: today,
            due_date: installment.due_date,
            line_items: [line] }
```

Re-running the action is safe: steps 1, 2, 4 skip work already done (external ids
present). A partially-failed push re-pushes only the rows still missing an
`external_invoice_id`.

## Idempotency & error handling

**Exception taxonomy** (in `invoice_platform.py`, mirroring DocuSeal):
```
InvoicePlatformError
 ├─ InvoicePlatformConfigError    missing creds / unknown mode    → permanent
 ├─ InvoicePlatformAuthError      401 / 403                       → permanent
 ├─ InvoicePlatformNotFoundError  404                             → permanent
 └─ InvoicePlatformTransientError 5xx / timeout / connection      → retryable
```
The job classifies: transient → raise `RetryableInvoiceError` so the django-q cluster
retries; terminal → persist `external_status="failed"` + `external_error_code` on the
affected `BillingInvoice` and roll up to the record, then return cleanly. Per-row
granularity means one bad invoice doesn't abort the rest.

**Double-create hazard.** An IN invoice is created but we crash before storing its id;
a retry could double-create. Guard with the deterministic invoice `number`
`{PREFIX}-{record}-{seq}` — IN enforces unique invoice numbers, so the retry gets a 4xx
"number exists". The provider treats that specific case as "already created": it looks
the invoice up by number, recovers the id, and stores it rather than erroring.
Product/client creation is guarded the same way by their stored external ids.

**Recovery surface.** `BillingRecordAdmin` shows `external_status`; a failed record
exposes the Latvian error and lets staff re-run the same action to retry only the
failed rows (matching the DocuSeal "Mēģināt vēlreiz" pattern).

## Latvian copy

A billing copy module (extends `apps/billing/messages.py`), all guardian-facing text in
Latvian:
- Line label: `Biedra maksa — {child_name} — {season}`
- Sibling discount note (only on the discounted child's invoices):
  `Ietverta {percent}% atlaide — {n}. bērns`
- Product name/notes: `Biedra maksa {season}`
- `get_invoice_error_message(code)` — error-code → Latvian message map with a generic
  fallback (same shape as `apps/agreements/messages.py`).
- Admin action feedback: `Izrakstīti {n} rēķini.` / `Rēķins jau izrakstīts.` /
  `Vispirms apstipriniet ierakstu.`

## Testing strategy

TDD throughout; `stub` mode keeps everything offline. HTTP/enqueue spies use
`unittest.mock` / `monkeypatch` (repo convention — no `responses`, no `pytest-mock`).

- **Pure builders** (no network): `derive_installment_schedule` → `BillingInvoice`
  rows; line-item/invoice payload assembly — net amounts, `product_key`, deterministic
  `number` with the configurable prefix, discount note present only on siblings.
- **Idempotency:** re-running the push creates no duplicate rows/invoices; the
  "number already exists" path recovers the id; product/client ensured exactly once.
- **Error classification:** 401→Auth, 404→NotFound, 5xx/timeout→Transient→retryable;
  terminal failures persist `failed` + `error_code` at row and record level.
- **Provider unit tests** (`invoice_ninja.py`): `X-Api-Token` header, base-URL
  construction, status→exception mapping.
- **Admin action integration:** confirmed record → enqueues push → stub creates
  invoices → `external_status="synced"`; draft record refused.
- **Full gate:** `uv run pytest -q && uv run ruff check . && uv run mypy .`.

## Out of scope (deferred to Slice C)

- Payment status read-back (IN → Django), updating `BillingInvoice.external_status` with
  paid/partial/overdue.
- IN webhooks + signature verification for payment events.
- Void/regenerate invoices when a confirmed record or plan is edited after push.
- Sync-health / reconciliation dashboard and dunning configuration.

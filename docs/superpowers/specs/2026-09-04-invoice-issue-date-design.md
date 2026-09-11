# Invoice issue date — billing-month first day

*Design spec. Date: 2026-09-04.*

## 1. Problem

Invoice Ninja invoice payloads (`date` field) have used the **current date** (the moment `create_invoice` runs) instead of the billing month the installment covers. When a parent receives an invoice via IN's email for, say, September, the IN invoice shows today's date — which is wrong and confusing. The `due_date` is correct (e.g. `2026-09-20`), but the `date` field is a moving target.

## 2. Rule

Every new Invoice Ninja invoice creation — both installment and upfront — sets:

```
date = billing_invoice.due_date.replace(day=1).isoformat()
```

In other words: **the first calendar day of the due_date month**.

Examples:
- `due_date = 2027-09-20` → `date = "2027-09-01"`
- `due_date = 2027-08-20` (upfront) → `date = "2027-08-01"`
- `due_date = 2026-11-01` (already day 1) → `date = "2026-11-01"`

## 3. Scope

**In scope:**
- The `date` field in the Invoice Ninja invoice-create payload (`POST /invoices`).
- Both installment and upfront payment modes.
- Only **new** invoice creations (the push path via `create_invoice`).

**Out of scope:**
- Existing external invoices already created in Invoice Ninja.
- Changing `BillingInvoice.due_date`.
- Schema migrations.
- New payload fields beyond `date`.
- Jobs or admin UI changes.
- Public notes, line items, credit notes.

## 4. Data flow

```
BillingInvoice.due_date (e.g. 2027-09-20)
    │
    ▼
_build_invoice_body() → "date": due_date.replace(day=1).isoformat()
    │
    ▼
create_invoice() → POST /invoices with { ..., "date": "2027-09-01", ... }
    │
    ▼
Invoice Ninja stores the invoice with date = 2027-09-01
```

The `due_date` field itself is unchanged — it still carries the actual due date (e.g. `2027-09-20`). Only the `date` payload field is affected.

## 5. Implementation

`apps/integrations/invoice_ninja.py::_build_invoice_body` — changed from the previous `date` value (which was the current date at push time) to:

```python
"date": billing_invoice.due_date.replace(day=1).isoformat(),
```

`django.utils.timezone` remains imported because `_build_credit_note_body` still uses `timezone.now().date().isoformat()` for credit note creation — this is out of scope and intentional (credit notes are created at the moment of the adjustment, not tied to a billing month).

## 6. Testing

**File:** `tests/integrations/test_invoice_ninja_provider.py`

| Test | What it verifies |
|------|-----------------|
| `test_build_invoice_body_shape` | Fixture `due_date = 2026-11-01` (already day 1) → `date == "2026-11-01"` (baseline shape test retained) |
| `test_public_notes_installment_period_uses_due_date` | `due_date = 2027-09-20` → `date == "2027-09-01"` (non-first installment) |
| `test_public_notes_upfront_period_normalized_season` | `due_date = 2027-08-20` (upfront mode) → `date == "2027-08-01"` (upfront) |
| `test_build_invoice_body_no_new_http_fields` | Payload keys unchanged — no new fields introduced |

## 7. Verification evidence

| Check | Result |
|-------|--------|
| `uv run pytest tests/integrations/test_invoice_ninja_provider.py -q` | 17 passed |
| `uv run pytest -q` (full suite) | 2139 passed |
| `uv run ruff check .` | clean |
| `uv run mypy .` | exit 0 (existing annotation-unchecked notes, unchanged) |
| `uv run python manage.py makemigrations --check` | no changes |

## 8. Acceptance

1. Installment invoice with `due_date = 2027-09-20` → payload `date = "2027-09-01"`.
2. Upfront invoice with `due_date = 2027-08-20` → payload `date = "2027-08-01"`.
3. Invoice already on the 1st → `date` unchanged (idempotent edge).
4. No new payload keys, no schema changes, no migration.
5. Credit notes still use `timezone.now()` — untouched.

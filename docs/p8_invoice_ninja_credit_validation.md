# P8 Invoice Ninja credit-note validation

Date: 2026-06-30
Environment: Invoice Ninja sandbox

## Findings

### Read credits list

- `GET /api/v1/credits?per_page=1` returns **200** with a JSON list.
- Script: `scripts/validate_invoice_ninja_credit.py` (safe mode).

### Create credit note

- `POST /api/v1/credits` accepts a payload with:
  - `client_id`
  - `number`
  - `date`
  - `public_notes`
  - `line_items` (each with `product_key`, `notes`, `cost`, `quantity`)
- Live sandbox observation: a line item with **positive** `cost="10.00"` returns a
  credit whose `amount` is `10`. A negative `cost` would create a credit with a
  negative amount, which is not the desired accounting for a credit note.
- **Fix applied:** `apps/integrations/invoice_ninja.py::_build_credit_note_body`
  now uses `cost=str(adjustment.amount)` (positive), not `str(-adjustment.amount)`.
- Result: **create credit note PASS** against sandbox.

### Apply credit to invoice

- `POST /api/v1/credits/bulk` with `action="apply"` and an `invoices` payload
  returns **422** with body `{"message":"The given data was invalid.","errors":{"action":["The selected action is invalid."]}}`.
- Confirmed live against sandbox credit `Opnel5aKBz` (client `kzPdy7aQro`).
- Result: **auto-apply is unsupported** by this Invoice Ninja API path.

### App fallback

- The adapter returns `CreditApplyResult(applied=False, external_status="unsupported")`.
- `create_credit_note_job` sets `BillingAdjustment.requires_staff_apply=True` and
  leaves `external_status="created"`.
- This fallback is covered by automated tests
  (`tests/integrations/test_credit_note_tasks.py::test_create_credit_note_job_applies_fallback_when_apply_not_supported`).

## Result

| Check | Status |
|---|---|
| Read credits list | PASS |
| Create credit note (positive `cost`) | PASS |
| Auto-apply credit to invoice | Unsupported by API; app fallback (`requires_staff_apply=True`) verified by tests |
| Paid invoice block | App-side design; no API call required |

## Operational note

When discontinuing a member with sent unpaid invoices, staff must still manually
apply the created credit note to the target invoice in Invoice Ninja until a
supported apply endpoint is discovered.

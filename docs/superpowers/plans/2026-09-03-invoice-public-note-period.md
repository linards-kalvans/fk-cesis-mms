# Invoice Ninja public-note period + heading — delivered

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate Invoice Ninja `public_notes` with a Latvian heading + period line per invoice, so parents see what each invoice covers (member name, season, installment month or season). Line-item notes remain generic to avoid catalog-product pollution.

**Architecture:** A pure function `invoice_public_note(record, billing_invoice)` in `apps/billing/messages.py` computes the newline-separated text. `apps/integrations/invoice_ninja.py::_build_invoice_body` passes it to the `public_notes` field of the invoice-create payload. No schema change, no data migration, no new IN fields/calls.

**Tech Stack:** Django 5.x, pytest-django, `uv run` for everything (pytest/ruff/mypy/manage.py). SQLite for tests.

Spec: `docs/superpowers/specs/2026-09-03-invoice-public-note-period-design.md`.

---

## File Structure

- `apps/billing/messages.py` — modify: add new period/normalization helpers (`_normalize_season`, `_installment_period_line`, `_upfront_period_line`, `_INSTALLMENT_MONTH_ACCUSATIVE`), update `invoice_public_note` to accept `billing_invoice` and emit the new heading/period lines; `sibling_discount_note` existed and is unchanged.
- `apps/integrations/invoice_ninja.py` — modify `_build_invoice_body` to pass `messages.invoice_public_note(record, billing_invoice)` as `public_notes`; `_build_line_item` was already generic and remains unchanged.
- Tests (new):
  - `tests/billing/test_invoice_messages.py` — 24 tests covering heading, period lines (installment + upfront), season normalization, discount line, error-message fallback, payment-status labels.
  - `tests/integrations/test_invoice_ninja_provider.py` — 17 tests covering payload shape, `public_notes` content (installment + upfront + discounted + no-PII), no-new-http-fields, duplicate-number recovery, archive/cancel HTTP shapes, ensure_client contacts.

**Conventions discovered (use these, don't reinvent):**
- The push test pattern + fixtures live in `tests/billing/test_push_billing_record.py` and `tests/billing/conftest.py`: fixtures `active_plan` (installment_count=10, first_installment_month=9), `guardian` (email `anna@example.com`), `member`.
- The `pytest.mark.external_contract` marker annotates tests that exercise the IN HTTP contract (payload shape, header presence, status→exception mapping).
- The `_build_invoice_body` test pattern uses `_record()` from the test file to create a DB-backed `BillingRecord` + `BillingInvoice`, then asserts on the dict returned by the private builder.
- The `override_settings(**INVOICE_NINJA)` pattern sets `INVOICE_PROVIDER_MODE=invoiceninja` + URL/key for the duration of each test.

---

## File-by-file TDD steps (already performed)

### Task 1: `apps/billing/messages.py` — `invoice_public_note` + helpers

**Files:**
- Modify: `apps/billing/messages.py` (the file was updated — the function + helpers were added alongside the existing `PAYMENT_MODE_LABELS`, `PAYMENT_STATUS_LABELS`, `invoice_line_label`, `get_invoice_error_message`).

- [x] **Step 1: Write the failing tests**

`tests/billing/test_invoice_messages.py` (24 tests):

- `test_invoice_public_note_installment_period_from_due_date` — installment mode, `due_date=2027-09-20` → heading + `Maksājums par 2027. gada septembri`.
- `test_invoice_public_note_installment_period_month_names` — 12 parametrized cases covering all accusative month forms.
- `test_invoice_public_note_upfront_period_normalized_season` — upfront mode, season `2026/2027` → `Maksājums par 2026./2027. gada sezonu`.
- `test_invoice_public_note_upfront_period_season_forms` — 3 parametrized cases (`2027/2028`, `2027./2028.`, `2027./2028..`) all normalize to `2027./2028.`.
- `test_invoice_public_note_discounted_third_line` — `is_full_price=False` → third line `Ietverta 50% atlaide`.
- `test_invoice_public_note_full_price_has_no_discount_line` — `is_full_price=True` → no discount line, exactly one newline.
- `test_sibling_discount_note_uses_percent` — 50% → `Ietverta 50% atlaide`.
- `test_sibling_discount_note_fractional_percent` — 33.33% → `Ietverta 33.33% atlaide`.
- `test_product_name` — generic line-item name.
- `test_error_message_fallback` — known code + unknown code fallback.
- `test_payment_status_labels_latvian` — all four labels verified.

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_invoice_messages.py -v`
Expected: FAIL — the new two-argument `invoice_public_note(record, billing_invoice)` call fails with the existing one-argument version, producing obsolete `Biedra maksa — <member> — <season>` output.

- [x] **Step 3: Implement the function + helpers**

In `apps/billing/messages.py`, add:

```python
_INSTALLMENT_MONTH_ACCUSATIVE = {
    1: "janvāri", 2: "februāri", 3: "martu", 4: "aprīli",
    5: "maiju", 6: "jūniju", 7: "jūliju", 8: "augustu",
    9: "septembri", 10: "oktobri", 11: "novembri", 12: "decembri",
}

def _normalize_season(season: str) -> str:
    return "/".join(part.rstrip(".") + "." for part in season.split("/"))

def _installment_period_line(billing_invoice) -> str:
    due = billing_invoice.due_date
    return f"Maksājums par {due.year}. gada {_INSTALLMENT_MONTH_ACCUSATIVE[due.month]}"

def _upfront_period_line(record) -> str:
    return f"Maksājums par {_normalize_season(record.season)} gada sezonu"

def sibling_discount_note(record) -> str:
    percent = f"{record.sibling_discount_percent_applied:.2f}".rstrip("0").rstrip(".")
    return f"Ietverta {percent}% atlaide"

def invoice_public_note(record, billing_invoice) -> str:
    lines = [
        f"Futbola treniņu un spēļu nodrošināšana — {record.member.full_name} — {record.season}"
    ]
    if record.payment_mode == record.PaymentMode.UPFRONT:
        lines.append(_upfront_period_line(record))
    else:
        lines.append(_installment_period_line(billing_invoice))
    if not record.is_full_price:
        lines.append(sibling_discount_note(record))
    return "\n".join(lines)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_invoice_messages.py -v`
Expected: PASS (24 passed).

- [ ] **Step 5: Commit**

Commit intentionally not performed; user did not request one.

---

### Task 2: `apps/integrations/invoice_ninja.py` — wire `public_notes`

**Files:**
- Modify: `apps/integrations/invoice_ninja.py` — `_build_invoice_body` changes its call to `invoice_public_note` to pass `billing_invoice`; `_build_line_item` was already generic and remains unchanged.

- [x] **Step 1: Write the failing tests**

`tests/integrations/test_invoice_ninja_provider.py` (17 tests):

- `test_build_invoice_body_shape` — asserts `public_notes` contains heading + installment period; line-item notes are generic (no member name, no Latvian text).
- `test_sibling_note_appended_for_discounted` — discounted record → third line in `public_notes`, not in line-item notes.
- `test_public_notes_installment_period_uses_due_date` — mutating `due_date` changes the period line.
- `test_public_notes_upfront_period_normalized_season` — upfront mode → normalized season in period line.
- `test_public_notes_never_contain_personal_id` — member with `personal_id` → ID absent from `public_notes`.
- `test_build_invoice_body_no_new_http_fields` — payload keys are exactly `{client_id, number, date, due_date, public_notes, line_items}`.
- `test_create_invoice_posts_and_returns_id` — HTTP call shape (headers, URL, method).
- `test_auth_error_maps_to_auth_exception` — 401 → `InvoicePlatformAuthError`.
- `test_timeout_maps_to_transient` — timeout → `InvoicePlatformTransientError`.
- `test_rate_limit_maps_to_transient` — 429 → `InvoicePlatformTransientError`.
- `test_http_408_maps_to_transient` — 408 → `InvoicePlatformTransientError`.
- `test_duplicate_number_recovers_existing_id` — 422 with "already been taken" → recovery lookup.
- `test_archive_invoice_posts_to_bulk_archive` — archive HTTP shape.
- `test_cancel_invoice_posts_to_bulk_cancel_with_reason` — cancel HTTP shape + reason.
- `test_archive_invoice_auth_error_maps` — archive 401 → `InvoicePlatformAuthError`.
- `test_cancel_invoice_timeout_maps_to_transient` — cancel timeout → `InvoicePlatformTransientError`.
- `test_ensure_client_posts_name_parts_in_contacts` — contacts split first/last name.

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integrations/test_invoice_ninja_provider.py -v`
Expected: FAIL — `_build_invoice_body` passes a two-argument call that mismatches the existing one-argument `invoice_public_note` signature.

- [x] **Step 3: Wire `public_notes` in `_build_invoice_body`**

In `apps/integrations/invoice_ninja.py`, modify `_build_invoice_body`:

```python
def _build_invoice_body(record, billing_invoice) -> dict:
    return {
        "client_id": record.member.guardian.external_client_id,
        "number": _number(record, billing_invoice.sequence),
        "date": timezone.now().date().isoformat(),
        "due_date": billing_invoice.due_date.isoformat(),
        "public_notes": messages.invoice_public_note(record, billing_invoice),
        "line_items": [_build_line_item(record, billing_invoice)],
    }
```

Note: `_build_line_item` was already generic (`notes: messages.product_name(record.plan)`) before this feature and is unchanged.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integrations/test_invoice_ninja_provider.py -v`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

Commit intentionally not performed; user did not request one.

---

## Verification

### Targeted test suite (delivered)

```bash
uv run pytest tests/billing/test_invoice_messages.py tests/integrations/test_invoice_ninja_provider.py -v
```
Expected: **41 passed**, 0 failed.

### Full repo gate

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```
**Status:** Full repo gate is currently blocked by unrelated MedicalPermit test/import failures. This is a pre-existing repository condition, not a limitation of this feature. The targeted suite passes cleanly.

---

## Self-Review Notes

- **Spec coverage:** §2 heading + period → `invoice_public_note` (Task 1). §3 exact text examples → all 12 accusative forms + upfront normalization + discount line verified by targeted tests. §4 data flow → `messages.invoice_public_note` → `invoice_ninja._build_invoice_body` (Task 2). §5 privacy/scope → `public_notes_never_contain_personal_id` test; line-item notes were already generic before this feature. §6 verification → all 7 acceptance criteria covered by tests.
- **Normalization invariant:** `_normalize_season` strips trailing dots from each part and re-adds exactly one — `2027/2028` → `2027./2028.`, `2027./2028..` → `2027./2028.`. No double-dot leakage verified by parametrized test.
- **Month accusative coverage:** All 12 Latvian accusative month forms are explicit in `_INSTALLMENT_MONTH_ACCUSATIVE` and each is asserted by the parametrized test `test_invoice_public_note_installment_period_month_names`.
- **Discount line gating:** `sibling_discount_note` uses `record.is_full_price`; the third line is present only for discounted records. Full-price records have exactly one `\n` (heading + period, no discount).
- **No schema/data migration:** The change is purely at the invoice-create payload boundary. Existing IN invoices are untouched. No new database columns, no `RunPython` operations.
- **Payload shape invariant:** `_build_invoice_body` returns exactly six keys: `client_id`, `number`, `date`, `due_date`, `public_notes`, `line_items`. Verified by `test_build_invoice_body_no_new_http_fields`.

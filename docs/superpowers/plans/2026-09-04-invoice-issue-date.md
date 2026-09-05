# Invoice issue date — billing-month first day

> **Delivery record.** Implementation is complete. This plan documents the work that was done.

**Goal:** Set the Invoice Ninja invoice-create payload `date` field to the first day of the billing month (derived from `BillingInvoice.due_date`) instead of the current date at push time.

**Architecture:** A single-line change in `_build_invoice_body` (`apps/integrations/invoice_ninja.py`). The `due_date` field is unchanged; only the `date` payload field is affected. Credit notes remain on `timezone.now()` (out of scope).

**Tech Stack:** Django 5.x, pytest-django, `uv run` for everything (pytest/ruff/mypy/manage.py). SQLite for tests.

Spec: `docs/superpowers/specs/2026-09-04-invoice-issue-date-design.md`.

---

## File Structure

- `apps/integrations/invoice_ninja.py` — `_build_invoice_body`: `date` → `billing_invoice.due_date.replace(day=1).isoformat()`
- `tests/integrations/test_invoice_ninja_provider.py` — date assertions added to 3 pre-existing tests: `test_build_invoice_body_shape`, `test_public_notes_installment_period_uses_due_date`, `test_public_notes_upfront_period_normalized_season` (the latter two also set/save distinct due dates)

**Conventions:** The test file uses `pytest.mark.external_contract`; fixtures `active_plan`, `guardian`; `override_settings` for IN config.

---

### Task 1: `_build_invoice_body` — date field

**Files:**
- Modify: `apps/integrations/invoice_ninja.py`
- Test: `tests/integrations/test_invoice_ninja_provider.py`

- [x] **Step 1: Write the failing tests**

Date assertions added to three pre-existing tests in `tests/integrations/test_invoice_ninja_provider.py`:

```python
@override_settings(**INVOICE_NINJA)
def test_public_notes_installment_period_uses_due_date(active_plan, guardian):
    """Non-first installment: due_date 2027-09-20 → date 2027-09-01."""
    rec, bi = _record(active_plan, guardian)
    bi.due_date = date(2027, 9, 20)
    bi.save(update_fields=["due_date"])
    body = invoice_ninja._build_invoice_body(rec, bi)
    assert body["date"] == "2027-09-01"


@override_settings(**INVOICE_NINJA)
def test_public_notes_upfront_period_normalized_season(active_plan, guardian):
    """Upfront: due_date 2027-08-20 → date 2027-08-01."""
    rec, bi = _record(active_plan, guardian, payment_mode=BillingRecord.PaymentMode.UPFRONT)
    bi.due_date = date(2027, 8, 20)
    bi.save(update_fields=["due_date"])
    body = invoice_ninja._build_invoice_body(rec, bi)
    assert body["date"] == "2027-08-01"
```

The existing `test_build_invoice_body_shape` was updated with a date assertion (fixture `due_date = 2026-11-01`, already day 1) — added `assert body["date"] == "2026-11-01"`.

- [x] **Step 2: Run tests to verify they fail**

All three date assertions failed against the old `timezone.now().date()` implementation. The shape test's due_date was already day 1, but the old code still returned the current date — expected `2026-11-01`, actual `2026-09-04`.

- [x] **Step 3: Implement the change**

In `apps/integrations/invoice_ninja.py::_build_invoice_body`, line 67:

```python
# Before:
# "date": timezone.now().date().isoformat(),

# After:
"date": billing_invoice.due_date.replace(day=1).isoformat(),
```

- [x] **Step 4: Run tests to verify they pass**

All three amended test functions passed; the targeted provider suite (`test_invoice_ninja_provider.py`) reported 17 passed.

- [x] **Step 5: Full verification**

```bash
uv run pytest tests/integrations/test_invoice_ninja_provider.py -q    # 17 passed
uv run pytest -q                                                      # 2139 passed
uv run ruff check .                                                   # clean
uv run mypy .                                                         # exit 0
uv run python manage.py makemigrations --check                        # no changes
```

- [ ] **Step 6: Commit** (deferred pending user instruction)

```bash
git add apps/integrations/invoice_ninja.py tests/integrations/test_invoice_ninja_provider.py
git commit -m "fix(invoice_ninja): use billing-month first day for invoice date field"
```

---

## Notes

- `django.utils.timezone` remains imported — `_build_credit_note_body` still uses `timezone.now().date().isoformat()` for credit notes (out of scope).
- No schema changes, no migrations, no new dependencies.
- Existing external invoices are unaffected.

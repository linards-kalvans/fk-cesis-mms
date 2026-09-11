# Invoice Ninja public-note refinement — period + heading

*Design spec. Delivered 2026-09-03. No schema change. No data migration.*

## 1. Problem

Invoice Ninja invoice `public_notes` carried `Biedra maksa — <member name> — <season>` — a generic
product-line label. The parent
could see member name and season but lacked a clear service description and payment-period detail. The
line-item `notes` field was already generic (`Biedra maksa <season>`) specifically to avoid shared-
product pollution via IN's "Update Products" behaviour.

This refinement changes only the `public_notes` wording and adds a per-installment period line;
the product line stays unchanged.

## 2. Approach (chosen)

Populate `public_notes` on every invoice create with a **newline-separated** Latvian heading +
period line + optional sibling-discount line. The line item stays generic (`Biedra maksa <season>`)
so the catalog product is never polluted.

- **Heading:** `Futbola treniņu un spēļu nodrošināšana — <member full name> — <record season>`
- **Period line:** differs by payment mode (see §3).
- **Discount line:** only present when `is_full_price == False`.

No new IN fields, no new IN API calls, no stored data. The text is computed at push time from the
`BillingRecord` + `BillingInvoice` objects.

## 3. Exact text contract

### Installment mode

One invoice per installment; the period line is derived from the **invoice's** `due_date`:

```
Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027
Maksājums par 2027. gada septembri
```

Full month accusative forms (12 entries):

| Month | Accusative |
|-------|-----------|
| 1 | janvāri |
| 2 | februāri |
| 3 | martu |
| 4 | aprīli |
| 5 | maiju |
| 6 | jūniju |
| 7 | jūliju |
| 8 | augustu |
| 9 | septembri |
| 10 | oktobri |
| 11 | novembri |
| 12 | decembri |

Format: `Maksājums par {year}. gada {accusative}`.

### Upfront mode

One invoice for the full amount; the period line uses the **record's** season, normalized:

```
Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027
Maksājums par 2026./2027. gada sezonu
```

Normalization rule: `2027/2028`, `2027./2028.`, and `2027./2028..` all become `2027./2028.` —
exactly one trailing dot per part, no double dots, no double dot before `gada`.

### Discounted records

The sibling-discount message is appended as a third line **only** when `is_full_price == False`:

```
Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027
Maksājums par 2027. gada septembri
Ietverta 50% atlaide
```

For fractional percents: `Ietverta 33.33% atlaide` (trailing zeros stripped, no trailing dot).

## 4. Data flow

```
BillingRecord + BillingInvoice
       │
       ▼
apps/billing/messages.invoice_public_note(record, billing_invoice)
       │
       ├── heading:  "Futbola treniņu un spēļu nodrošināšana — {member.full_name} — {record.season}"
       ├── period:   _installment_period_line(billing_invoice)  or  _upfront_period_line(record)
       └── discount: sibling_discount_note(record)  (if not is_full_price)
       │
       ▼
apps/integrations/invoice_ninja._build_invoice_body(record, billing_invoice)
       │
       public_notes: messages.invoice_public_note(record, billing_invoice)
       │
       ▼
POST /api/v1/invoices  (Invoice Ninja)
```

The function lives in `apps/billing/messages.py`; the call site is
`apps/integrations/invoice_ninja.py::_build_invoice_body`. No other consumers exist.

## 5. Privacy & scope

- `public_notes` is sent to Invoice Ninja **only** for future invoice-create payloads. Existing IN
  invoices are untouched (no re-push, no data migration).
- No personal IDs appear in the text. The member's `full_name` and the season are the only
  identifiers used.
- The line-item `notes` field stays generic (`Biedra maksa <season>`) — per-member text never
  touches the line item.
- Scope is restricted to the IN invoice-create path. Credit notes, payment read-back, and
  all other IN operations are unaffected.

## 6. Verification acceptance criteria

1. **Installment period** — `invoice_public_note` returns `Maksājums par {year}. gada {accusative}`
   for every due_date month (12 parametrized cases).
2. **Upfront normalization** — all three season inputs (`2027/2028`, `2027./2028.`, `2027./2028..`)
   produce `Maksājums par 2027./2028. gada sezonu`; no `2027./2028.. gada` leakage.
3. **Discount line** — present only when `is_full_price == False`; absent when `True`; exact
   newline-separated third line.
4. **No PII** — `public_notes` never contains a personal ID.
5. **Payload shape** — `_build_invoice_body` returns exactly the existing IN fields
   (`client_id`, `number`, `date`, `due_date`, `public_notes`, `line_items`); no new keys.
6. **Line-item purity** — `line_items[0].notes` never contains member names, Latvian text, or
   the heading.
7. **Targeted test suite** — 41 tests pass (`tests/billing/test_invoice_messages.py` +
   `tests/integrations/test_invoice_ninja_provider.py`).
8. **Full repo gate** — blocked by unrelated MedicalPermit work; not a limitation of this feature.

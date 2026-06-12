# LAN / Sandbox Acceptance — P6 Invoice Issue/Send Policy

**Date:** 2026-06-12
**Build under test:** `dev` branch (scheduled per-installment send; `billing/0008` sent_at + `billing/0009` schedule).
**Scope:** Verifies the create→issue→send path end-to-end against a **real Invoice Ninja sandbox/test company**. Functional unit/integration behavior is covered by the suite (1195 passed). This checklist is the deploy-sensitive, real-IN, real-email part.

## Setup

Against a local instance + `qcluster`, pointed at an Invoice Ninja **sandbox/test** company (never production):

```
INVOICE_PROVIDER_MODE=invoiceninja
INVOICE_NINJA_API_URL=<sandbox api base>
INVOICE_NINJA_API_KEY=<sandbox key>
BILLING_AUTOSEND_ENABLED=false   # flipped to true at S3
```

Use a **test guardian whose email you control** (so the invoice email lands somewhere you can read). The send can be triggered without waiting for the nightly schedule by calling the task directly, e.g.:

```
uv run python manage.py shell -c "from apps.integrations.tasks import send_due_invoices; send_due_invoices()"
```

(Invoice Ninja sends the invoice email itself — the app's email backend is not involved.)

## Checks

| # | Scenario | Steps | Expected | Result |
|---|----------|-------|----------|--------|
| S1 | No burst on push | Confirm + push an installment `BillingRecord` (e.g. 10 installments) | All installments appear in IN as **Draft**; **no** emails sent | |
| S2 | Autosend off = no-op | With `BILLING_AUTOSEND_ENABLED=false`, run `send_due_invoices` | Nothing sent; all invoices stay Draft | |
| S3 | Current installment sends | Set `BILLING_AUTOSEND_ENABLED=true`, restart `qcluster`, run `send_due_invoices` | The current-month installment flips Draft→**Sent** in IN; the test guardian receives **exactly one** invoice email; future installments stay Draft | |
| S4 | Idempotent | Run `send_due_invoices` again | No second email for the already-sent invoice; future installments still Draft | |
| S5 | No-email guardian | A confirmed+pushed record whose guardian has no email; run `send_due_invoices` | That invoice is **skipped** (left Draft), a warning is logged; no crash, other rows unaffected | |

## Notes

- `send_due_invoices` is gated by `BILLING_AUTOSEND_ENABLED`; after changing task code or the flag, restart the `qcluster` worker so it reloads.
- The nightly schedule (`billing-send-due-invoices`, daily at `BILLING_SEND_DUE_HOUR`, default 04:00 local) runs the same function automatically in deployment — the manual `shell -c` invocation above is only to exercise it on demand during acceptance.
- The "1st of due month" rule means: to see S3 actually send, the test record's current installment `due_date` must be in the current month (or overdue). A fresh record created this month satisfies this.

## Results — run YYYY-MM-DD

PENDING — to be filled in during the sandbox acceptance session.

## Recording results

Record pass/fail per row + build SHA here and add the sign-off line to the AGENTS.md "P6 invoice issue/send policy delivered" entry. **Prod activation** is a deliberate step: set `BILLING_AUTOSEND_ENABLED=true` only after S1–S5 pass.

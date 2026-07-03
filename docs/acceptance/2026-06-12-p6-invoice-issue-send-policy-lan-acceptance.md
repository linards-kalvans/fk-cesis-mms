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

## Results — run 2026-06-12 (build `dev` @ `f531706`, local `uv` instance, real IN at `in.mplytics.eu`)

Test guardian email `linards.kalvans+fktest@gmail.com`. A confirmed 3-installment record was pushed (real IN invoices); the first installment's local `due_date` was set to today (eligible), the other two to 2027 (future). The sweep was invoked via `manage.py shell -c` with the flag toggled per step. IN invoice `status_id` verified via the IN API (1 = Draft, 2 = Sent).

| # | Result | Evidence |
|---|--------|----------|
| S1 | ✅ PASS | Push created 3 IN invoices, all `status_id=1` (Draft); no emails. |
| S2 | ✅ PASS | `BILLING_AUTOSEND_ENABLED=false` → sweep no-op; due installment stayed `created` / `status_id=1`. |
| S3 | ✅ PASS | Flag on → due installment → local `sent` + `sent_at` set + IN `status_id=2` (Sent); future installments stayed Draft. **Parent invoice email received** ("Jauns rēķins MMS-10-1 no FK Cēsis", FK Cēsis branding, €100.00, "Apskatīt rēķinu", Latvian). |
| S4 | ✅ PASS | Re-run → `sent_at` unchanged (not re-sent); futures still Draft. |
| S5 | ✅ PASS | Due Draft invoice with empty-email guardian → skipped, left `created`, no crash, no IN call. |

Cleanup: the 3 test invoices were bulk-deleted (`is_deleted=True`) and the test client + product deleted on `in.mplytics.eu`; local SQLite DB restored.

**Operational finding (not a code defect):** Invoice Ninja also sent an admin "Invoice Sent" notification to the IN account owner. This is an IN per-user notification preference, not produced by this app (we make one bulk-`email` call per invoice). **Before prod activation, disable the IN "Invoice Sent" admin notification** (Settings → User Details → Notifications) so staff are not emailed once per installment during nightly bulk sends.

**Slice acceptance: COMPLETE (signed off 2026-06-12).** All S1–S5 pass; parent invoice email confirmed.

## Recording results

Record pass/fail per row + build SHA here and add the sign-off line to the AGENTS.md "P6 invoice issue/send policy delivered" entry. **Prod activation** is a deliberate step: set `BILLING_AUTOSEND_ENABLED=true` only after S1–S5 pass.

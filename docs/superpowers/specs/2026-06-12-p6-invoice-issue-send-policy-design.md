# P6 follow-up — Invoice issue/send policy (scheduled per-installment send)

*Design spec. Status: approved for planning. Date: 2026-06-12.*

## 1. Problem

The Invoice Ninja (IN) push creates invoices but never issues or sends them. `create_invoice`
(`apps/integrations/invoice_ninja.py`) POSTs to `/invoices` with **no `status_id`**, so every
invoice lands as **Draft** (status 1): invisible to the guardian, no email, not counted in their
balance. For the parent to ever see or pay an invoice, a human must open Invoice Ninja and send it
by hand. That dangling manual step is the gap (milestone: "Invoice issue/send policy — Draft vs
auto-issue").

### Why "auto-issue on push" is wrong here

Billing is **installment-based**. A `BillingRecord` materializes into many `BillingInvoice` rows
(`materialize_installments` → `derive_installment_schedule`), each with its own `due_date` spread
across future months (default due day 20th; skips July + December). The push creates **all** of
them at once. So "issue + email everything on push" would email a parent their entire season of
invoices in a single burst (e.g. 9 emails the day staff push). The send must be **per installment,
near its own due date** — not all upfront.

## 2. Approach (chosen)

**Separate create from send.** Keep the push behavior (create all installments as Draft). Add a
**nightly job** that issues + emails each invoice when it comes due, driven by the same proven
`django-q` daily-schedule pattern already used for payment read-back (`billing/0005`).

- **Create** — unchanged: staff confirm a `BillingRecord`, push creates all installment invoices in
  IN as Draft.
- **Issue + send** — a nightly sweep emails each Draft invoice on/after the **1st of its own due
  month**. Emailing a Draft in IN transitions it to **Sent** (status 2) and delivers IN's templated
  invoice email (PDF + payment link). One email per installment, ~19 days before the 20th-of-month
  due date.

Rejected alternatives:
- *Issue + email all on push* — produces the burst described above. Not chosen.
- *Issue all now (mark Sent), email none* — parent gets no payment notification; defeats the point
  of automating the send. Not chosen.
- *Stay Draft + a separate in-app "send" action* — still a manual per-installment step every month
  for staff; the schedule automates exactly that. Not chosen (but staff retain IN's own UI for
  ad-hoc sends — see §8).

## 3. Send rule (eligibility predicate)

A `BillingInvoice` is eligible to be sent on a given run when **all** hold:

1. `external_invoice_id` is set (it exists in IN), and
2. `external_status == "created"` (still Draft, not yet sent), and
3. `today >= due_date.replace(day=1)` (on/after the first day of its due month), and
4. the guardian has a non-empty email (`record.member.guardian.email`).

Rationale for predicate #3: sending from the 1st of the due month gives the parent the whole month
until the 20th. Using `>=` (not `==`) means the rule also covers:
- a **mid-season signup** whose first installment is due in the current month (already past the 1st),
- **catch-up** for anything overdue (e.g. autosend was off for a month, then enabled).

Only the current (and any overdue) installment is eligible on any given run; future installments'
`due_date.replace(day=1)` is still in the future, so no burst. The "1st of due month" policy lives
in **one small pure function** (e.g. `is_invoice_due_to_send(invoice, today)`); changing the lead
later is a one-line edit (YAGNI on making it configurable).

## 4. Invoice Ninja mechanism

Issue + email is a single call per invoice:

```
POST /api/v1/invoices/bulk
{"action": "email", "ids": ["<external_invoice_id>"]}
```

Emailing a Draft in IN both **marks it Sent** (status 2) and **sends the templated email** (PDF +
payment link). The email content/branding is configured **inside Invoice Ninja**, not this app —
the app only triggers the send. Done **per invoice** (one bulk call with a single id) so each row's
success/failure is tracked independently.

A thin client function `email_invoice(external_invoice_id)` is added to
`apps/integrations/invoice_ninja.py` (and surfaced through `invoice_platform.py`, mirroring the
existing `create_invoice` / `fetch_invoice_payment` seam so tests can stub the platform). It raises
the same typed errors the other IN calls raise (so `_classify_invoice_error` handles them).

Sources: Invoice Ninja v5 bulk email action
(https://forum.invoiceninja.com/t/email-invoice-via-api/9988),
API reference (https://api-docs.invoicing.co/).

## 5. State model

`BillingInvoice.external_status` lifecycle gains a terminal **`"sent"`**:

```
""  --push-->  "created"  --nightly send-->  "sent"
                   |                              ^
                   +--------- failed send --------+  (error code recorded; retried next run)
```

- Add `BillingInvoice.sent_at = DateTimeField(null=True, blank=True)` — set when the email succeeds.
- `external_status` values: `""` (not pushed), `"created"` (Draft in IN), `"sent"` (issued+emailed),
  and the pre-existing `"failed"` set by the **push/create** path when invoice creation errors. A
  failed **send** does NOT use `"failed"`: the row stays `"created"` (still Draft, never emailed) and
  records the error in `external_error_code`, so the eligibility predicate re-selects it on the next
  run. This keeps the nightly cadence as the retry loop and avoids a terminal state that would
  silently strand an unsent invoice.
- Schema-only migration: add `sent_at`.

Payment read-back (`sync_billing_payments`) is unaffected — it already keys off
`external_invoice_id` and works for sent invoices; Draft invoices have no payments, so syncing them
is a harmless no-op.

## 6. The nightly job

New task `send_due_invoices()` in `apps/integrations/tasks.py`:

- Selects eligible `BillingInvoice` rows (§3) whose parent record is confirmed/pushed.
- For each, calls `invoice_platform.email_invoice(external_invoice_id)`; on success sets
  `external_status="sent"`, `sent_at=now`, clears `external_error_code`; on failure records the
  classified error and leaves the row `"created"` for the next run.
- Idempotent and safe to re-run: already-`"sent"` rows are not re-selected.

Registered as a **DAILY `django-q` `Schedule`** via a new migration mirroring
`apps/billing/migrations/0005_billing_payment_sync_schedule.py` (separate schedule from payment sync;
single responsibility). Runs in the existing `qcluster` worker.

## 7. Safety switch

A settings/env flag **`BILLING_AUTOSEND_ENABLED`** (bool, default **`False`**). When false,
`send_due_invoices()` returns immediately (no selection, no sends). This lets us deploy the full
machinery, verify the create→send path against a single real parent in IN, then flip the flag on in
prod. Rationale: this is the step that starts emailing real parents payment requests, so enabling it
is a deliberate operational action, not an implicit consequence of deploying.

## 8. Escape hatch / manual control

No new in-app "send now" action in this scope. Staff retain Invoice Ninja's own UI to send or
inspect any individual invoice ad-hoc (e.g. send one early, or re-send). The existing admin push
action (create-as-Draft) is unchanged. An in-app per-invoice "send now" admin action can be added
later if real usage shows a need (explicitly deferred).

## 9. Error handling

- Reuse `_classify_invoice_error` + the retryable/non-retryable classification already used by
  `push_billing_record`. Retryable errors (timeouts, rate limits, provider-unavailable) surface so
  the row is retried on the next nightly run; the nightly cadence is itself the retry loop.
- A failed send records `external_error_code` on the `BillingInvoice` (visible in admin), leaving it
  `"created"`.
- A guardian with no email is **skipped and logged**, not marked failed (it's a data gap to fix, not
  a transient error).
- The job processes rows independently — one bad row never blocks the rest.

## 10. Out of scope

- IN recurring invoices / native auto-billing (the installment schedule is owned by this app).
- Payment reminders / dunning (IN can do its own reminders if configured).
- In-app "send now" admin action (deferred, §8).
- Changing the create-at-push behavior or the discount/installment math.

## 11. Testing

- **Send predicate** (`is_invoice_due_to_send`): last day of prior month → not eligible; 1st of due
  month → eligible; mid-month current-month signup → eligible; already `"sent"` → skip; no guardian
  email → skip.
- **`send_due_invoices` service**: emails only eligible rows; transitions `"created"`→`"sent"` +
  stamps `sent_at`; idempotent re-run sends nothing new; a failing `email_invoice` records the error
  and leaves the row `"created"`; a no-email guardian is skipped, not failed.
- **Autosend flag**: with `BILLING_AUTOSEND_ENABLED=False`, the job is a no-op even when eligible
  rows exist.
- **IN client** (`email_invoice`): issues `POST /invoices/bulk` with `{"action":"email","ids":[id]}`;
  maps error responses to typed errors.
- **Schedule migration**: the DAILY `Schedule` row is created (and removed on reverse).
- **LAN / sandbox acceptance**: with the flag on, a real test parent receives exactly one email for
  the due installment, the IN invoice flips Draft→Sent, future installments are untouched, and a
  second nightly run sends nothing new.

## 12. Acceptance

1. Push still creates all installments as Draft (unchanged).
2. With `BILLING_AUTOSEND_ENABLED` on, the nightly job emails each installment on/after the 1st of
   its due month; emailing flips the IN invoice to Sent and the parent receives IN's invoice email.
3. Future installments are not emailed early; a mid-season first installment and any overdue rows are
   picked up.
4. The job is idempotent (no double-send) and records per-row errors without blocking other rows.
5. A guardian without an email is skipped and logged.
6. With the flag off, nothing is sent.
7. Full suite, ruff, and mypy green; LAN/sandbox verification of the create→send path.

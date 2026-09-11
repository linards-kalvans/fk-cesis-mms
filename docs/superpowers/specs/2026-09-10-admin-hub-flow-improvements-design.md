# Admin Hub: Direct Agreement Handoff and One-Click Invoice Push — Design Specification

> **Date:** 2026-09-10
> **Status:** Design review
> **Scope:** Admin Hub approval and billing UI, plus a narrowly scoped existing Django-admin push endpoint extension.

---

## 1. Problem

The Admin Hub makes staff take two unnecessary steps:

1. After application approval, the cockpit remains open and only offers a separate **Turpināt: Līgums** action.
2. A new draft `BillingRecord` requires **Apstiprināt ierakstu** before staff can use **Izrakstīt rēķinus**. The billing page also provides no invoice preview before the external push.

Staff should continue straight to the agreement workflow after approval, inspect the prospective installments, then make one deliberate action that confirms the local billing record and queues its Invoice Ninja push.

## 2. Scope

### In scope

1. Successful Hub approval redirects to `/hub/pieteikumi/<application-pk>/ligums/`.
2. A draft billing record shows a derived invoice preview before the first push.
3. Preview rows show installment sequence, due date, amount, and a visible `Priekšskatījums` status.
4. Preview includes explicit Latvian copy that rows are not actual invoices yet.
5. Hub's `Izrakstīt rēķinus` action confirms a draft record and queues the existing Invoice Ninja push in one POST.
6. Existing direct Django-admin push behavior remains confirmed-only unless the explicit Hub one-click flag is present.
7. Existing staff access control, POST-only handling, CSRF protection, audit events, safe redirects, and idempotent already-synced behavior remain intact.

### Out of scope

- Invoice Ninja API/provider/task changes.
- New models, fields, migrations, persisted preview rows, or JavaScript.
- Parent-facing pages, Family Hub, agreement workflow, or plan setup changes.
- Changes to direct Django-admin draft-push behavior without the explicit Hub flag.

## 3. Design

### 3.1 Direct handoff after approval

`cockpit.html` will submit both query and form `next` values as the existing Hub agreement URL. The approval endpoint already validates safe local `next` destinations, creates the member and agreement, then redirects. It needs no service change.

This removes the post-approval dead-end while preserving direct Django-admin behavior when no Hub `next` is supplied.

### 3.2 Derived invoice preview

`billing_view` will derive a schedule only when a current `BillingRecord` exists and its persisted invoice list is empty. It will call existing `derive_installment_schedule(record.plan, record.final_amount, first_billing_month=record.first_billing_month)`.

The billing template renders this derived schedule as a clearly separate preview table. Every row has sequence, due date, amount, and a neutral `Priekšskatījums` badge. A nearby hint says invoices are not yet created in Invoice Ninja. The existing persisted-invoice table remains authoritative once invoice rows exist; no preview renders alongside it.

This boundary prevents UI rendering from creating records or talking to Invoice Ninja. It also avoids incorrectly calling persistent, worker-created `BillingInvoice` rows a preview.

### 3.3 One-click confirm and push

The existing Django-admin billing push endpoint gains one explicit POST flag: `confirm_and_push`.

```text
Hub button POST
  └─ confirm_and_push=1
       ├─ draft record: confirm record, record confirmation audit event
       ├─ confirmed record: retain current state
       ├─ synced record: retain current no-op behavior
       ├─ enqueue existing Invoice Ninja push
       └─ record existing push audit event and redirect safely
```

For an ordinary direct request without this flag, a draft record remains refused exactly as today. Thus the admin action keeps its confirmation safeguard, while the Hub deliberately combines confirmation and push in one staff-authenticated, CSRF-protected POST.

The confirmation mutation and its audit event happen before enqueueing. This guarantees any queued worker sees a confirmed record. The work is local database state plus an asynchronous enqueue; it does not call Invoice Ninja during request handling.

## 4. Components

| Component | Change | Reason |
|---|---|---|
| `templates/admin_hub/cockpit.html` | Submit approval with agreement URL as `next` | Remove redundant intermediate screen. |
| `apps/admin_hub/views.py::billing_view` | Provide derived preview schedule | Render only persisted billing intent; no writes. |
| `templates/admin_hub/billing.html` | Render preview and one push button | Make pending invoices understandable and action singular. |
| `apps/billing/admin.py::BillingRecordAdmin` push route | Interpret explicit `confirm_and_push` flag | Reuse existing controlled mutation boundary; preserve direct-admin default guard. |
| `tests/admin_hub/*`, billing-admin tests | Cover redirects, preview, combined action, and regressions | Prove requested flow and safety contract. |

## 5. Error and State Rules

| Record state | `confirm_and_push=1` | Normal push request |
|---|---|---|
| Draft | Confirm, audit confirmation, enqueue | Refuse; no enqueue/audit push |
| Confirmed, unsynced | Enqueue | Enqueue |
| Confirmed, synced | Existing no-op | Existing no-op |

- GET requests remain refused.
- Unauthorized staff and CSRF-invalid requests remain refused by existing protections.
- Invalid `next` values remain ignored by existing safe-redirect logic.
- A failed enqueue must not falsely claim an Invoice Ninja invoice exists; normal error handling applies.

## 6. Acceptance Criteria

1. Approving submitted application from Hub redirects to its agreement page, not cockpit.
2. Draft record with no persisted invoices displays preview with sequence, due date, amount, `Priekšskatījums`, and clear non-invoice copy.
3. Preview is absent when persisted invoice rows exist.
4. Hub has one invoice action for a draft record: `Izrakstīt rēķinus`.
5. Clicking it confirms record, creates required confirmation/push audit events, queues one push, and returns safely to billing page.
6. Direct draft push without flag still does not confirm, enqueue, or create push audit event.
7. Existing staff, POST-only, CSRF, safe redirect, and synced-record no-op coverage passes.

## 7. Verification

1. Targeted Hub and billing-admin pytest files pass.
2. `uv run pytest -q -m "not slow"` passes.
3. `uv run ruff check .`, `uv run mypy .`, and `uv run python manage.py makemigrations --check` pass.
4. LAN smoke: approve application → agreement page; sign → preview appears; one click queues invoice push; after worker processing, real invoice list replaces preview.

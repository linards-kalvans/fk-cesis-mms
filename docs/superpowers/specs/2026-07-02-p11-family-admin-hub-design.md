# P11 — Family admin action hub

*Design spec. Status: approved for planning. Date: 2026-07-02.*

## 1. Problem

Today, processing one family end-to-end requires staff to jump across many Django admin pages:
Guardian change page, RegistrationApplication change page (review), Agreement change page,
Member change page, BillingRecord change page, BillingInvoice inline. Each page has its own
context, its own action controls, and its own status display. For a routine workflow — review
an application, approve, send agreement, mark signed, confirm billing, push invoices — staff
opens five or more admin pages and re-derives the family context on each one.

This is slow, error-prone, and makes statuses hard to read at a glance. Staff cannot answer
"what does this family need right now?" without opening multiple tabs.

## 2. Goals

- One page per family (Guardian) that shows the full current state across all lanes:
  applications, agreements, membership, billing/invoices.
- Staff can complete the most common workflow actions from that single page without navigating
  to deep admin change pages, including choosing the agreement billing plan before signing.
- Statuses are translated from raw model states into clear icon + badge + next-action cues,
  so staff understand where each lane stands in under ~30 seconds.
- The action queue (what needs attention across all families) is the primary entry point;
  the per-family hub is the drill-down. The Guardian/parent changelist also shows the next
  missing action and sorts action-needed families first by default.
- The hub and the family/admin member controls expose kit-size as a single canonical value
  (`Formas izmērs`). The legacy `Šortu izmērs` field is hidden in hub surfaces and never
  rendered here — the shirt field is the only kit-size staff value.
- No new business logic in the first slice. Every action reuses an existing service path.

## 3. Non-goals (first milestone)

- No new business rules, no new model states, no new service methods.
- No inline editing of parent/member/application fields (deep edits stay on existing admin
  change pages).
- No parent-facing invoice visibility (that is P12).
- No custom invoice creation (that is P14).
- No coach portal, attendance, calendar, or WhatsApp (that is P15 / P16).
- No SPA or API rewrite. The hub is a server-rendered page inside the Django admin shell.

## 4. Proposed UX

### 4.1 Entry point: action-needed queue

A new admin page (registered in the Django admin shell, custom URL via `get_urls()`) shows
a queue of families that need staff attention. Each row is one Guardian/family with:

- Guardian name + contact summary.
- Count of children/members.
- A compact row of lane indicators (application / agreement / membership / billing), each
  rendered as a small icon + colour badge showing the current state and the next action
  needed (e.g. application "Iesniegts → apstiprināt", agreement "Sagatavots → nosūtīt",
  billing "Apstiprināts → izrakstīt").
- Clicking a row opens the family hub for that Guardian.

The queue is ordered by urgency: families with action-needed lanes first, then by most
recent activity.

### 4.2 Family hub page

The hub page is the single-family view. Layout:

1. **Header:** Guardian name, contact (email, phone), linked ParentAccount status, total
   children count.
2. **Action bar:** the same lane indicators as the queue row, but expanded — each lane
   shows its full status line and the primary action button for that lane.
3. **Children section:** one card per child (Member), each card showing:
   - Member name, personal ID (masked), training group, membership status.
   - Per-child sub-lanes: application (if pending), agreement, billing.
4. **Billing block ("Norēķini un rēķini"):** grouped by child + season/plan. Each group
   is a card with:
   - Header: total amount, confirmed/synced state, paid/unpaid summary, error badge if any.
   - Expandable rows: one per installment/invoice — due date, amount, sent state, payment
     state, error/action buttons.
   - `BillingRecord` and `BillingInvoice` are shown as one unified staff-facing block. The
     model split is hidden unless staff opens the deep admin change pages.
5. **Agreement section:** current agreement state, lifecycle history, action buttons.
6. **Deep-edit links:** "Atvērt detalizēti" links to the existing admin change pages for
   each object (Guardian, Member, Application, Agreement, BillingRecord).

### 4.3 Hybrid shell

The hub lives inside the Django admin shell — it uses the admin base template, admin nav,
admin auth, admin CSRF. Custom CSS and JS are allowed for the hub-specific layout and
interactions (expandable rows, action confirmations), but the admin shell is retained.

## 5. Lanes and status model

Four lanes, each mapping raw model states to a small set of staff-facing statuses:

### 5.1 Application lane

| Raw state | Staff status | Next action |
|---|---|---|
| `draft` | (not shown in queue) | — |
| `submitted` | Iesniegts | Apstiprināt / Pieprasīt labojumu / Noraidīt |
| `fix_requested` | Gaida labojumu | (parent action) |
| `approved` | Apstiprināts | (moves to agreement lane) |
| `rejected` | Noraidīts | (terminal) |

### 5.2 Agreement lane

| Raw state | Staff status | Next action |
|---|---|---|
| `generated` | Sagatavots | Atzīmēt kā nosūtītu |
| `sent` | Nosūtīts | Atzīmēt kā parakstītu |
| `signed` | Parakstīts | (moves to billing) |
| `void` | Atcelts | Sagatavot jaunu |
| `superseded` | Aizstāts | (see new current agreement) |
| `discontinued` | Pārtraukts | (terminal) |
| failed external state | Sinhronizācijas kļūda | Mēģināt vēlreiz / Pārbaudīt statusu |

### 5.3 Membership lane

| Raw state | Staff status | Next action |
|---|---|---|
| `active=True` | Aktīvs | — |
| `discontinued=True` | Pārtraukts (date) | (terminal) |

### 5.4 Billing / invoice lane

| Raw state | Staff status | Next action |
|---|---|---|
| BillingRecord `draft` | Melnraksts | Apstiprināt |
| BillingRecord `confirmed`, no external | Apstiprināts | Izrakstīt (Invoice Ninja) |
| BillingRecord `confirmed`, external `synced` | Sinhronizēts | Pārbaudīt maksājumus |
| BillingRecord `confirmed`, external `failed` | Kļūda | Mēģināt vēlreiz |
| BillingInvoice `created` (draft in IN) | Izveidots | (auto-send handles) |
| BillingInvoice `sent` | Nosūtīts | Gaida apmaksu |
| BillingInvoice `sent`, `paid` | Apmaksāts | — |
| BillingInvoice `sent`, `partial` | Daļēji apmaksāts | — |
| BillingInvoice error | Kļūda | Mēģināt vēlreiz / Pārbaudīt |

## 6. Supported hub actions (first milestone)

Every action reuses an existing service path. The hub is presentation/orchestration only.

### 6.1 Application actions
- Approve (with optional training-group assignment) — reuses `approve_application`.
- Request fix — reuses `request_fix`.
- Reject — reuses `reject_application`.

### 6.2 Agreement actions
- Mark as sent — reuses `mark_agreement_sent` (including DocuSeal enqueue for electronic).
- Mark as signed — reuses `mark_agreement_signed`.
- Retry failed submission — reuses existing `retry_docuseal` POST branch.
- Sync status — reuses existing `sync_docuseal` POST branch.
- Void — reuses `void_agreement`. **Separate lane from membership discontinuation.**
- Regenerate — reuses `regenerate_agreement`.
- Material amendment — reuses existing material amendment flow.

### 6.3 Membership actions
- Discontinue — reuses existing discontinuation flow (member + agreement + billing side
  effects). **Separate action from agreement void.**

### 6.4 Billing actions
- Confirm — reuses existing billing confirm path.
- Push to Invoice Ninja — reuses existing push action.
- Send due invoices — reuses existing send path (where applicable).
- Sync payments — reuses existing payment sync action.

### 6.5 What is NOT on the hub
- Editing parent/guardian fields (name, email, phone, address) — use Guardian admin page.
- Editing member fields (name, personal ID, training group) — use Member admin page.
- Editing application fields — use Application admin change page.
- Creating custom invoices — P12.
- Any action that does not already have a service path.

## 7. Agreement void vs membership discontinuation

These are explicitly separate lanes and separate actions:

- **Void agreement** (`void_agreement`): cancels the agreement artifact. The member is
  still active. Staff can regenerate a new agreement. Billing records are not affected.
  Use case: agreement was generated incorrectly, needs to be re-issued.

- **Discontinue membership** (P8 discontinuation flow): ends the member's participation.
  Marks the member as discontinued, marks the agreement as discontinued, handles billing
  side effects (credit notes for sent unpaid invoices). Use case: child is leaving the
  club.

The hub UI must make this distinction clear — different icons, different confirmation
copy, different sections. Void is in the agreement lane; discontinue is in the membership
lane.

## 8. Billing display: unified "Norēķini un rēķini" block

Staff perceives `BillingRecord` and `BillingInvoice` as one workflow. The hub shows them
as one block:

- Grouped by child (Member) + season/plan.
- Card header: total amount (from `BillingRecord.final_amount`), confirmed/synced state
  (from `BillingRecord.status` + `external_status`), paid/unpaid summary (rolled up from
  `BillingInvoice.payment_status`), error badge (from `BillingRecord.external_error_code`
  or `payment_error_code`).
- Expandable detail: one row per `BillingInvoice` — due date, amount, sent state
  (`external_status` + `sent_at`), payment state (`payment_status` + `paid_to_date` +
  `balance`), error/action buttons.

The model split is visible only when staff clicks "Atvērt detalizēti" to the deep admin
change pages.

## 9. Data sources and source of truth

The hub is read-only for status display. All data comes from existing models:

- Guardian / ParentAccount: `apps.members.models.Guardian` + `apps.accounts.models.ParentAccount`.
- Applications: `apps.registrations.models.RegistrationApplication` (filtered by
  `guardian__parent_account`).
- Members: `apps.members.models.Member` (filtered by `guardian`).
- Agreements: `apps.agreements.models.Agreement` (via `Member.agreements`).
- Billing: `apps.billing.models.BillingRecord` + `BillingInvoice` (via `Member`).

No new models. No new denormalization. The hub queries existing relations.

## 10. Permissions and audit

- The hub page requires staff auth (`@staff_member_required` or `admin_view`).
- Every action triggered from the hub goes through the existing service path, so audit
  events are already recorded (P7 audit baseline covers all the actions listed in §6).
- The hub page itself does not need new audit events — it is a read view.
- Action confirmations use the same CSRF and permission checks as the existing admin
  endpoints.

## 11. Acceptance criteria

P11 is complete when all of the following are true:

1. Staff can open one Guardian/family and see the full current state across application,
   agreement, membership, and billing lanes on one page.
2. Staff can complete the normal workflow (approve application → send agreement → choose
   billing plan/month → mark signed → confirm billing → push invoices) from the hub without
   navigating to deep admin change pages.
3. The action-needed queue shows all families with pending actions, ordered by urgency.
4. Statuses are rendered as icon + badge + next-action label, not raw model state strings.
   The Guardian changelist has a dedicated next-action column and orders action-needed
   families first by default.
5. Agreement void and membership discontinuation are clearly separate actions in separate
   lanes.
6. Billing is shown as one unified "Norēķini un rēķini" block grouped by child + season,
   with expandable invoice rows.
7. LAN acceptance proves staff can understand a family's status and complete the normal
   workflow in under ~30 seconds.
8. All hub actions reuse existing service paths — no new business logic.
9. Kit-size is shown in the hub as a single canonical `Formas izmērs` value (per child).
   The legacy shorts field, the label `Šortu izmērs`, and the column `member_kit_size_shorts`
   are never rendered on hub surfaces — only the shirt/canonical field is.
10. Tests cover:
    - queue ordering and filtering
    - hub page renders all lanes for a family
    - each hub action triggers the correct existing service
    - agreement void does not discontinue membership
    - membership discontinuation does not void agreement
    - billing block groups by child + season correctly
    - permission checks (staff-only)
    - kit-size admin display: hub shows `Formas izmērs` label and the canonical shirt value,
      and never shows `Šortu izmērs` or `member_kit_size_shorts` in rendered HTML

## 12. Tests and documentation scope

- New test file: `tests/admin_hub/test_action_queue.py` — queue ordering, filtering,
  urgency ranking.
- New test file: `tests/admin_hub/test_family_hub_page.py` — hub renders all lanes,
  status badges, action buttons.
- New test file: `tests/admin_hub/test_hub_actions.py` — each action triggers the
  correct service, permission checks, CSRF.
- New test file: `tests/admin_hub/test_billing_block.py` — grouping, expandable rows,
  error badges.
- Operator guide update: `docs/admin-hub.md` — how staff uses the hub, what each lane
  means, what actions are available, what requires deep admin pages. The guide must call
  out the kit-size rule: `Formas izmērs` is the only canonical value, shorts values are
  legacy and hidden in the hub.
- New test: kit-size admin display coverage under `tests/admin_hub/test_family_hub_page.py`
  (or its successor) — assert the rendered hub contains `Formas izmērs` and the selected
  shirt label, and does not contain `Šortu izmērs` or `member_kit_size_shorts`.
- No changes to parent-facing surfaces.
- No changes to existing admin change pages (they remain for deep edits).

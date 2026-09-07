# Admin Hub UI — design

**Date:** 2026-09-07
**Status:** design approved (mock-ups delivered), implementation not started
**Scope:** staff-facing UI for two workflows — registration application pipeline (8 steps) and outstanding-invoice review.

## Problem

Staff work happens today inside Django admin change pages plus the bespoke Family
Hub (`templates/admin/members/guardian/family_hub.html`). Both inherit admin
chrome: `<details>` disclosures stacked in `.module` fieldsets, no visual
hierarchy, and the eight-step application pipeline is invisible — a reviewer
cannot tell from any screen which step a member is on or what comes next.

The document-versus-field validation that opens every review is the worst case:
document thumbnails sit in one panel, the typed values in the standard admin
form above them, and comparing the two means scrolling.

## Decision

Build a **standalone FK Cēsis-branded staff UI ("Admin Hub")** whose forms POST
to the admin action endpoints that already exist. Django admin stays reachable as
the raw escape hatch.

### Rationale

| Option | Verdict |
|---|---|
| **A. Standalone views + own base template, POST to existing admin endpoints** | **Chosen.** Full control of page structure, so the split cockpit is possible. No new domain logic, no new state machine, no API layer. Django admin remains available unchanged for edge cases. |
| B. Restyle Django admin in place (CSS over `admin/base_site.html`) | Rejected. Admin's DOM (`fieldset.module`, changelist `<table>`) cannot express a two-pane cockpit or a step rail without JS that rewrites the page. Every Django upgrade would put the skin at risk. |
| C. SPA (HTMX/React) over a new JSON API | Rejected as unjustified. The pipeline is eight discrete POSTs and two list views, not a live-collaboration app. Cost: a serializer layer plus an auth story that does not exist today. |

### Rejected sub-decision: OCR comparison column

The first design draft put an "OCR value vs typed value" column in step 1 with
accept/keep affordances. **Rejected by the product owner:** the parent-facing
registration form already pre-fills from OCR, and the parent may legitimately
correct a wrong reading before submitting. A machine comparison would therefore
flag the parent's *corrections* as mismatches — noise, not signal.

Step 1 is instead a human side-by-side: document on the left, submitted values on
the right, with a per-field check-off list so the reviewer can track progress
through a long form. `field_sources` (already persisted on
`RegistrationApplication`) renders as a provenance badge per field — *no
dokumenta* / *vecāks labojis* / *ievadīts* — which tells the reviewer where to
look hardest without asserting a verdict.

## Screens

Mock-ups: `style-guide/admin/` (`index.html` is the launcher). Shared stylesheet
`style-guide/admin/hub.css`; tokens follow `style-guide/tokens.css`
(`--fk-blue: #0f0851`, `--fk-red: #ce1c20`, Anton display face) and reuse the
component language of `style-guide/fk_cesis_list.html`.

### S1 — Pieteikumu rinda (`01-pieteikumu-rinda.html`)

Default view: `status=submitted`, ordered `submitted_at DESC`. Tabs for
Jāizskata / Jālabo / Procesā / Pabeigti / Noraidīti / Visi.

Each row carries: child name + age, guardian, submitted-ago, document
completeness (three dots for guardian ID / member ID / portrait), an 8-segment
pipeline bar with `n/8` and a "next action" line, plus row actions. Left border
encodes urgency — green new, red aging (>3 days submitted), amber awaiting parent
fix, blue in-flight.

Stat strip above: to review, aging, awaiting signature, invoices to issue.

### S2 — Izskatīšanas kabīne, steps 1–2 (`02-kabine-parbaude.html`)

Split 46/54. **Left:** sticky document viewer — tab strip per document kind,
rotate ±90° (also `Shift+←/→`), zoom, fit, open in new tab, download, file
metadata line, and a collapsed tray listing replaced uploads. **Right:** field
readout grouped Bērns / Vecāks / Ekipējums un izvēles / Piekrišanas. Each row
shows label, value at 1.06rem, provenance badge, and a check-off button.

The check-off summary bar is **pinned to the top of the scrolling column**
(`position: sticky` below the header and step rail), so the count and the
"Apstiprināt visus" action stay reachable through a long field list.

**The checklist is never binding on approval.** It is a reviewer's working aid:
approval is enabled regardless of how many fields are ticked, step 2 shows no
"waiting on verification" state, and the card copy says so outright. Gating
approval on the ticks would only teach reviewers to click "Apstiprināt visus"
without reading.

**Fields the system has already verified start checked.** The guardian e-mail is
the case today: the one-time-code flow is what sets
`RegistrationApplication.parent_account`, so a non-null `parent_account_id` *is*
the proof the address is reachable — there is no separate boolean to read. The
row therefore renders pre-checked with a "Sistēma apstiprinājusi" badge instead
of a provenance badge, and asking a reviewer to eyeball it against a document
would be theatre. The tick stays clickable so a reviewer can deliberately clear
it if they have reason to.

Step 2 (approve) is a card at the foot of the right column: training-group
select, season, primary action. Reject and request-fix live in a "Riskantās
darbības" tray plus the sticky action bar.

**Kit size is one field, not two.** Commit `21945c4` ("Collapse shirt/short size
to single form size in reg form") reduced the parent form to a single
"Formas izmērs" choice bound to `member_kit_size_shirt`;
`apps/registrations/services.py` documents it as the canonical field and
`_require_valid_kit_sizes` validates only that id. `member_kit_size_shorts`
(`apps/registrations/models.py`) and `KitSizeOption.Kind.SHORTS` are now dead
weight — nothing writes them. The cockpit shows one row. Removing the dead
column and enum member is **out of scope here** but worth its own cleanup.

Rotation is client-side CSS transform only — no re-encoding, no write to the
stored document.

### S3 — Līgums, steps 3–5 (`03-ligums.html`)

Content column of three cards (prepare/send, download, upload signed) plus a
sticky sidecar: member card, agreement metadata, and a lifecycle timeline built
from `AgreementLifecycleEvent`. Void / amend / discontinue sit in a risky-actions
tray. "Atzīmēt kā parakstītu" is disabled until a signed artifact exists.

### S4 — Maksas plāns un rēķini, steps 6–8 (`04-plans-rekini.html`)

Step 6 renders the plan form (plan, first billing month, payment mode, due day,
discount switches) above a **computed installment schedule** — one row per
installment with due date and amount, skip months shown as dashed rows. Step 7
lists `BillingInvoice` rows with amounts, balances, Invoice Ninja status and
payment status. Step 8 is the next-season card, locked until its window opens.

### S5 — Neapmaksātie rēķini (`05-rekini-neapmaksatie.html`)

Stat strip (total balance, overdue count, unpaid count, received this month),
tabs including **Sinhronizācijas kļūdas** and **Nav izrakstīti**, filters for
season / group / due month / overdue age. Table rows carry an overdue pill with
day count; a selection bulk bar exposes sync and issue actions. Credit notes
(`BillingAdjustment`) render as an inset row under the invoice they correct.

Overdue reminder e-mails are **out of scope** (decided 2026-09-07): no such
action exists in the domain today and the design does not add one.

## Step-to-endpoint mapping

Every step drives an endpoint that exists today. No new domain logic.

| Step | UI | Existing endpoint / action |
|---|---|---|
| 1 Datu pārbaude | S2 cockpit | read-only; documents via `documents:admin-document-preview` / `-download` |
| 2 Apstiprināt | S2 approve card | `admin:registrations_registrationapplication_approve` |
| 3 Ģenerēt + atzīmēt nosūtītu | S3 card A | `review-action` → `mark_agreement_sent`, `regenerate_agreement`, `set_signing_path` |
| 4 Lejupielādēt | S3 card B | `admin:registrations_registrationapplication_docuseal_document` |
| 5 Augšupielādēt parakstīto, atzīmēt parakstītu | S3 card C | `…_signed_artifact_upload` (POST), `…_signed_artifact` (serve); `review-action` → `mark_agreement_signed` |
| 6 Maksas plāns | S4 step 6 | `review-action` → `set_billing_setup` |
| 7 Izrakstīt rēķinus | S4 step 7 | `BillingRecordAdmin.push_to_invoice_ninja`, `sync_payments`, `confirm_view` |
| 8 Nākamā sezona | S4 step 8 | `review-action` → `create_next_season_billing` |
| Request fix / reject / assign group | S2 bar + trays | `review-action` → `request_fix`, `reject`, `assign_training_group` |
| Outstanding invoices | S5 | `BillingRecordAdmin` list + actions, `BillingAdjustment` |

### Ordering note

The data model attaches the billing intent to `Agreement`
(`billing_plan`, `first_billing_month`) and materialises the `BillingRecord` on
the *signed* transition. The requested order (plan after signing) is supported,
but the plan can also be set from step 3 onward. The UI therefore makes step 6
**available from step 3 and required before step 5 completes**, pre-selecting the
default plan and derived month as `create_agreement_for_member` already does.

## New work this design implies

1. `apps/admin_hub/` — URLs under `/hub/`, `staff_member_required`, view
   functions that assemble the per-step context and render the new templates.
   No new models, no new state transitions.
2. Templates + `static/admin_hub/hub.css` ported from
   `style-guide/admin/hub.css`.
3. **Extract the lane derivation into its own module** (see decision below) and
   build the linear 8-step rail on top of it. Single source for S1's micro rail
   and S2–S4's full rail.
4. Installment-schedule preview for step 6 — read-only reuse of
   `derive_installment_schedule`.
5. Selection guard on bulk invoice actions — a confirm step above N selected
   records (see the batch-cap decision below).
6. Check-off persistence in `localStorage` (see decision below).

## Decisions on the three implementation questions (2026-09-07)

### Batch caps — sweeps capped separately, Hub gets a selection guard

Corrected understanding of the current code: the staff-triggered
`push_to_invoice_ninja` action is **already asynchronous per record** — it calls
`enqueue_push_billing_record` and returns, so there is no request-timeout risk
and no unbounded synchronous loop. It is staff-triggered, not recurring.

The genuinely uncapped **recurring** flows are the two nightly django-q2
schedules: `sync_billing_payments()` and `send_due_invoices()`
(`apps/integrations/tasks.py`), both iterating an unbounded queryset with
per-row error isolation. Those predate this design.

Decision: capping the nightly sweeps is **tracked as its own change with its own
spec** — it is backend work unrelated to the skin, and folding it in would
couple a UI delivery to a billing-automation change. The Admin Hub contributes
only:

- a confirm step when staff select more than N records for a bulk action, and
- a backlog indicator on S5 fed by the sweep's leftover count once the capped
  sweeps expose one.

The mock-up's "no more than 50 per run" copy on S4 describes the intended capped
behaviour, not what the code does today.

### Step state — extract a shared lanes module

`apps/members/family_hub.py` (842 lines) already derives this state as four
parallel lanes: `FamilyLaneStatus` (`key`, `label`, `badge`, `level`, `icon`,
`next_action`, `urgency`) produced by `application_lane`, `agreement_lane`,
`membership_lane` and `billing_lane`.

Decision: **extract that derivation into its own module** (e.g.
`apps/members/lanes.py`), leaving `family_hub.py` to assemble the hub and queue
pages, then express the linear 8-step rail as a projection over the same lane
functions. One source of truth, so `next_action` wording cannot drift between
the Family Hub and the Admin Hub — and a file that had grown to two jobs is
split. The extraction is a behaviour-preserving refactor pinned by the existing
`tests/admin_hub/` suite.

Rejected: a second independent derivation in `apps/admin_hub/pipeline.py` (two
sources of the same truth, guaranteed drift); a denormalized `current_step`
column (migration, backfill, and discipline required on every transition path,
for a list view that is not slow).

### Check-off persistence — `localStorage`, keyed per application

Decision: the reviewer's ticks persist in `localStorage` under a key derived
from the application id, so a reload or accidental navigation does not lose
progress. **Field keys and booleans only — never field values** — so no personal
data is written to browser storage. Every read and write is wrapped in
`try`/`catch`: a private window or blocked site data must render the page
correctly with no stored state.

Storage records an **explicit boolean per field, never an absence**. This
matters because of the default-checked rows: if an unticked field were stored by
deleting its key, clearing the tick on a default-checked row such as the e-mail
would silently revert on the next page load. Restore therefore reads
`stored === undefined ? row default : stored === true`.

Scope of that guarantee: per browser, per reviewer. It is a working aid, not an
audit trail — it is not shared between staff and is cleared with site data.
The auditable record stays what it is today: `reviewed_by` / `reviewed_at`
stamped on approval.

Rejected: a per-field database row with reviewer and timestamp — genuinely
auditable and shared across devices, but a model, a migration and write
endpoints for an audit trail nobody has asked for; and session-only state, which
loses every tick on a reload mid-comparison.

The mock-up `02-kabine-parbaude.html` implements the chosen behaviour, so the
storage contract is demonstrable before any Django code exists.

## Security and data-handling notes

- Documents stay behind the existing private-storage preview/download views;
  the viewer embeds those URLs and never a public path.
- Rotation and zoom are presentation-only; no stored file is modified.
- Personal data on screen (personal codes, addresses, phone numbers) is the
  reason this UI is staff-only — `staff_member_required` on every route, same
  export-permission split as `export_csv_with_sensitive`.
- All names, personal codes and amounts in the mock-ups are synthetic.

## Resolved questions

- **S1 default filter** — keep as mocked: `status=submitted`, newest first, with
  the other work reachable through the tabs. (2026-09-07)
- **Overdue reminder e-mails** — dropped from scope. (2026-09-07)
- **Batch caps** — nightly sweeps capped in a separate change; Hub adds only a
  bulk-selection guard. (2026-09-07)
- **Step-state derivation** — extract a shared lanes module from
  `family_hub.py`. (2026-09-07)
- **Check-off persistence** — `localStorage`, keyed per application, field keys
  only. (2026-09-07)
- **Check-off bar** — pinned to the top of the scrolling column; action renamed
  "Apstiprināt visus"; never a precondition for approving the application.
  (2026-09-07)
- **Kit size** — one canonical field (`member_kit_size_shirt`, "Formas izmērs"),
  matching commit `21945c4`. (2026-09-07)
- **Guardian e-mail** — pre-checked as system-verified (non-null
  `parent_account`), still clearable; storage keeps explicit booleans so that
  clearing persists. (2026-09-07)

## Open questions

None outstanding. The nightly-sweep batch cap is out of scope here and needs its
own spec before implementation.

# Family admin action hub — staff guide

*P11. Concise operator reference for the family action queue and the per-family hub.
Read this before triaging a family end-to-end.*

## Entry point

1. Open the Django admin: `/admin/`.
2. Under **Vecāki** (Guardians) the changelist shows families needing action first.
   The **Nākamā darbība** column names what is missing, and **Ģimenes centrs** opens
   the per-family hub.
3. Or jump straight to the global action queue at
   `/admin/members/guardian/family-hub/`. It lists every family that has at least one
   action-needed lane, ordered by urgency (most urgent first), then by parent name,
   then by Guardian pk.

The per-family hub lives at `/admin/members/guardian/<id>/family-hub/`. Each row of
the queue links there. The hub is one page with the full family state — applications,
agreements, membership, billing — and a button bar for the common workflow actions.

## Lane meanings

The hub shows four lanes per child, in this order:

1. **Pieteikumi** (application). State: draft, submitted, fix_requested, approved, rejected.
2. **Līgumi** (agreement). State: generated, sent, signed, void, superseded, discontinued,
   plus a DocuSeal `failed` overlay.
3. **Dalība** (membership). Whether the Member is active, has a training group, or is
   discontinued.
4. **Norēķini un rēķini** (billing). One card per `(child, season)`, with a
   `<details>` of one row per installment.

Each lane has a coloured badge (ok / pending / fail / muted) and a one-line next-action
label so you can scan the page top-to-bottom without opening deep admin pages.

## Normal workflow

Process the family in this order — each step lives on the hub:

1. **Pieteikumi → Apstiprināt** (submitted application). Pick a training group from the
   `<select>` in the disclosure, click *Apstiprināt*. The application moves to approved
   and a `Member` + `Agreement` are created.
2. **Līgumi → Atzīmēt nosūtītu** (generated agreement). Both signing paths enqueue a
   DocuSeal submission: electronic with `send_email=True` (DocuSeal sends the signing
   email to the parent) and paper with `send_email=False` (the club's own Latvian
   notification already informed the guardian). The agreement moves to `sent`.
3. **Līgumi → Saglabāt norēķinu plānu** (generated/sent agreement). If the agreement
   has no billing plan, choose **Norēķinu plāns** and optionally **Pirmais rēķina mēnesis**
   directly in the hub. The **Atzīmēt parakstītu** button appears only after this setup.
4. **Līgumi → Atzīmēt parakstītu** (sent agreement). When the parent signs, the hub
   transitions the agreement to `signed`. This is the trigger that creates the draft
   `BillingRecord` for the current season.
5. **Norēķini → Apstiprināt** (draft billing). The draft record becomes `confirmed` and
   is audited (`BILLING_RECORD_CONFIRMED`).
6. **Norēķini → Izrakstīt rēķinus** (confirmed billing). The hub enqueues the Invoice
   Ninja push job. Once pushed, the record flips to `external_status="synced"` and the
   invoices become visible inside the `<details>` block.
7. **Norēķini → Pārbaudīt maksājumus** (synced billing). The hub enqueues the payment
   read-back so Invoice Ninja payment events flow back into Django.

If DocuSeal fails on step 2, the lane shows the Latvian error tooltip plus two buttons:
*Mēģināt vēlreiz* (re-enqueues create) and *Pārbaudīt DocuSeal statusu* (enqueues sync).

When DocuSeal has created a submission (any state, any signing path), the Līgumi
lane lists every agreement for the child with a non-empty `external_id` and renders
the download link **Lejupielādēt ģenerēto līgumu** for each — current row plus
history (generated, sent, signed, void, superseded, discontinued). The link goes
through the staff-only proxy at
`/admin/members/guardian/<guardian_id>/family-hub/agreement/<agreement_id>/docuseal-document/`
with `?disposition=attachment`, which streams the generated PDF from DocuSeal
through Django (the DocuSeal URL itself is never rendered, bookmarkable, or
persisted to the database).

The paper signing path also gets a DocuSeal submission — `mark_agreement_sent`
always enqueues the create job, but with `send_email=False` so DocuSeal does not
send its own signing email to the parent (the club's own Latvian notification
already informed them). The paper path therefore appears in the same download list
once the submission completes. Voiding any agreement with a non-empty
`external_id` archives the DocuSeal submission regardless of signing path while
retaining the stored id, so historical download controls stay visible after void.

## Void agreement vs discontinue membership

These are **separate actions in separate lanes**. The hub UI mirrors that:

- **Atcelt līgumu** (void) — **Līgumi** lane. Cancels the agreement artifact only.
  The Member stays active, billing rows are not affected. Use it when an agreement was
  generated incorrectly and needs to be re-issued. A new agreement can be regenerated
  (Sagatavot jaunu līgumu) once voided.
- **Pārtraukt dalību** (discontinue) — **Dalība** lane. The action ends the **Member's**
  participation. Marks the Member as `discontinued`, marks the agreement as
  `discontinued`, runs the P8 billing side-effects (credit notes for sent unpaid
  invoices, local cancellation of unpushed/unsent invoices). Use it when a child is
  leaving the club. The disclosure lists each invoice row from the child's billing
  groups as an opt-in checkbox (`selected_invoices`).

Voiding does **not** discontinue. Discontinuing does **not** void separately — it ends
the agreement via its own transition.

## Norēķini un rēķini block

One block per `(child, season)` group:

- Header: child name, season, `final_amount` (with currency), status badge, error
  message in Latvian if any (`auth_failed`, `misconfigured`, `not_found`,
  `provider_error`, `unavailable`).
- Buttons: *Apstiprināt ierakstu* (draft only), *Izrakstīt rēķinus* (confirmed, not
  yet pushed), *Pārbaudīt maksājumus* (any time on a confirmed record).
- `<details>`: one row per `BillingInvoice` — sequence, due date (ISO), amount, IN
  status, payment status label. Failed invoices would surface here if the schedule
  job logged per-invoice errors.
- Deep link: *Atvērt detalizēti rēķinu ierakstu →* opens the BillingRecord change
  page in the admin shell.

The model split (`BillingRecord` vs `BillingInvoice`) is hidden inside the block.
Staff perceive one workflow. The model split is only visible on the deep admin pages.

## Formas izmērs (kit size)

The hub shows a single canonical kit-size value per child: **Formas izmērs**, read
from `application.member_kit_size_shirt.label` (or, once approved, from the source
application's shirt value — there is no separate member-level kit-size column).

The legacy `member_kit_size_shorts` column is **never rendered** in the hub. The
label `Šortu izmērs` is never rendered either. The shorts values remain in the
database for historical applications but are not exposed in the hub surface — the
shirt value is the only kit-size staff see or set in this flow.

If you need to change a kit size, edit the RegistrationApplication on its deep admin
change page (the child may not yet be a Member). The hub re-reads on the next request.

## Treniņu grupa (training group)

In **Dalība**, an active member without a training group shows an inline **Treniņu grupa**
dropdown and **Piešķirt grupu** button. The dropdown lists the active groups from
`TrainingGroup.objects.filter(is_active=True)`. POST goes through
`action=assign_training_group` and reuses the existing `assign_training_group` service
(plus the `TRAINING_GROUP_ASSIGNED` audit hook). To reassign or clear a group, use
the deep admin Member change page — the hub exposes only the empty-group case.

## What still needs deep admin pages

The hub is for triage and the routine workflow. Deep edits stay on the existing
admin change pages — open them via the **Atvērt detalizēti** links in the hub or the
queue list display:

- Guardian: parent/contact fields, email change, account active flag.
- Member: full name, personal ID, birth date, training group (via the registration
  review queue's training-group module).
- Registration application: full form fields, all review actions including training
  group assignment, document preview. The Līgums (agreement) module on the review
  page renders the same `Lejupielādēt ģenerēto līgumu` list as the Family hub for
  every agreement of the approved member with a non-empty `external_id`, served
  through the same shared proxy at
  `/admin/registrations/registrationapplication/<id>/agreement/<agreement_id>/docuseal-document/`.
  Cross-application agreement requests return 404 (the route enforces
  `member_id=application.approved_member_id`). The retired "Atvērt DocuSeal ↗"
  external link is gone — the document URL never leaves the server.
- Agreement: agreement number, lifecycle events, deep amendment history. The
  Agreement admin change page is view-only (`has_change_permission=False`,
  `has_view_permission` returns true for any signed-in staff). When the row has
  a non-empty `external_id`, the change page embeds the PDF in an iframe at
  `?disposition=inline` and renders the **Lejupielādēt ģenerēto līgumu** download
  anchor next to the iframe. The page never renders the DocuSeal document URL.
- BillingRecord: amount override + reason, plan reassignment, full invoice inline.

Anything the hub doesn't expose lives on the deep admin page. The two routes never
duplicate form fields — the hub is intentionally narrow.

## Permissions

The hub is staff-only (`@admin_view`, `has_change_permission`-gated). Cross-family
action attempts return `404` (not `403`) — the helpers filter by Guardian ownership
in the queryset. All actions reuse existing services, so the P7 audit trail
(`AuditEvent`) covers every mutation: `BILLING_RECORD_CONFIRMED`, `APPLICATION_APPROVED`,
`AGREEMENT_SENT`, `AGREEMENT_SIGNED`, `AGREEMENT_VOIDED`, `MEMBER_DISCONTINUED`, etc.

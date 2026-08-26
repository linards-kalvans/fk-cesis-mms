# FK Cēsis MMS Milestones

## 1. Purpose

This file is authoritative forward-looking milestone base for future development tasks.

Use it for:
- current implemented baseline
- open gaps
- milestone ordering
- acceptance criteria for future work
- future task planning

Do **not** use archived implementation plans for current planning unless user explicitly asks for historical context.

---

## 2. Current implemented baseline

### Foundation and platform
- Django project scaffold exists and boots
- `uv` workflow is in place
- `.env` autoload works for local commands and app startup
- acceptance-test baseline available on LAN at `http://192.168.3.245:8000`
- deployment runtime ownership is split: this repo owns app image build/tagging and local smoke; `https://github.com/linards-kalvans/fk-cesis` owns deployed runtime configuration and rollout docs.

### Accounts and parent access
- `ParentAccount` and `MagicLinkToken` exist
- magic-link issue / send / consume services exist
- request / verify / logout views exist
- current parent portal exists

### Registration workflow (P1 delivered)
- `/register/` is guardian email entry with one-time code verification
- `/register/verify/` completes verified parent access before continuation
- `/portal/` acts as chooser/dashboard for verified guardians
- `/applications/new/` starts a new verified registration with guardian-only prefill
- `/applications/<id>/` is the canonical parent application workspace
- Anonymous same-browser draft continuation removed; edit/submit require verified parent ownership
- Registration form uses one form with **save draft** and **submit application** actions
- Grouped form sections: guardian, child/player, documents
- `RegistrationApplication` workflow with `draft`, `submitted`, `fix_requested`, `approved`, `rejected`
- `fix_requested` save preserves status

### Documents and OCR
- `Document` model exists
- private storage root `PRIVATE_DOCUMENTS_ROOT` / `private-uploads/` exists
- admin-only protected preview/download endpoints exist
- anonymous users redirect to admin login
- authenticated non-admin users receive `404`
- real OCR integration delivered (P3): tiny-IDP provider behind stub/real adapter; synchronous extraction on guardian/member identity uploads; encrypted payload + summary in `DocumentExtraction`; classified error code persistence
- `OCR_PROVIDER_MODE` (`stub` / `tiny_idp`), `TINY_IDP_API_URL`, `TINY_IDP_API_KEY`, `OCR_ENCRYPTION_KEY` are the canonical config names
- live validation evidence committed at `docs/p3_tiny_idp_validation.md`

### Admin review and member creation
- admin review lives in Django admin (P7 Slice C-i, 2026-06-14): custom `change_form_template` renders document/OCR panels, agreement module, and training-group module above the native edit form, with flow actions in a top action bar
- review actions exist: request fix, reject, approve — all audited
- approval reuses canonical Guardian and creates Member idempotently (P6 Slice A, 2026-06-10)
- optional active `TrainingGroup` assignment at approval plus post-approval reassign/clear exists (P5 Slice B, 2026-05-28)

---

## 3. Open gaps and debt

- **Parent self-service email change with OTP** remains deferred — requires OTP re-verification of the new address.
- **Legal review/versioning of personal-data consent text** remains an operational prerequisite before any material text change.
- Roadmap / current validation status lives in §4.

---

## 4. Priority order for future development

### Current validation / operational list

Open items requiring attention:

1. **P5 DocuSeal generated-document proxy:** live DocuSeal validation pending.
2. **P10 analytics:** provider setup and dashboard smoke pending before production enablement.
3. **P11 family hub:** live DocuSeal validation pending; do not claim production sign-off.
4. **P15 calendar-year partial billing:** dev complete, LAN sign-off pending.
5. **P22 digest:** local PostgreSQL verification passed; GitHub CI rerun and LAN/email acceptance pending.
6. **M6:** production env / second-host, scheduled off-host backups, integration config docs, final security checklist.

---

### P16 — Signed-agreement upload + verification
**Status:** Blocked — eParaksts test credentials required.

**Why first**
- staff need a way to attach a signed agreement obtained through an alternative channel (e.g. in-person eParaksts signing) to the agreement record
- the DocuSeal-generated PDF is a separate artifact; staff-uploaded signed documents must be private, verifiable, and visible to staff + guardian

**Target outcome**
- staff-only upload of a signed PDF or `.edoc` file, attached to an Agreement
- private Agreement artifact; accessible through authorization-checked proxy views from admin detail, family hub, agreement detail, and verified guardian portal
- separated from the DocuSeal-generated document
- one current artifact per Agreement; replacement permanently deletes the prior file only after the new file succeeds
- redacted `AuditEvent` on upload/replace (no signer data, no file bytes, no validation results in metadata)
- best-effort background eParaksts validation via SignAPI (session-based OAuth); valid signer names, signing time, format, and status shown to admin + guardian; failure or unavailability does not block publication (guardian sees neutral "Status nav pieejams")
- external prerequisite: test credentials before implementation; production credentials + suitable security/data-processing terms before production sign-off
- provider links: https://developers.eparaksts.lv/v2.0/docs/before-you-start-1, https://developers.eparaksts.lv/docs/test-environment, https://developers.eparaksts.lv/v2.0/docs/validation-api
- out of scope: interactive in-portal eParaksts signing, raw provider URLs, reusing the registration `Document`/OCR model

### P17 — Configurable member export
**Status:** complete (2026-08-26).

**Why second**
- P7 Slice B static CSV exports are insufficient for recurring reports; staff need reusable templates with custom columns and filters

**Target outcome**
- shared saved staff-created export templates; all staff may include sensitive columns
- staff-only, audited; never export values/bytes in logs or audit metadata
- one Member row per export; selected member/guardian/current-agreement/training-group columns via stable allowlisted keys only
- agreement statuses: OR within each chosen set; selected training groups use OR within their group set; the two predicates use AND when both filters are configured; current agreement only; empty = unfiltered
- CSV/XLSX per run; XLSX default when available; CSV keeps UTF-8 BOM + semicolon + formula guard; direct download only
- P7 static CSV exports remain unchanged (additive)
- out of scope: guardian-row templates, scheduled email exports, arbitrary formula columns, arbitrary queries

**Delivered**
- Shared `MemberExportTemplate` admin templates: any active staff user can create, edit, delete, and run templates, including sensitive columns.
- One Member row per direct export; ordered member/guardian/current-agreement/training-group column keys come only from a server registry. Current-agreement state filters use OR, group filters use OR, and both predicates use AND.
- XLSX is the default direct in-memory attachment (`openpyxl`); CSV retains UTF-8 BOM + semicolon. Both formats apply the formula guard. No output storage, jobs, or provider calls.
- Template mutation/run audits use generic targets and redacted metadata; P7 static exports remain unchanged.
- Migrations: `core/0008`, `members/0012`. Verification: `2033 passed`, ruff clean, mypy clean (436 files; existing unchecked-function notes only), migration check clean; code review approved.
- Spec: `docs/superpowers/specs/2026-08-26-p17-configurable-member-export-design.md`. Plan: `docs/superpowers/plans/2026-08-26-p17-configurable-member-export.md`.

### P18 — Unfinished-application lifecycle
**Status:** Planned.

**Why third**
- draft and fix_requested applications sit indefinitely without reminders or archival

**Target outcome**
- automatic workflow for draft and fix_requested only: generic no-PII reminder emails at 7 and 21 inactive days, archive at 60 inactive days
- daily schedule at 09:00 Europe/Riga (django-q2 Schedule, admin-editable)
- follow-up anchor resets on parent save and request_fix
- at/in excess of 60 days: archive; no reminder sent in the same sweep
- reminder recipient: verified parent-account email when present, else `claimed_email`; blank both means skip reminder (no timestamp), leave eligible for later retry; archive timing unaffected; email goes to `/register/` with standard one-time-code gate
- new `archived` status; retain: anchor, reminder timestamps, archive time, prior state, archive actor (null for automated)
- auto-archived draft/fix_requested can resume (restores prior state, resets timer); manual staff archive for draft/submitted/fix/rejected; approved cannot be archived; manually archived submitted/rejected show read-only in portal, no resume
- audit reminder, archive, resume — no PII in audit metadata
- out of scope: deletion/purge, staff reminders, SMS/WhatsApp, automatic reminders for submitted/rejected, new auth links, automatic reopening

### P1 — Field-set finalization + guardian-email-first verified registration gate
**Status:** completed

**Delivered outcome**
- guardian, member, and application field sets are finalized in code and tests
- one-time email code verification gates registration continuation and portal access
- verified continuation replaced anonymous draft-start as primary registration path
- `/portal/` now acts as chooser/dashboard for verified guardians
- `/applications/new/` starts a new verified registration with guardian-only prefill
- same-browser anonymous draft edit/submit fallback removed

### P2 — Visual system + registration UX redesign
**Status:** complete

**Delivered outcome**
- unified visual system applied across parent-facing flow: guardian-email entry, chooser/dashboard, registration form, parent portal/registration list — all match style guide with canonical tokens, readable typography on desktop/mobile, FK Cēsis identity
- registration form: grouped guardian, child/player, and document sections with shared template primitives
- document-upload UX: guardian and member documents clearly separated; active uploaded document state visible; replace/refresh action understandable
- OCR-prefill review UX: extracted values distinguishable via source badges (`manual_only`, `derived_system_filled`, OCR markers); user can correct without confusion
- validation UX: readable field errors; top-level error summary with anchor links to invalid fields; invalid-submit error summary with heading and anchor target
- no workflow regression: verified entry, chooser, continue draft, start new, save draft, submit still work; no insecure ownership regression
- no schema changes, no business rule changes, no admin redesign

**Why second**
- should be built on final entry-flow model, not current temporary draft model
- improves parent-facing clarity after identity gate is decided

**Target outcome**
- parent flow matches style guide and approved visual direction

### P3 — OCR integration + secure extracted metadata
**Status:** complete — live validation evidence in `docs/p3_tiny_idp_validation.md` (2026-05-22)

**Provider decision (2026-05-15):**
- Provider: **tiny-IDP** (only provider)
- Open risks: no Latvian-specific accuracy data; tiny-IDP post-incident operational resilience unverified; pricing not publicly documented; legal review of DPA still needed

**Why third**
- depends on final field model and stable registration flow
- introduces real extraction and sensitive metadata handling

**Delivered code outcome**
- stub/real OCR provider boundary exists in `apps/integrations/ocr.py` with real tiny-IDP runtime
- identity uploads for `guardian_identity` and `member_identity` trigger synchronous OCR in draft flow
- `member_portrait` stays outside OCR scope
- OCR success persists encrypted payload and encrypted summary in `DocumentExtraction`
- `/applications/new/` reuses active guardian identity document by default and merges prior OCR extraction into parent prefill
- parent workspace shows OCR source markers and decrypted OCR summaries
- admin review detail shows separate guardian/member preview sections, decrypted OCR summaries, and confidence values when provider returns them
- non-blocking OCR failure path is covered in tests
- classified exception mapping: `_classify_exception()` in `safe_extract_document_data` maps typed OCR errors (`provider_misconfigured`, `auth_failed`, `rate_limited`, `request_timeout`, `provider_unavailable`, `invalid_response`) to `Document.ocr_error_code`; unknown exceptions fall back to `provider_unavailable`
- canonical config names: `OCR_PROVIDER_MODE` (`stub` / `tiny_idp`), `TINY_IDP_API_URL`, `TINY_IDP_API_KEY`, `OCR_ENCRYPTION_KEY`

**Verification evidence**
- full suite green: `638 passed`
- lint green: `uv run ruff check .`
- types green: `uv run mypy .`
- live validation harness: `scripts/validate_tiny_idp/`, evidence in `docs/p3_tiny_idp_validation.md`
- live run on 2026-05-22 against `api.tiny-idp.com` surfaced and fixed three integration bugs (auth header, multipart field, response shape) before sign-off

### P3.5 — Async OCR UX + background-job baseline
**Status:** complete (2026-05-23 — phase shipping 2026-05-22, post-merge fixes 2026-05-23)

**Why between P3 and P4**
- P3 delivered real OCR but kept it synchronous: the form blocks for ~4–10 s per upload (live runs showed 4182–9609 ms on tiny-IDP). That latency dominates parent-facing UX.
- M1 already flags background-job baseline as missing. Pulling it forward here unblocks future async work (agreement-state sync in P5, billing sync in P6).
- Belongs before P4 because the agreement-platform sync introduced in P4 should be built on the same job runner, not bolted on later.

**Target outcome**
- Documents upload immediately on file selection (before form submit), in background.
- OCR runs in background after upload completes; the form remains interactive throughout.
- Per-document progress states are visible: `uploading`, `uploaded`, `ocr_running`, `ocr_done`, `ocr_failed`.
- Empty/whitespace fields auto-fill from OCR when it completes; fields that already contain a value display an inline OCR suggestion the user can accept or dismiss.
- Background-job runner adopted: **django-q2** (DB-broker default, single-instance friendly). Worker process documented in `AGENTS.md` run instructions.
- No regression of P3 secure-storage posture: encrypted payload + summary still persisted; non-blocking failure path preserved.

### P4 — Parent-flow UX polish + mobile-first workspace
**Status:** complete (2026-05-25) — Slices A–E delivered. Six pre-existing parent-flow defects surfaced during Slice E LAN verification are tracked in the new P4.5 quality-debt sweep below.

**Why fourth**
- P3.5 deferred its visual polish (spinners, chip styling, source badges, visibility-aware polling, failure-message Latvianization); consolidating leftovers now closes that loop before any new workflow build
- parents are using the live LAN baseline now; compounding clarity on their flow before staff-workflow expansion yields faster ground-truth value
- the approval-to-agreement phase (now P5) reshapes staff workflow, not parent UX — a stable parent surface lets P5 build without re-touching the wizard
- multilingual architecture remains an explicit non-priority (Section 8); the i18n work in this phase is Latvian copy normalization, not translation infrastructure

**Target outcome**
- P3.5 leftover polish landed: calm branded spinner during `ocr_running` ("Apstrādājam dokumentu…"); one-shot "Dokumenta apstrāde pabeigta. Persona atpazīta kā <First Last>." confirmation on `ocr_done`; refined OCR suggestion chip styling and source-badge visual consistency; visibility-aware polling (pauses while tab hidden, resumes on focus); Latvianized failure messages for upload/OCR/validation errors
- Latvian copy normalized across all parent-facing templates, partials, and inline JS strings; zero English leakage on parent flows; admin surfaces unchanged
- name normalization from OCR: ALL CAPS → Latvian title-case applied at the OCR-result-processing layer before the decrypted prefill summary is consumed; handles hyphenated compound surnames and particles; encrypted payload at rest is unchanged
- step-gated wizard with inline validation and auto-save: "Turpināt" CTA on each step disabled until that step's required fields are valid; validation on blur for first-touch and on change for previously-invalid fields; inline error messages; draft auto-saves with ~500 ms debounce on field change, plus on blur and on step transition; subtle "Saglabāts" indicator; transient save failures retry silently; auto-save preserves `fix_requested` status; ownership posture unchanged
- personal data consent on the ID-documents step: required checkbox at the top of step 1; expandable inline T&C (default Latvian draft, pending legal review); "Turpināt" on step 1 disabled until checkbox ticked AND step-1 fields valid; `personal_data_consent_at` and `personal_data_consent_version` persist on `RegistrationApplication`; existing in-flight drafts re-consent on resume
- document/photo upload with camera capture: each upload slot exposes "Augšupielādēt failu" and "Uzņemt attēlu" (HTML `capture="environment"`); no custom `getUserMedia`; camera control hidden gracefully on unsupported devices; reuses P3.5 async upload + OCR enqueue path
- mobile-first registration workspace: `/applications/<id>/` wizard laid out narrow-viewport-first then enhanced for desktop; sticky primary CTA; progressive disclosure; ≥44 px touch targets
- entry + chooser + portal polished: `/register/`, `/register/verify/`, `/portal/`, parent registration list audited for mobile breakpoints, empty/error state clarity, visual cohesion with workspace
- cross-cutting UX primitives: shared empty-state and error-state partials; consistent spinner/toast/inline-error patterns
- minimal schema change scoped to consent: two new nullable fields on `RegistrationApplication` (`personal_data_consent_at`, `personal_data_consent_version`); no other model changes, no admin redesign, no new business rules

### P4.5 — Parent-flow quality-debt sweep
**Status:** complete (2026-05-25)

**Why interleaved**
- Each item is a real user-visible defect or UX gap surfaced during the Slice E manual LAN check on 192.168.3.245. They predate Slice E (earlier P3 / P3.5 / P4 Slice A–B), so they were correctly out of Slice E scope, but they should land before P5's approval-to-agreement work starts shaping staff workflow on top of the same parent surfaces.

**Target outcome**
- Member identity document + member portrait correctly reflect upload state on the workspace (not "not added" after a successful upload + OCR completion).
- New-registration prefill: member fields are not auto-filled from prior applications (only guardian fields carry over); guardian-field prefill does not double the value.
- OCR stub emits the canonical fields the live extractor produces, including `date_of_birth`, so the workspace's prefill path can populate member birth date.
- Mobile users can jump between wizard steps non-linearly (back-navigation already works; forward jump to a previously-visited step should also work).
- New-registration summary step shows "Iesniegt pieteikumu" as the primary action and drops the redundant "Saglabāt melnrakstu" button (autosave already persists the draft).
- On `edit` / `fix_requested` resumption, the step-gating logic recognises pre-filled valid values on initial load and enables "Turpināt →" without requiring a re-touch.

**Out of scope for P4.5**
- Anything that requires a model migration beyond what is needed for the OCR stub schema alignment.
- Translation infrastructure or admin redesigns.
- New OCR providers.

### P5 — Approval-to-agreement flow
**Status:** complete — all slices delivered and LAN-verified; signed off 2026-06-07
- Slice A delivered 2026-05-27 — admin review uses Django admin shell (`admin/base_site.html`), thumbnail grid per document kind opens a `<dialog>` lightbox on click, member portrait surfaced, active vs replaced docs distinguished via `<details>` history with per-doc `preview_kind`; OCR readout uses Latvian-labeled `<dl>` + translated confidence chips; approval-ready inspection grouped on one screen. Covers acceptance items 1 + 2 (item 4 was already implemented pre-Slice A via `approved_member_id` early-return). Includes Revision A (admin styling pivot away from fk-* branding + thumbnail/lightbox UX) and Slice A.1 (templated review-action emails with application/portal URL).
- Slice B delivered 2026-05-28 — training-group assignment inline on the review detail page (during approval via a bundled dropdown; post-approval via a Treniņu grupa module with reassign/clear). New `assign_training_group` service. Approve email enriched with the assigned group name when assignment happens at approval time. Currently-assigned-but-inactive groups surface with a `(neaktīva)` marker so existing state is never hidden. No model changes. Item 3 closed.
- Slice C delivered 2026-05-29 — internal-only Agreement domain (new `apps/agreements/` app): `Agreement` model with `ForeignKey(Member)` + `is_current` flag and partial `UniqueConstraint` enforcing at most one current per member; state machine `generated → sent → signed` with `void` + regenerate-after-void; auto-created inside `approve_application` (now `@transaction.atomic`) honouring the application's `preferred_agreement_signing` (default `electronic`); admin Līgums module on the review-detail page with five POST transitions; parent portal + workspace render Latvian status copy via the `agreement_status_copy` helper; plain-text emails on `sent`, `signed`, and `void` (Slice D will suppress these for the electronic path); Django admin `VIEW ON SITE` link bridges from the read-only Agreement detail to the review-detail page; bidirectional sync invariant keeps `application.preferred_agreement_signing` and `agreement.signing_path` always-equal post-approval; backfill migration creates Agreements for approved Members from before Slice C. DocuSeal reservation fields (`external_*`) on the model stay empty until Slice D. Items 5, 7, 11 closed.
- Slice D delivered 2026-06-06 — DocuSeal self-hosted adapter + signed-state sync + manual signing tracking (items 6, 8, 9, 10). New `apps/integrations/agreement_platform.py` boundary (stub/docuseal dispatch on `AGREEMENT_PROVIDER_MODE`, exception taxonomy, frozen `SubmissionResult`) + concrete `apps/integrations/docuseal.py` provider (HTTP via `requests`, `X-Auth-Token`, status→exception mapping, HMAC-SHA256 webhook verify). django-q2 jobs create/sync/archive submissions with transient-retry vs terminal-fail classification (`external_state="failed"` + `external_error_code` → Latvian copy via `apps/agreements/messages.py`). Electronic path: optimistic `sent`, sent/signed guardian emails suppressed (DocuSeal notifies), enqueue create; empty guardian email degrades to paper; void enqueues archive. HMAC-verified `submission.completed` webhook (`integrations/docuseal/webhook/`, mounted before the registrations catch-all) drives `sent`/`generated` → `signed`; bad signature 403, all other cases ack 200. Līgums module surfaces the failed-state error + retry and a live-submission DocuSeal link + manual sync button. Migration `0003_agreement_external_error_code`. Closes P5.
- P5 Slice D follow-up (2026-08-24) — DocuSeal agreement document preview. Both signing paths now create a DocuSeal submission on `mark_agreement_sent` (electronic with `send_email=True` so DocuSeal sends the signing email, paper with `send_email=False` because the club email already informed the guardian); `void_agreement` archives any non-empty `external_id` regardless of signing path and retains the id so historical download controls stay visible. New `apps/agreements/document_proxy.py` exposes `build_agreement_document_response(agreement, *, disposition)` (valid dispositions: `inline`, `attachment`; everything else → `Http404`) which streams the PDF through Django — the DocuSeal document URL is never rendered, bookmarkable, or persisted. New `apps/integrations/agreement_platform.DocumentStream` + `stream_submission_document(external_id)` boundary; the real provider selects `application/pdf` first, falls back to the first available document, fetches the selected URL via the existing `_request(..., stream=True)`, and closes the upstream response in `finally`. Three staff surfaces share the proxy through named routes: Family hub (`admin:members_guardian_docuseal_document`), Registration admin (`admin:registrations_registrationapplication_docuseal_document`, with `member_id=application.approved_member_id` ownership guard), Agreement admin (view-only `has_view_permission` for staff, `change_form_template` embeds an iframe + download anchor, `has_change_permission` stays False). A shared `templates/admin/_agreement_list.html` partial renders the per-row state label + signing path + download link for any non-empty `external_id` agreement; Family hub prefetches `members__agreements` with a filtered `Prefetch` to avoid per-child N+1. No migrations; `uv run pytest -q` → 1956 passed; `uv run ruff check .` → clean; `uv run mypy .` → clean. Live DocuSeal validation pending — no claim of production sign-off in this status line.

**Why fifth**
- agreement is business basis for billing
- admin review quality should improve before agreement decisions
- simpler first slice avoids premature in-app e-sign orchestration

**Target outcome**
- inline admin document preview in approval flow
- training-group assignment workflow
- generate agreement after approval
- track agreement state from external agreement platform

### P6 — Billing / Invoice Ninja sync
**Why sixth**
- should follow agreement flow in business sequence

**Target outcome**
- membership plan rules
- sibling discount
- automatic billing trigger after agreement platform `completed` state
- Invoice Ninja sync and payment-status visibility

**Status:** complete — live Invoice Ninja push/read-back validation complete (2026-06-09, `in.mplytics.eu`). Acceptance items 7, 8, 9 addressed and 1, 2 verified by Slice C. All code complete + gates green (1115 passed). Live-IN end-to-end validation (push + read-back) confirmed: product + client created (client carries `custom_value1=guardian.pk`), 10 invoices created, idempotent re-push, dedup lookups verified, product-note pollution fixed, payment read-back (full/partial/unpaid) verified via `payments[].date` field.
- Slice A delivered 2026-06-07 — local-only billing domain (new `apps/billing/` app): `MembershipPlan` (staff-editable plan config, one active row by convention) + `BillingRecord` (one per `(member, season)`, money snapshotted at creation, draft/confirmed + upfront/installments choices, manual override). Pure sibling-discount engine (`compute_billing_amounts`) derives the discount from the guardian's children (earliest-created full price, rest discounted; opt-out reuses `support_club_instead_of_multi_child_discount`) plus an installment-schedule helper. `agreement_signed` signal emitted from `mark_agreement_signed`; billing connects a receiver in `BillingConfig.ready()` that auto-creates a DRAFT `BillingRecord` on signing (idempotent; no-ops without an active plan). `recompute_billing_record` + admin plan/record surfaces with a `Pārrēķināt no plāna` action. New `preferred_payment_mode` registration field (`Maksājuma veids`). `backfill_billing` management command for pre-existing signed agreements. No Invoice Ninja calls — that is Slice B. Gate after Slice A: 1053 passed, ruff + mypy clean. **Manual LAN smoke confirmed + signed off 2026-06-07** (7/7 acceptance items: plan activation, signing→draft trigger, billing admin surface, recompute action draft-update + confirmed-skip, idempotent `backfill_billing`, parent `Maksājuma veids` render+persist; sibling discount + opt-out via the green discount-engine unit suite). Plan: `docs/superpowers/plans/2026-06-07-p6-slice-a-billing-domain.md`.
- Slice B delivered 2026-06-08 — admin-confirmed Invoice Ninja push (push-only; payment read-back is Slice C). New `apps/integrations/invoice_platform.py` boundary (stub/`invoiceninja` dispatch on `INVOICE_PROVIDER_MODE`, exception taxonomy, frozen result dataclasses) + `apps/integrations/invoice_ninja.py` provider (HTTP via `requests`, `X-Api-Token`, status→exception map incl. 429→transient, duplicate-invoice-number idempotency recovery). Mapping: Guardian→IN Client, MembershipPlan→IN Product (mirrored, referenced by derived `product_key`), each child's `BillingRecord`→its own invoice stream (no sibling consolidation), upfront=1 invoice / installments=one IN invoice per `derive_installment_schedule()` row, net per line with the sibling discount as a Latvian note. New `BillingInvoice` model (one row per installment) + `external_*` sync fields on `Guardian`/`MembershipPlan`/`BillingRecord`. `push_billing_record` django-q2 job (ensure product → ensure client → materialize → create invoices → roll up; deterministic `{PREFIX}-{record}-{seq}` numbers for idempotency; transient-retry vs terminal-fail with Latvian error copy). `BillingRecordAdmin` "Izrakstīt rēķinus (Invoice Ninja)" confirmed-only action. Gate after Slice B: 1080 passed, ruff + mypy clean. **Manual LAN smoke confirmed + signed off 2026-06-08** (stub provider mode + django-q worker): confirm→push→`synced` with 10 `BillingInvoice` rows, verified IN payload (number/product_key/Latvian label), idempotent re-push, draft skipped, and a testing refinement so already-`synced` records are reported separately rather than re-counted as pushed. Live-IN end-to-end deferred until an instance is provisioned. Plan: `docs/superpowers/plans/2026-06-07-p6-slice-b-invoice-ninja-push.md`.
- Slice C delivered 2026-06-08 — payment read-back + nightly scheduled sync + sync health (acceptance items 7, 8, 9; verifies 1, 2). `invoice_platform.fetch_invoice_payment` + provider `GET /invoices/{id}` with IN `status_id`→`payment_status` mapping (+ amount-derived fallback) and latest-payment-date extraction; payment-projection fields on `BillingInvoice`/`BillingRecord` (migration `billing/0004`, new `PaymentStatus` choices). `sync_billing_payments` nightly batch sweep (per-row error isolation) + `sync_billing_record_payments` manual per-record sync (terminal-error surface / transient re-raise), rolled up by `roll_up_payment_status`. Nightly django-q2 `Schedule` via idempotent data migration `billing/0005` + configurable `BILLING_PAYMENT_SYNC_HOUR`. Read-back terminal errors land on a dedicated `BillingRecord.payment_error_code` (migration `billing/0006`), separate from the push-side `external_error_code`. Admin: confirmed-only "Pārbaudīt maksājumus (Invoice Ninja)" action, payment columns/filter, read-only `BillingInvoiceInline`. Folded in the deferred Slice-B dedup hardening (`ensure_product` by `product_key`, `ensure_client` by `custom_value1=guardian.pk`) and an honest `backfill_billing` count. Gate: 1114 passed, ruff + mypy clean (240 files). Fixed a pre-existing TZ gap (no `TIME_ZONE`/`USE_TZ` was set → Django default America/Chicago): now `TIME_ZONE="Europe/Riga"` + `USE_TZ=True`, so the nightly hour is interpreted in local time. **Live-validated against a real Invoice Ninja instance (2026-06-09):** push (product/client/invoice create + dedup + dup-number recovery) and read-back (paid/partial/date mapping) both confirmed end-to-end through the django-q worker. **Six stub-hidden bugs found + fixed live:** (1) missing `X-Requested-With`/`Accept` headers (IN returned 200+HTML on errors); (2) dup-number message text; (3) `?include=payments` for the payment date; (4) generic line note + invoice `public_notes` to stop product-note pollution; (5) client/product dedup trusting `rows[0]` from IN's ignored `?custom_value1=`/`?product_key=` filters → narrow with `?filter=` + exact-match client-side; (6) dedup reusing archived/soft-deleted rows → `?status=active` + skip `is_deleted`/`archived_at`. Test suite hardened to never hit live providers from `.env`. Gate: 1126 passed, ruff + mypy clean. **Follow-ups deferred:** invoices push as IN **Draft** (auto-issue vs. staff-send policy); guardian dedup-by-email (repeated registrations create separate guardians → separate clients + no sibling linkage). **Operational note:** wiping IN data requires clearing Django `external_*` ids; restart the `qcluster` worker after task-code changes (no hot-reload). Remaining P6 close-out: confirmation pass on the deployed cloud `:dev` artifact.
- Installment calendar + per-plan due day delivered 2026-06-09 (completes acceptance item 6) — `derive_installment_schedule` now skips configured break months (per-plan `skip_months`, default July + December) placing N real installments (Jan–Jun + Aug–Nov for a Jan start), each due on a per-plan `payment_due_day` (default 20, clamped to month length); migration `billing/0007`; go-forward only. Gate: 1123 passed. Plan: `docs/superpowers/plans/2026-06-09-p6-installment-calendar-due-day.md`. Design: `docs/superpowers/specs/2026-06-08-p6-slice-c-payment-readback-sync-health-design.md`.
- Guardian-identity Slice A delivered 2026-06-10 — canonical `Guardian` 1:1 with `ParentAccount`, resolved at initiation and reused at approval; sibling-discount linkage now holds for all go-forward registrations. Gate: 1133 passed, ruff + mypy clean. Plan: `docs/superpowers/plans/2026-06-09-p6-guardian-identity-slice-a.md`. Spec: `docs/superpowers/specs/2026-06-09-p6-canonical-guardian-identity-design.md`. **LAN-acceptance verified 2026-06-10** (live Invoice Ninja); scenarios A–E + H pass — see the AGENTS.md Slice A entry.
- Concurrent-push dedup fix delivered 2026-06-10 (found during the Slice A LAN acceptance, scenario F) — parallel `push_billing_record` workers for sibling records created **duplicate Invoice Ninja clients + products** via an unlocked check-then-create on the shared guardian/plan. Fixed with `select_for_update`-locked `_ensure_client_id` / `_ensure_product_id` helpers in `apps/integrations/tasks.py`; re-test confirmed one client + one product per parent. Gate: 1137 passed. (Latency follow-up: the outbound IN call runs while the row lock is held — fine at current scale, revisit under load.)
- Guardian-identity Slice B1 delivered 2026-06-10 — read-through propagation. 5 guardian-read accessors on `RegistrationApplication` (`guardian_name`, `guardian_pid`, `guardian_contact_phone`, `guardian_address`, `guardian_contact_email`); Guardian profile now populated at draft-save; templates, workspace `initial` dict, prefill, phone-sync, and review-notification read via the accessors; `approve_application` no longer copies the snapshot. Editing a guardian's profile now propagates to every application and agreement (agreements read `member.guardian.*` for free). The `guardian_*` columns remain (dual-written); column drop is Slice B2. Gate: 1146 passed, ruff + mypy clean. Plan: `docs/superpowers/plans/2026-06-10-p6-guardian-identity-slice-b1-read-through.md`.
- Guardian-identity Slice B2 delivered 2026-06-11 — drop guardian columns. The five `guardian_*` columns dropped from `RegistrationApplication` (migration `registrations/0010`); read accessors now read `Guardian`/`ParentAccount` only (no column fallback); read-through is fully landed (B1 + B2). Only Slice C remains (locked-profile UX + admin email change). Gate: 1149 passed, ruff + mypy clean.

### P7 — Admin operations / export / audit polish
**Why seventh**
- builds on earlier workflow completion
- improves day-to-day operations and controls

**Target outcome**
- CSV export
- search/filter polish
- audit completion
- document/admin UX polish

### P8 — Agreement lifecycle ✅ COMPLETE (2026-06-30)
**Why eighth**
- extends delivered approval-to-agreement flow beyond the initial generated/sent/signed/void states
- should happen before deeper billing renewal work because amendments and discontinuation can change billing obligations

**Target outcome**
- staff can amend an active agreement without losing the original history
- staff can discontinue membership/agreement cleanly with reason, date, audit trail, and parent-visible status
- agreement replacement/regeneration rules are explicit and safe around already-signed agreements
- downstream billing behaviour is defined for amendments, discontinuation, and replacements
- DocuSeal / manual-signing states remain understandable after lifecycle changes

### P9 — Billing plan lifecycle
**Status:** complete (2026-07-03) — `Agreement` owns explicit `billing_plan` + `first_billing_month`; `MembershipPlan.is_default` + `billing_start_cutoff_day` with single-default DB constraint and `default-is-active` validation; preselected default plan + derived first-billing-month at `create_agreement_for_member`; `mark_agreement_signed` refuses to mutate state without a billing plan; `set_billing_setup` admin action; selected-member `renew_member_billing` action; draft-only `reassign_draft_billing_record` action (blocks confirmed/sent invoices). Three new `AuditEvent` choices: `BILLING_PLAN_ASSIGNED`, `BILLING_RECORD_RENEWED`, `BILLING_RECORD_REASSIGNED`. Spec/plan: `docs/superpowers/{specs,plans}/2026-07-02-p9-billing-plan-lifecycle*`. Gate: 1565 passed, ruff + mypy clean, no migrations.

**Why ninth**
- extends delivered billing instead of changing the signed-agreement trigger ad hoc
- removes the current "latest active plan wins" ambiguity before renewals matter
- builds on agreement-lifecycle rules for amendments and discontinuation

**Target outcome**
- explicit billing-plan assignment for new agreements
- staff can choose or override the plan before billing-record creation
- existing members can be renewed into a next-season plan
- draft billing records can be reassigned safely
- confirmed/synced invoices are never silently mutated; changes use explicit renewal or adjustment flow

### P10 — Public-site analytics + registration funnel
**Status:** Dev complete — provider/dashboard smoke pending before production enablement.

**Why tenth**
- public launch needs basic evidence about what visitors use before more admin-only workflow polish
- registration funnel visibility helps diagnose drop-off without reading logs or guessing from support messages
- parent portal ops signals help catch confusing empty/error states without tracking sensitive staff/admin work

**Delivered outcome**
- Platform comparison selected Plausible-first (`stub` + `plausible` provider modes), with Umami as fallback and Matomo/PostHog rejected as too heavy/broad for P10.
- Browser analytics and server analytics are independently flag-gated (`ANALYTICS_BROWSER_ENABLED`, `ANALYTICS_SERVER_ENABLED`) and disabled by default.
- Parent-only browser instrumentation emits fixed page/CTA/empty/error/validation hooks; admin pages never render analytics scripts.
- Server milestones emit `registration_start`, `email_verified`, and `application_submitted` without blocking user flow on provider failure.
- Referral attribution supports `/register/?ref=coach-a`, sanitizes to `[a-z0-9_-]` (max 64), consumes the session after first application creation, persists `RegistrationApplication.referral_code`, and sends only the safe `referral_code` property.
- Payloads are allowlist-only and exclude names, emails, phone numbers, personal IDs, document metadata/filenames, free-text form values, and model PKs.
- GDPR/privacy posture and production enablement checklist are documented in `docs/analytics.md`; live provider/dashboard smoke remains required before enabling in production.

### P11 — Family admin action hub
**Status:** dev complete (2026-07-09, extended 2026-08-24) — family action queue + Guardian family hub delivered inside Django admin. Staff can review family lanes, approve/request-fix/reject applications, send/sign/retry/sync/void/regenerate agreements, start minor/material amendments, discontinue memberships with invoice selection, confirm/push/sync billing, and inspect the unified `Norēķini un rēķini` block with invoice rows. Statuses render as icon + badge + next-action labels. Agreement billing-plan setup is available before signing, the Guardian changelist shows a next-action column and sorts action-needed families first, the Līgumi lane lists every agreement with a non-empty `external_id` (current + history, paper + electronic) and renders the **Lejupielādēt ģenerēto līgumu** download link through the staff-only Family hub proxy, missing training groups can be assigned inline from **Dalība**, and kit size appears as one canonical **Formas izmērs** value; legacy shorts values stay hidden here. DocuSeal document URLs are never rendered, bookmarkable, or persisted to the database — the proxy fetches each PDF server-side from `stream_submission_document` and yields it through Django. The same shared partial and proxy drive the Registration admin Līgums module and the Agreement admin read-only change page (inline iframe + download anchor). Verification: `uv run pytest -q` → 1956 passed; `uv run ruff check .` → clean; `uv run mypy .` → clean; `uv run python manage.py makemigrations --check` → no changes. Live DocuSeal validation pending — no claim of full production sign-off in this status line.

**Why eleventh**
- staff currently jumps across many Django admin pages to process one family end-to-end
- all underlying service paths already exist (P5–P8); this is presentation/orchestration only
- unlocks faster workflow before adding more billing/parent-facing features

**Target outcome**
- one admin page per family (Guardian) showing applications, agreements, membership, billing/invoices across all children
- action-needed queue as primary entry point, family hub as drill-down
- common actions (approve/request-fix/reject, agreement send/sign/retry/sync/void/regenerate/material amendment, membership discontinuation, billing confirm/push/send/sync) available from the hub
- agreement void and membership discontinuation are clearly separate lanes/actions
- BillingRecord and BillingInvoice shown as one "Norēķini un rēķini" block grouped by child + season
- admin family/member kit-size controls show one form-size field instead of separate shirt/shorts values
- statuses rendered as icon + badge + next-action label, not raw model state strings
- no new business logic, no new model states, no new service methods
- deep edits remain on existing admin change pages

### P12 — Parent invoice visibility
**Status:** dev complete (2026-07-13)

**Why twelfth**
- builds on Invoice Ninja sync and payment read-back already delivered in P6
- gives parents self-service visibility before adding more invoice types

**Target outcome**
- parent portal lists all invoices for the guardian's children
- invoice rows show member, season or event, amount, due date, sent/payment status, and sync freshness
- safe Invoice Ninja payment/view link is shown only when available
- parent access is limited to the verified guardian's own invoices

**Delivered**
- issued membership invoices visible on existing `/portal/`, grouped by child + season
- rows show sequence, due date, amount, sent status, payment status, sync freshness timestamp
- safe stored Invoice Ninja URL opens through Django ownership-check proxy (not raw external link)
- future draft / unissued installments hidden from parent view
- custom invoices remain out of scope (P19)
- verification evidence: targeted P12 tests 28 passed; full gate `uv run pytest -q` → 1703 passed, `uv run ruff check .` → passed, `uv run mypy .` → passed, `uv run python manage.py makemigrations --check` → no changes; code review approved

### P13 — Invoice Ninja client name mapping
**Status:** dev complete incl. mirror cleanup (2026-07-15)

**Why thirteenth**
- Invoice Ninja clients expect separate first-name / family-name values
- MMS previously had one canonical parent full-name field, which made client records weaker and invoice presentation less clean
- this is crucial for MVP billing polish before adding custom invoices

**Delivered**
- `Guardian.first_name` and `Guardian.family_name` added with safe backfill migration `members/0010_guardian_name_parts`; backfill rule uses the last token as family name and earlier tokens as first name
- `Guardian.full_name` mirror dropped by `members/0011_remove_guardian_full_name`; `Guardian.display_name` now derives from `first_name` + `family_name`
- parent registration now renders separate **Vecāka vārds** and **Vecāka uzvārds** fields; production `guardian_full_name` alias removed after backfill cleanup
- guardian OCR maps provider `first_name` / `last_name` into explicit guardian fields and source keys
- Guardian admin edits explicit name fields, shows derived `display_name` read-only, and keeps ParentAccount-owned email/phone consolidation intact
- Invoice Ninja client contact payload sends separate `first_name` and `last_name` while preserving client `name`/`display_name` and `custom_value1` dedup behavior
- display surfaces, DocuSeal payloads, email contexts, exports, and admin search now use `display_name` or explicit name parts; stale mirror sync helpers removed
- verification evidence: cleanup targeted sweep `uv run pytest -q ...` → 290 passed; full gate `uv run pytest -q` → 1757 passed, `uv run ruff check .` → passed, `uv run mypy .` → success (418 source files), `uv run python manage.py makemigrations --check` → no changes; grep check found only historical migrations plus intentional negative tests

### P14 — Family discount tiers
**Status:** complete (2026-07-15)

**Why fourteenth**
- replaces the flat `MembershipPlan.sibling_discount_percent` with graduated tiers (0 %, 50 %, 75 %, 100 %) computed at billing-record creation time
- the discount schedule is fixed club policy, not configurable per plan
- 100 % tier records exist locally for history but do not materialize, push, send, or sync Invoice Ninja invoices

**Target outcome**
- graduated sibling discount: 1st child 0 %, 2nd 50 %, 3rd 75 %, 4th+ 100 %
- ordered by current signed agreement's `signed_at` with `Member.pk` tie-break
- guardian and season isolation for tier computation
- opt-out child occupies its rank but is full-price
- discontinued member (or effective date ≤ first due date) excluded from ranking
- snapshot computed tier atomically under a guardian-row lock
- staff can override draft record total with a required reason (audited; reason excluded from metadata)
- `MembershipPlan.sibling_discount_percent` removed; `BillingRecord.sibling_discount_percent_applied` retained as snapshot

**Delivered**
- Fixed 0/50/75/100 % ranks use current signed agreements ordered by `signed_at`, then member pk; normal signing is season-scoped and guardian-row locked.
- P9 billing-only renewal ranks the guardian's current signed family across seasons; a member without a current signed agreement remains full-price.
- Opt-out stores actual 0 %, stays full-price, and keeps rank; draft recompute/reassign preserve snapshots; blank `first_billing_month` stays blank while scheduling falls back to plan defaults.
- Zero-total records create no Invoice Ninja rows or provider calls and end locally `synced`; draft overrides require a reason including €0, confirmed records lock changes, and audit metadata excludes reason text.
- `MembershipPlan.sibling_discount_percent` is removed; migrations `core/0007` and `billing/0014` landed. Verification: 1791 passed; ruff, mypy, and migration check clean.

### P15 — Calendar-year partial billing ✅ DEV COMPLETE (2026-07-21)
**Why fifteenth**
- extends billing for mid-season signups before adding custom invoices
- ensures parents are only charged for the remaining billable months of the calendar year
- existing records and invoices remain untouched

**Target outcome**
- new agreements only: existing billing records and invoices are not affected
- staff derives default first billing month from plan cutoff; may choose that month or a later month, never backdate
- partial total = annual amount × remaining scheduled billable installments ÷ total plan installment count (skip months excluded from count)
- family discount applied after partial calculation
- staff may override total with a reason; system splits it across remaining scheduled installments
- if no billable month remains in the calendar year, staff must explicitly select an active next-year plan before signing (never silently reuse current-year price)

**Delivery state:** DEV COMPLETE. Implementation landed on `dev`. Deterministic test-only clock pin applied; full suite 1956 passed; `ruff`, `mypy`, and `makemigrations --check` green. Not yet LAN-signed-off. Design spec: `docs/superpowers/specs/2026-07-21-p15-calendar-year-partial-billing-design.md`.

### P19 — Custom invoices
**Why nineteenth**
- extends billing beyond membership dues after parent invoice visibility, client name mapping, family discount tiers, and calendar-year partial billing exist
- covers one-off commercial tournaments, camps, kit, and other special events without abusing membership plans

**Target outcome**
- staff can create one-off invoices for a guardian/member with description, amount, and due date
- custom invoices use the same Invoice Ninja push, sync-health, send, and payment-status model where possible
- parent portal shows custom invoices alongside membership invoices
- creation, push, send, failure, and payment-sync actions stay audited

### P20 — Coaches and training groups
**Why twentieth**
- extends the member/training-group admin model before adding attendance or coach-facing workflows
- keeps coach data structured instead of burying it in free-text group names

**Target outcome**
- staff can create and manage coach records
- one or more coaches can be linked to each training group
- coach names are visible on training-group and member admin surfaces
- parent-visible coach info stays optional and explicitly scoped later
- coach portal, attendance, and messaging remain out of this slice

### P21 — Calendar + WhatsApp attendance integration
**Why later**
- explicitly future scope
- likely separate platform/integration boundary

**Target outcome**
- calendar integration, likely external platform such as Google Calendar
- automated WhatsApp attendance polling integration

### P22 — Daily submitted-registration digest notification
**Status:** full CI-equivalent PostgreSQL suite passed locally (2026-07-27: 1855 tests, ruff, mypy, migration check); GitHub CI rerun and LAN acceptance pending.

**Why twenty-second**
- staff need a dependable daily reminder for submissions without repeatedly polling the admin changelist
- reuses the existing Django mail and django-q2 Schedule foundations; no new service or dependency

**Target outcome**
- one Latvian plain-text Bcc digest per day for configured active staff users
- each row shows child and guardian names, Riga submission time, current status, and a direct admin link
- recipients are configured by a superuser in Django admin; Schedule time is admin-editable after its 08:00 Europe/Riga seed
- each initial submission and correction resubmission is delivered at least once; failed sends leave rows pending for the next daily run
- contact details, personal IDs, addresses, documents, and review messages stay out of the email

---

## 5. Acceptance criteria by priority block

### P1 acceptance — Field-set finalization + guardian-email-first verified registration gate
**Status:** complete

P1 is complete when all of the following are true:

1. Guardian field set is finalized:
   - required / optional fields decided
   - validation rules decided
   - source mapping decided for each field
2. Child/player field set is finalized:
   - required / optional fields decided
   - validation rules decided
   - source mapping decided for each field
3. Registration entry starts with guardian email only.
4. Email code is primary entry verification method:
   - short-lived
   - single-use
   - rate-limited
   - typed email alone grants nothing
5. Existing guardian flow works:
   - verified code attaches to existing guardian account
   - user lands on chooser/dashboard
   - if draft exists, **continue draft** is primary action
   - **start new registration** is available on same screen
   - past/current registrations list is visible on same screen
6. New guardian flow works:
   - verified code creates/establishes verified session/account
   - user can continue into new registration flow
7. Same verified gate protects both registration continuation and portal access.
8. Old insecure ownership path is removed:
   - typed email can no longer auto-link or expose another guardian’s registrations
9. Tests prove behavior:
   - existing guardian code flow
   - new guardian code flow
   - chooser behavior
   - continue-draft priority
   - start-new option visibility
   - registrations-list visibility
   - cross-account exposure regression

Verification evidence captured in current codebase:
- full suite green: `349 passed`
- registration suite green: `229 passed`
- lint green: `ruff check .`
- types green: `mypy .`

### P2 Task 4 — Document state, OCR source cues, error summary
**Status:** complete

**Delivered outcome**
- Reusable document card partial (`document_card.html`) shows filename, kind label, active state, and replace action in parent workspace.
- Error summary uses `items` parameter to render field label, validation message, and anchor link to invalid field.
- Source badges render for `manual_only`, `derived_system_filled`, and OCR markers using `SOURCE_LABEL_MAP` in `presentation.py`.
- Invalid-submit error summary shows heading, field label, validation message, and anchor target.
- No schema changes, no business rule changes, no admin redesign.

### P2 acceptance — Visual system + registration UX redesign
**Status:** complete

P2 is complete when all of the following are true:

1. Style guide is applied on parent-facing flow:
   - canonical tokens used
   - typography readable on desktop/mobile
   - public pages reflect FK Cēsis identity
2. Guardian-email entry page is redesigned:
   - clear first step
   - email + code flow feels obvious
   - calm branded entry experience
3. Existing-guardian chooser/dashboard is redesigned:
   - resumable draft is primary if present
   - **start new registration** on same screen
   - past/current registrations visible
   - next action obvious
4. Registration form is redesigned:
   - grouped guardian, child/player, and document sections
   - shared template primitives used
   - layout supports later designer polish
5. Document-upload UX is clearer:
   - guardian and member documents clearly separated
   - active uploaded document state visible
   - replace/refresh action understandable
6. OCR-prefill review UX is clear:
   - extracted values distinguishable
   - user can correct without confusion
   - sensitive metadata shown only where appropriate
7. Validation UX is improved:
   - readable field errors
   - useful top-level summary where needed
   - invalid submit feels understandable
8. Parent portal / registration list matches same visual system.
9. No workflow regression:
   - verified entry, chooser, continue draft, start new, save draft, submit still work
   - no insecure ownership regression
10. Tests cover critical workflow/state behavior without brittle visual-detail assertions.
11. Public visual implementation remains easy to refine with designer assistance.

### P3 acceptance — OCR integration + secure extracted metadata
**Status:** complete (2026-05-22) — live validation evidence in `docs/p3_tiny_idp_validation.md`

P3 is complete when all of the following are true:

1. Real OCR integration exists for guardian and member documents.
2. App config can switch OCR mode between:
   - real OCR provider
   - stub/dummy OCR provider returning deterministic dummy data
3. OCR covers both document roles:
   - guardian identity document
   - member identity document
4. Extracted person fields are mapped according to P1 field-finalization decisions.
5. Extracted document metadata is stored in serialized form where available:
   - document number
   - issuer
   - issuance date
   - expiry
   - similar fields
6. Sensitive OCR data is secured with same posture as raw identity documents.
7. OCR remains non-blocking:
   - registration can continue if OCR fails
8. Manual correction flow works:
   - user/admin can review and correct OCR-filled values
   - corrected values override OCR guesses
9. Basic admin OCR controls exist:
   - admin can see OCR state
   - admin can review extracted data
   - admin can trigger/retrigger OCR where appropriate
10. Provider boundary is clean and adapter-based.
11. Tests cover:
   - real/stub mode selection
   - success path
   - failure path
   - non-blocking behavior
   - metadata storage
   - manual correction path
   - admin retry/review behavior
   - secure handling expectations where testable

### P3.5 acceptance — Async OCR UX + background-job baseline
**Status:** complete (2026-05-23) — plan archived at `docs/superpowers/plans/2026-05-22-p3.5-async-ocr-ux.md`.

**Post-merge fixes (2026-05-23):**
- `/applications/new/` redirects to a freshly created blank draft workspace (was rendering a synchronous wizard form with no application_id, so async upload had no endpoint to POST to).
- Workspace wizard now lands on step 1 (ID documents) instead of the review step.
- Page-load polling: workspace polls any documents already in `ocr_status=PENDING` on load (previously the JS only bound to file-pick events, so PENDING docs from a sync save were never observed).
- Guardian-doc reuse no longer double-prefixes `private/documents/` on the file path (each reuse used to compound the prefix until `FileSystemStorage` ran out of `max_length`).
- `STATICFILES_DIRS` switched to `(prefix, path)` tuple form so `/static/style-guide/tokens.css` resolves correctly.

P3.5 is complete when all of the following are true:

1. Background-job runner is in place:
   - **django-q2** added via `uv add`, configured against the Django DB broker
   - worker entry point documented in `AGENTS.md` (how to start, how to stop, how it behaves in dev vs prod)
   - at-least-once retry policy defined for OCR jobs
   - failure visibility: failed jobs surface in Django admin or equivalent inspection point
2. Document upload is async on the parent registration page:
   - selecting a file POSTs it immediately, without waiting for form submit
   - upload endpoint returns a document ID and initial status
   - failed uploads (size limit, type rejection, network error) surface clear inline errors and do not block other fields
3. OCR is enqueued automatically after upload completes:
   - synchronous OCR path is removed from the upload request/response cycle
   - encrypted payload + summary persistence remains identical to P3
   - classified exception mapping (`provider_misconfigured`, `auth_failed`, `rate_limited`, `request_timeout`, `provider_unavailable`, `invalid_response`) still applies inside the job
4. Per-document progress states are visible to the parent:
   - states: `uploading`, `uploaded`, `ocr_running`, `ocr_done`, `ocr_failed`
   - frontend polls (or receives via SSE) until terminal state reached
   - polling stops on terminal state; no zombie polling loops
   - `ocr_failed` shows a non-blocking message; the parent can still submit
5. Prefill vs suggestion rule is implemented:
   - on `ocr_done`, fields whose current value is empty or whitespace-only are auto-filled and tagged with the existing OCR source badge
   - fields whose current value is non-empty (including `derived_system_filled` from guardian-reuse) show an inline OCR suggestion chip beside the field
   - accepting a suggestion overwrites the value and updates the source badge to OCR
   - dismissing a suggestion hides the chip; the dismissal is not persisted across sessions (acceptable for first slice)
6. Admin and audit posture preserved:
   - admin OCR review screens still show extracted data and confidence values
   - admin-triggered re-OCR still works (enqueues a new job)
   - private-document access controls unchanged
7. No workflow regression:
   - verified entry, chooser, continue draft, start new, save draft, submit still work
   - parent can submit the application even if OCR is still running (submitted application records the pending OCR state)
   - non-blocking OCR failure path still passes its test
8. Tests cover:
   - async upload endpoint (success + validation failure)
   - job enqueue on upload completion
   - job success path persists encrypted payload + summary as before
   - job failure path sets `ocr_failed` and records `ocr_error_code`
   - prefill rule: empty field is filled, non-empty field gets a suggestion
   - suggestion accept/dismiss interactions
   - submit-while-OCR-pending behavior
   - admin re-OCR enqueue
9. Documentation updated:
   - `AGENTS.md` describes the worker process, the job lifecycle, and how OCR fits in
   - `README.md` includes worker startup in the local-dev quickstart

### P4 acceptance — Parent-flow UX polish + mobile-first workspace
**Status:** complete (2026-05-25).

P4 is complete when all of the following are true:

1. **P3.5 polish leftovers landed**:
   - calm branded spinner during `ocr_running` with "Apstrādājam dokumentu…" copy
   - one-shot "Dokumenta apstrāde pabeigta. Persona atpazīta kā <First Last>." confirmation on `ocr_done`
   - refined OCR suggestion chip styling and source-badge visual consistency
   - visibility-aware polling pauses while the tab is hidden and resumes on focus
   - Latvianized failure messages for upload, OCR, and validation errors
2. **Latvian copy normalized** across all parent-facing templates, partials, and inline JS strings; zero English leakage on `/register/`, `/register/verify/`, `/portal/`, `/applications/new/`, `/applications/<id>/`; admin surfaces unchanged.
3. **Name normalization from OCR**:
   - ALL CAPS → Latvian title-case ("JĀNIS BĒRZIŅŠ" → "Jānis Bērziņš")
   - hyphenated compound surnames ("BĒRZIŅŠ-KALNIŅŠ" → "Bērziņš-Kalniņš") handled
   - particles ("VAN DER BERG" → "van der Berg") handled
   - normalization at the OCR-result-processing layer before the decrypted prefill summary is consumed; encrypted payload at rest unchanged
   - unit tests cover representative Latvian + particle cases
4. **Step-gated wizard with inline validation and auto-save**:
   - "Turpināt" CTA disabled until current step's required fields are all valid
   - validation runs on blur for first-touch fields and on change for fields previously shown invalid
   - inline error messages render beneath each field
   - draft auto-saves with ~500 ms debounce on field change, plus on blur and on step transition
   - "Saglabāts" indicator confirms persistence; transient save failures retry silently and surface only on terminal failure
   - auto-save preserves `fix_requested` status; ownership posture unchanged
5. **Personal data consent on step 1 (ID documents)**:
   - required checkbox at the top of the ID-documents step
   - expandable inline T&C (collapsed by default, "Lasīt vairāk" toggle) with default Latvian draft pending legal review
   - "Turpināt" on step 1 disabled until checkbox ticked AND step-1 fields valid
   - `personal_data_consent_at` (timestamp) and `personal_data_consent_version` (text) persist on `RegistrationApplication`
   - resuming a draft with prior consent of the current version does not re-prompt
   - existing in-flight drafts must re-consent on resume (consent fields default to unset)
6. **Document/photo upload with camera capture**:
   - each upload slot exposes "Augšupielādēt failu" (file picker) and "Uzņemt attēlu" (camera capture)
   - camera capture uses HTML `<input type="file" accept="image/*" capture="environment">`; no custom `getUserMedia` pipeline in this phase
   - camera control hidden gracefully on devices/browsers without `capture` support
   - captured images flow through the existing async upload + OCR enqueue path from P3.5
7. **Mobile-first registration workspace**:
   - `/applications/<id>/` wizard laid out narrow-viewport-first, enhanced for desktop
   - primary CTA sticky on mobile
   - wizard steps use progressive disclosure (one step at a time, prior steps collapsible/back-navigable)
   - all interactive controls (wizard nav, document card actions, consent checkbox, camera/upload buttons) have touch targets ≥44 px
8. **Entry + chooser + portal polished**:
   - `/register/`, `/register/verify/`, `/portal/`, and parent registration list audited at mobile breakpoints
   - empty and error states use the shared cross-cutting primitives
   - visual cohesion with the workspace (same tokens, typography, spacing)
9. **Cross-cutting UX primitives**:
   - shared empty-state partial used across surfaces
   - shared error-state partial used across surfaces
   - consistent spinner, toast, and inline-error patterns
10. **No regression**:
    - verified entry, chooser, continue draft, start new, save draft, submit still work
    - async upload, OCR enqueue, suggestion accept/dismiss still work
    - non-blocking OCR failure path still passes its test
    - ownership/security posture unchanged
11. **Schema migration applied**:
    - two new nullable fields on `RegistrationApplication` (`personal_data_consent_at`, `personal_data_consent_version`)
    - migration committed; existing drafts default to unset (forcing re-consent on resume)
    - no other model changes
12. **Tests cover**:
    - name-normalization helper across Latvian, hyphenated, particle, and edge cases
    - "Turpināt" gating: invalid field → disabled; valid field + missing consent on step 1 → disabled; both valid → enabled
    - auto-save debounce, blur, and step-transition triggers; transient retry path
    - consent persistence and resume behavior
    - async upload from camera-capture input
    - OCR success confirmation message renders with normalized name
    - visibility-aware polling pauses/resumes correctly
    - critical mobile breakpoints render expected layout (DOM-level, not pixel-perfect)
13. **Documentation updated**:
    - `AGENTS.md` notes the T&C version handling and consent fields
    - `README.md` worker startup section unchanged from P3.5
    - default T&C text marked as pending legal review

### P5 acceptance — Approval-to-agreement flow
P5 is complete when all of the following are true:

1. Admin review shows inline document preview:
   - guardian and member ID docs visible inline beside applicant data
   - preview remains admin-only
   - active doc clearly distinguished from replaced doc
2. Admin review supports approval-ready inspection:
   - guardian/player data, OCR data, and doc metadata visible together
3. Training-group assignment flow exists:
   - assignment during approval is optional
   - admin can assign during approval or immediately after
   - assignment state is visible and editable
4. Approval remains idempotent:
   - repeated approval does not create duplicate guardian/member/agreement records
5. Agreement is generated after approval.
6. Agreement platform integration exists at metadata/API level:
   - Django can create/register agreement in external agreement platform
   - Django stores external agreement identifiers and state
   - preferred direction is **DocuSeal self-hosted**
   - adapter boundary remains clean
7. Manual signing flow is tracked:
   - `generated`
   - `sent/shared`
   - `signed`
8. Supported manual signing paths are explicit:
   - LV qualified electronic signature
   - paper signing
9. Agreement platform is source of truth:
   - signed documents live in agreement platform, not Django storage
   - signed state comes back to Django via API sync
10. Agreement access/security is defined appropriately.
11. Parent/admin visibility is clear:
   - admin can see agreement state
   - parent can see appropriate status/next step if needed
   - no misleading in-app e-sign UX
12. Tests cover:
   - inline preview access control
   - training-group assignment path
   - approval idempotency
   - agreement generation
   - external-platform linkage/state tracking
   - signed-state sync behavior

### P6 acceptance — Billing / Invoice Ninja sync
P6 is complete when all of the following are true:

1. Billing starts only after agreement platform final state is **completed**.
2. Billing is created automatically after Django sync confirms `completed` state.
3. Membership billing model exists:
   - annual fee baseline
   - payment mode
   - billing start month
   - sibling-discount state
4. Invoice Ninja integration exists:
   - Django can create/update customer/contact data
   - Django can create/register recurring billing setup
   - Django stores external billing identifiers and sync state
5. Sibling discount logic works:
   - second child discount determined from guardian identity linkage
   - full-price opt-out supported
   - manual exception path remains possible
6. Installment schedule rules work:
   - €300 baseline
   - upfront and installment modes
   - agreed installment calendar
   - billing start month respected
7. Invoice Ninja remains source of truth for invoices and payment state.
8. Sync state and retries exist:
   - agreement sync and billing sync failure states visible
   - retry path exists
   - admin can see sync health
9. Payment-status visibility exists:
   - Django reads invoice/payment state back from Invoice Ninja on scheduled sync
   - sync runs at least nightly
   - cadence is configurable
10. Integration boundaries are clean:
   - agreement-platform adapter separate from billing adapter
   - Invoice Ninja logic behind adapter/service boundary
11. Security/data handling is acceptable:
   - payer/billing data handled carefully
   - payload logging redacted
   - secrets/config externalized
12. Tests cover:
   - completed-agreement prerequisite gating
   - automatic trigger after completed-state sync
   - sibling discount logic
   - installment rules
   - scheduled payment-status sync behavior
   - retry/failure handling
   - payment-status sync

### P7 acceptance — Admin operations / export / audit polish
P7 is complete when all of the following are true:

1. Admin search/filter is useful for registrations, members, agreements, and billing records.
2. CSV export exists for both:
   - members
   - registrations/applications
3. Agreed MVP export fields are available, with sensitive fields included only where explicitly allowed.
4. Audit coverage is completed for critical actions:
   - review actions
   - document preview/download/delete
   - agreement/billing sync actions where needed
5. Document admin UX is clearer:
   - active vs replaced clearly distinguished
   - inappropriate preview/download actions hidden or disabled
6. Sync/admin visibility is polished:
   - OCR, agreement, and billing sync states clearly visible
   - failures visible
   - retry/recovery actions understandable
7. Operational detail views are usable with enough linked context.
8. Permissions remain tight and sensitive actions stay staff-only and audited.
9. Exports and audit are safe:
   - no accidental public exposure
   - no sensitive data leakage through logs/export defaults
10. Tests cover:
   - search/filter basics
   - member export
   - registration/application export
   - audit event creation
   - active/replaced document handling
   - admin visibility for sync/error states

### P8 acceptance — Agreement lifecycle ✅ COMPLETE (2026-06-30)
P8 is complete when all of the following are true:

1. Staff can amend an active agreement while preserving the signed original and lifecycle history.
2. Staff can discontinue an agreement/member relationship with an effective date, reason, audit event, and parent-visible status.
3. Regeneration/replacement rules are explicit for generated, sent, signed, voided, amended, and discontinued agreements.
4. Parent and admin surfaces clearly show the current agreement state and the reason/action needed when applicable.
5. DocuSeal-backed and manual-signing paths both follow the same internal lifecycle rules.
6. Billing side effects are defined and safe:
   - draft records can be adjusted where allowed
   - confirmed/synced invoices are never silently mutated
   - credits/adjustments/stop-future-invoices flows are explicit where needed
7. Audit events cover amendment, discontinuation, replacement, and lifecycle-state changes.
8. Tests cover:
   - amendment history preservation
   - discontinuation flow
   - replacement/regeneration guards
   - billing side-effect guards
   - parent/admin status visibility

### P9 acceptance — Billing plan lifecycle
P9 is complete when all of the following are true:

1. New agreements do not rely on "latest active plan wins" silently.
2. Staff can assign or override the billing plan before draft `BillingRecord` creation.
3. Existing active members can be renewed into a new season/plan in bulk or per member.
4. Draft billing records can be reassigned or regenerated safely.
5. Confirmed billing records and pushed Invoice Ninja invoices are never silently mutated.
6. Any confirmed/synced change path is explicit: renewal, adjustment, credit, or new invoice flow.
7. Parent-facing billing amounts remain explainable after renewal/plan changes.
8. Audit events cover plan assignment, renewal, and post-confirmation adjustments where applicable.
9. Tests cover:
   - new-agreement plan assignment
   - renewal creation
   - draft reassignment
   - confirmed/synced no-silent-mutation guard

### P10 acceptance — Public-site analytics + registration funnel
P10 is complete when all of the following are true:

1. Platform comparison selects an analytics tool against three blocker-level constraints:
   - GDPR/privacy posture: EU/self-host option, cookie/IP handling, retention, DPA/config path
   - funnel/event power: public traffic, registration funnel, and parent portal ops events are practical
   - ops burden: simple enough to operate without a custom analytics stack
2. Public-site traffic stats are visible:
   - visits
   - page views
   - referrers
   - top pages
3. Registration funnel is visible in aggregate:
   - public visit
   - registration start
   - verified access
   - application submitted
4. Parent portal operational usage is visible in aggregate:
   - portal visits
   - key CTA usage
   - empty/error-state frequency
   - basic page health signals where the chosen platform supports them simply
5. Scope boundaries are enforced:
   - no admin tracking
   - no ad/tracking pixels such as Google Analytics or Meta Pixel
   - no per-user behaviour profiling
   - no custom BI warehouse or bespoke dashboard unless the selected platform provides it natively
6. Analytics payloads never include sensitive values:
   - no names
   - no emails
   - no phone numbers
   - no personal IDs
   - no document metadata or filenames
   - no free-text form values
7. GDPR/privacy posture is documented before production enablement:
   - hosting model
   - cookie use or cookie-free mode
   - IP anonymization / minimization
   - retention
   - DPA or self-host responsibility
   - consent/notice implications
8. Tests or config checks cover:
   - event emission boundaries
   - public/registration/parent-portal events only
   - PII guardrails where practical

### P11 acceptance — Family admin action hub
P11 is complete when all of the following are true:

1. Staff can open one Guardian/family and see the full current state across application, agreement, membership, and billing lanes on one page.
2. Staff can complete the normal workflow (approve application → send agreement → mark signed → confirm billing → push invoices) from the hub without navigating to deep admin change pages.
3. The action-needed queue shows all families with pending actions, ordered by urgency.
4. Statuses are rendered as icon + badge + next-action label, not raw model state strings.
5. Agreement void and membership discontinuation are clearly separate actions in separate lanes.
6. Billing is shown as one unified "Norēķini un rēķini" block grouped by child + season, with expandable invoice rows.
7. Admin family/member kit-size controls expose one form-size value, not separate shirt/shorts values.
8. LAN acceptance proves staff can understand a family's status and complete the normal workflow in under ~30 seconds.
9. All hub actions reuse existing service paths — no new business logic.
10. Tests cover queue ordering/filtering, hub page rendering, each hub action triggering the correct service, void-vs-discontinuation separation, billing block grouping, kit-size admin display, and permission checks.

### P12 acceptance — Parent invoice visibility ✅ COMPLETE (2026-07-13)
P12 is complete when all of the following are true:

1. Parent portal lists every invoice linked to the verified guardian's members.
2. Membership invoices show member, season, installment sequence where applicable, due date, amount, sent status, payment status, and last sync time.
3. Custom/non-membership invoice rows have a clear label and do not masquerade as membership dues.
4. Invoice Ninja payment/view links are shown only when a safe external URL or portal URL is available.
5. Authorization prevents one guardian from seeing another guardian's invoices.
6. Empty/error states are parent-friendly and Latvian.
7. Tests cover ownership, status display, empty state, and mixed paid/unpaid invoices.

### P13 acceptance — Invoice Ninja client name mapping
P13 is complete when all of the following are true:

1. MMS has a decided source of truth for parent first-name and family-name values: explicit fields or a documented derivation from the canonical full name.
2. Existing guardians are migrated/backfilled safely, or the derivation path is proven safe without migration.
3. Invoice Ninja client create/update payload sends first-name and family-name values in the fields Invoice Ninja expects.
4. Existing Guardian/ParentAccount contact-data consolidation remains intact; no duplicate email/phone source is reintroduced.
5. Admin and parent surfaces still render the canonical parent display name clearly.
6. Tests cover Latvian names, multi-token names where practical, empty/ambiguous names, and Invoice Ninja payload mapping.

### P14 acceptance — Family discount tiers ✅ COMPLETE (2026-07-15)
P14 is complete when all of the following are true:

1. All four tiers verified: 1st child 0 %, 2nd 50 %, 3rd 75 %, 4th+ 100 %.
2. Signed-time ordering + pk tie-break verified.
3. Guardian and season isolation verified.
4. P9 billing-only renewal ranks the current signed family across target-plan seasons; no current signed agreement means full-price.
5. Opt-out rank preserved (full-price, stores 0 % actual applied discount, but occupies rank).
6. Discontinuation-before-first-due exclusion verified.
7. Snapshot stability verified (old records retain stored tier).
8. Concurrency guard verified (guardian-row `select_for_update`).
9. Zero-record never produces an invoice or provider call.
10. Override/reason/locking/audit verified (reason excluded from metadata).
11. Old plan discount field (`sibling_discount_percent`) removed.
12. Full verification passes: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`.

### P15 acceptance — Calendar-year partial billing ✅ DEV COMPLETE (2026-07-21)
P15 is complete when all of the following are true:

1. New agreements only: existing billing records and invoices untouched. ✅
2. Staff derives default first billing month from plan cutoff; may choose later, never backdate. ✅
3. Partial total = annual amount × remaining billable installments ÷ total installment count (skip months excluded). ✅
4. Family discount applied after partial calculation. ✅
5. Staff override splits across remaining scheduled installments. ✅
6. No billable month remaining → staff must select active next-year plan (never silently reuse current-year price). ✅

**Delivery state:** DEV COMPLETE. Deterministic test-only clock pin applied; full suite 1956 passed; `ruff`, `mypy`, `makemigrations --check` green. Not yet LAN-signed-off.

### P16 acceptance — Signed-agreement upload + verification
P16 is complete when all of the following are true:

1. Staff can upload a signed PDF or `.edoc` file attached to an Agreement.
2. Uploaded artifacts are private, accessible only through authorization-checked proxy views from admin detail, family hub, agreement detail, and verified guardian portal.
3. Registration admin is the sole upload path. Registration admin, family hub, and read-only agreement admin display/download routes enforce staff permission (agreement admin uses `has_view_permission`); guardian proxy enforces ownership of the linked member.
4. One current artifact per Agreement; replacement permanently deletes the prior file only after the new upload succeeds and is audited.
5. Redacted `AuditEvent` on upload/replace — no signer data, no file bytes, no validation results in metadata.
6. Best-effort background eParaksts validation via SignAPI (session-based OAuth): valid signer names, signing time, format, and status shown to admin + guardian; failure or unavailability does not block publication (guardian sees neutral "Status nav pieejams").
7. eParaksts credentials prerequisite: test credentials present before implementation; production credentials + suitable security/data-processing terms before production sign-off.
8. Provider links documented: https://developers.eparaksts.lv/v2.0/docs/before-you-start-1, https://developers.eparaksts.lv/docs/test-environment, https://developers.eparaksts.lv/v2.0/docs/validation-api.
9. Out of scope confirmed: no interactive in-portal eParaksts signing, no raw provider URLs, no reusing the registration `Document`/OCR model.
10. Tests cover authorization checks on proxy views, upload/replace audit events, replacement-delete-after-success sequence, and eParaksts failure/availability handling, and stale validation job result/error rejection after a newer artifact upload.

### P17 acceptance — Configurable member export
**Status:** complete (2026-08-26).

P17 is complete when all of the following are true:

1. Staff can create, edit, and delete shared saved export templates with custom column selections.
2. All staff may include sensitive columns in templates; templates are staff-only and audited.
3. Never export values/bytes in logs or audit metadata.
4. One Member row per export; columns selected via stable allowlisted keys only (member/guardian/current-agreement/training-group).
5. Agreement status filter: selected agreement statuses as OR within each chosen set; selected groups as OR within group set; those two predicates AND when both configured; empty = unfiltered.
6. Current agreement only filter (not all historical agreements).
7. CSV/XLSX per run; XLSX default when available; CSV keeps UTF-8 BOM + semicolon + formula guard.
8. Direct download only; no stored output files.
9. P7 static CSV exports remain unchanged (additive).
10. Out of scope confirmed: no guardian-row templates, no scheduled email exports, no arbitrary formula columns, no arbitrary queries.
11. Tests cover template CRUD, column allowlist enforcement, filter combination (OR within state set; OR within group set; AND between state and group predicates), CSV/XLSX output format, formula guard, and audit event emission.

### P18 acceptance — Unfinished-application lifecycle
P18 is complete when all of the following are true:

1. Automatic workflow for draft and fix_requested only: generic no-PII reminder emails at 7 and 21 inactive days, archive at 60 inactive days.
2. Daily schedule at 09:00 Europe/Riga (django-q2 Schedule, admin-editable).
3. Follow-up anchor resets on parent save and request_fix.
4. At/in excess of 60 days: archive; no reminder sent in the same sweep.
5. Reminder recipient: verified parent-account email when present, else `claimed_email`; blank both means skip reminder (no timestamp), leave eligible for later retry; archive timing unaffected; email goes to `/register/` with standard one-time-code gate.
6. New `archived` status; retain: anchor, reminder timestamps, archive time, prior state, archive actor (null for automated).
7. Auto-archived draft/fix_requested can resume (restores prior state, resets timer); manual staff archive for draft/submitted/fix/rejected; approved cannot be archived; manually archived submitted/rejected show read-only in portal, no resume.
8. Audit reminder, archive, resume — no PII in audit metadata.
9. Out of scope confirmed: no deletion/purge, no staff reminders, no SMS/WhatsApp, no automatic reminders for submitted/rejected, no new auth links, no automatic reopening.
10. Tests cover reminder emission at 7/21 days, archive at 60 days, anchor reset on save/request_fix, reminder recipient fallback, resume, manual archive guards, and audit event emission.

### P19 acceptance — Custom invoices
P19 is complete when all of the following are true:

1. Staff can create a one-off invoice for a guardian/member with description, amount, due date, and optional event/category label.
2. Custom invoices can be pushed to Invoice Ninja without creating or mutating membership-plan billing records.
3. Custom invoices reuse existing sync-health, send, and payment-status visibility where possible.
4. Parent portal shows custom invoices alongside membership invoices with a distinct label.
5. Confirmed/sent custom invoices are not silently mutated; corrections use explicit adjustment/credit/reissue flow.
6. Audit events cover create, update-before-send, push, send, failure, and payment sync where applicable.
7. Tests cover staff creation, push payload, parent visibility, ownership, and no membership-plan pollution.

### P20 acceptance — Coaches and training groups
P20 is complete when all of the following are true:

1. Staff can create and edit coach records in admin.
2. Training groups can have one or more linked coaches.
3. Member and training-group admin views show linked coach names clearly.
4. Search/filter support helps staff find groups by coach where practical.
5. Coach data is not exposed to parents unless explicitly enabled in a later slice.
6. Coach portal, attendance, and messaging are not introduced in this milestone.
7. Tests cover coach CRUD basics, group linkage, and admin display/search behaviour.

### P21 acceptance — Calendar + WhatsApp attendance integration
P21 is complete when all of the following are true:

1. Calendar integration direction is implemented, likely via external platform such as Google Calendar.
2. Platform boundary is clean and loosely coupled to Django monolith.
3. Attendance polling flow exists through WhatsApp.
4. Event/member/guardian mapping works reliably.
5. Operational visibility exists for request/send/response state and failures.
6. Consent / messaging controls are acceptable and configurable.
7. Security / privacy posture is acceptable:
    - data sharing minimized
    - secrets/config externalized
    - audit/log posture reasonable
8. Calendar adapter and messaging adapter remain separate and replaceable.
9. Attendance responses for first slice are limited to:
    - yes
    - no
    - maybe
10. Tests cover critical mapping/failure behavior where testable.

### P22 — Daily submitted-registration digest notification
P22 delivers a daily Bcc email to configured staff summarising every submitted application that has not yet been included in a digest. The email lists child name, guardian name, Riga submission datetime, current status, and admin link per application. It omits contact data, personal IDs, addresses, documents, and review messages. The digest job uses a django-q2 daily Schedule (default 08:00 Europe/Riga, admin-editable after migration), per-row delivery flags on `RegistrationApplication`, and a singleton `RegistrationSubmissionDigestSettings` model for recipient management (superuser-only admin). At-least-once delivery semantics: send failures leave flags untouched so the next day retries.

**Delivery state:** CI exposed and P22 fixed a PostgreSQL nullable-outer-join lock regression. Full CI-equivalent local PostgreSQL verification passed 2026-07-27: `uv run pytest -q` → 1855 passed; `uv run ruff check .`, `uv run mypy .`, and `uv run python manage.py makemigrations --check` clean. GitHub CI rerun and LAN acceptance pending.

### P22 acceptance — Daily submitted-registration digest notification
P22 is complete when all of the following are true:

1. `RegistrationSubmissionDigestSettings` singleton exists after migration (pk=1).
2. A django-q2 Schedule named `registrations-submission-digest` exists, pointing to `apps.registrations.tasks.send_submitted_registration_digest`, schedule type DAILY.
3. Submitting a draft application sets `submitted_at` and clears `submission_digest_sent_at` to `NULL`.
4. Running `send_submitted_registration_digest()` with configured recipients and pending rows sends one Bcc email and stamps `submission_digest_sent_at` on all included rows plus `last_successful_at` on the singleton.
5. The email body contains only child name, guardian name, Riga datetime, status, and admin URL — no emails, phone, PID, address, docs, or review messages.
6. With no recipients configured, the job returns 0 and leaves flags unchanged.
7. With a send failure (SMTP error), the job returns 0 and leaves flags unchanged (retry next day).
8. Resubmitting a fix_requested application clears `submission_digest_sent_at` so it appears in the next digest.
9. Only superusers can access the digest settings in Django admin.
10. The recipient picker shows only active staff Users.
11. Full repository verification passes: `uv run pytest -q` (all tests), `uv run ruff check .`, `uv run mypy .`.
12. Manual LAN acceptance confirms end-to-end: configure recipients, submit application, verify staff inbox receives digest, verify flag stamping, verify re-submit re-arms flag, verify failure handling.

---

## 6. Milestone map

### M1 — Security and foundation completion
Delivered:
- background-job baseline (django-q2, delivered in P3.5)
- OCR metadata security posture (delivered in P3)
- audit event baseline (P7 Slice A, delivered 2026-06-13)

### M2 — Parent intake completion
Delivered:
- verified registration intake (P1: guardian email entry + OTP verification, chooser/dashboard)
- dual-document registration flow with OCR-backed prefill (P3)
- parent-flow UX polish: step-gated wizard, auto-save, consent gate, camera capture, mobile-first workspace, Latvian copy normalization (P4 Slices A–E)

### M3 — Approval-to-membership and agreement completion
Delivered:
- admin review consolidation into Django admin (P7 Slice C-i, 2026-06-14)
- membership creation with canonical Guardian reuse (P6 Slice A, 2026-06-10)
- agreement lifecycle: generation, amendment, discontinuation, replacement (P8, 2026-06-30)
- DocuSeal-backed e-signature (P5 Slice D, 2026-06-06)
Planned / blocked extension:
- P16 signed-artifact custody is Blocked pending eParaksts test credentials.

### M4 — Billing completion
- P15 LAN signoff (calendar-year partial billing, dev complete, LAN pending)
- P19 custom one-off invoices (planned)

### M5 — Admin operations completion
- P17 configurable member export (delivered 2026-08-26)
- P18 unfinished-application lifecycle (planned)
- P20 coaches linked to training groups (planned)
- P22 daily submitted-registration digest (local Postgres green, CI rerun + LAN pending)

### M6 — Production readiness

Delivered:
- two-channel deployment pipeline (2026-05-26, CI migrated to GitHub Actions 2026-07-03): containerized stack (`Dockerfile`, `compose.yaml` — `web` + `qcluster` + `postgres` 18, non-root UID 10001, whitenoise static, `/healthz` probe, configurable host port). Branch strategy: `dev` → floating `:dev` (dev server auto-pulls); `main` → floating `:main` plus immutable `:<major>.<minor>` from the `VERSION` file (prod server auto-pulls `:main`, can pin to a `:<X.Y>` for rollback). GitHub Actions CI orchestrates lint → test → branch-specific build/push to GHCR; deployment remains manual. All host-side services run as the unprivileged `fkmms` user (UID 10001 matches in-container `app`).
- deployment runbook: `docs/deployment.md`.
- public-site analytics and registration funnel visibility (P10) — code/docs delivered; production enablement still needs provider setup + dashboard smoke.

Remaining focus:
- prod environment / second host (same image, `:prod` floating tag, separate `.env`)
- recovery/backup notes (today: ad-hoc `pg_dump`; need scheduled job + off-host shipping)
- integration configuration docs (Invoice Ninja, SMTP provider choice)
- final security checklist (CSP, rate-limit, fail2ban, audit-log review)

### Future / post-MVP
- custom one-off invoices (P19)
- coaches linked to training groups (P20)
- calendar integration (P21)
- WhatsApp attendance polling (P21)

---

## 7. Explicit non-priorities right now
- coach portal
- adult members
- attendance tracking inside this monolith
- event / competition / travel planning
- direct national FA integration
- multilingual architecture
- SPA or API-first rewrite

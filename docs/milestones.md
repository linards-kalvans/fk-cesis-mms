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
- admin review queue/detail baseline exists
- review actions exist: request fix, reject, approve
- approval creates `Guardian` and `Member`
- `TrainingGroup` model exists, but approval currently leaves assignment empty

---

## 3. Confirmed target direction not yet implemented

### Agreement handling
- after approval, generate agreement
- first slice uses manual signing outside Django app
- agreement platform is source of truth for agreement artifact and signed state
- signed state sync comes back to Django through API
- preferred future richer agreement-processing direction: **DocuSeal self-hosted**

---

## 4. Open gaps and debt

### Security and architecture gaps
- audit/event baseline **delivered (P7 Slice A, 2026-06-13)** — `apps.core.AuditEvent` append-only model + fail-safe `record_audit_event` helper + read-only admin viewer + configurable retention prune (`AUDIT_RETENTION_DAYS`=730, daily `audit-retention-prune` Schedule). Wired: review actions, training-group assign/clear, document preview/download/delete, agreement sent/signed/voided/sync-failed, billing push/sync-triggered + push/send/payment-sync failures. Routine automated sync successes deliberately not audited. Spec/plan under `docs/superpowers/`. (P7 Slices B export + C admin-polish still pending.)

### Registration UX gaps
- step-gated wizard validation with background draft auto-save — delivered in P4 Slice C
- camera-capture option for document/photo upload — delivered in P4 Slice D
- personal-data consent gate on the ID-documents step — delivered in P4 Slice C
- OCR processing UX (spinner, success confirmation, name title-casing) — delivered in P4 Slices A + B
- Latvian copy normalization across parent-facing surfaces still incomplete (deferred to P4 Slice E)
- mobile-first responsiveness on the parent registration workspace — workspace delivered in P4 Slice D; entry/chooser/portal mobile polish deferred to P4 Slice E
- unnecessary re-upload can replace earlier file and create confusing admin rows (P7 target)

### Admin UX gaps
- admin review should show inline identity-document previews beside applicant data (P5 target)
- admin document UX should better distinguish active vs replaced documents **delivered (P7 C-ii b2 Plan 2, 2026-06-15)** — `DocumentAdmin` Aktīvs/Vēsturisks badge + `state` filter
- training-group assignment flow still incomplete (P5 target)
- review-action audit entries **delivered (P7 Slice A, 2026-06-13)** — approve/reject/request-fix now recorded as `AuditEvent`s with actor + target

#### P7 — COMPLETE (LAN sign-off 2026-06-19)
All of P7 is delivered: Slices A (audit), B (export), C (C-i + C-ii batch 1 + batch 2 Plans 1–3), the Guardian/ParentAccount consolidation, the admin menu re-order, and the audit close-out.
- **Audit gaps — CLOSED (2026-06-16).** The billing one-click **confirm** and the training-group **merge** now emit `AuditEvent`s (`BILLING_RECORD_CONFIRMED` / `TRAINING_GROUPS_MERGED`; merge metadata carries merged ids/names + reparented count) — migration `core/0004`. Spec/plan: `docs/superpowers/{specs,plans}/2026-06-16-p7-audit-confirm-merge*`.
- **LAN acceptance signed off 2026-06-19** — verified on dev: the unified **Vecāki** admin (merged guardians correct, email/phone/is_active edit routes via `change_parent_email`), the fixed menu order with "Parent accounts" gone, and all three billing-confirm paths (per-row list button, change-page button, status dropdown + Save) each emit a `billing_record_confirmed` audit; the group merge emits its audit. **Two live-found bugs fixed during the pass:** (1) the one-click confirm/quick-action buttons were `<form>`s nested inside the admin's changelist/change form (invalid HTML → browser drops them) — rebuilt as bare `<button formaction=… formmethod="post">` riding the surrounding admin form's CSRF (commit `b1d27aa`); (2) a list-triggered agreement quick-action now returns to the list via a validated `next` (commit `7b3311c`).
- **Explicitly out of P7 (not done by design):** account-without-guardian admin visibility (a `ParentAccount` with no `Guardian` is reachable by direct URL only, not the menu); parent self-service email change with OTP re-verification (deferred from P6).

### Business workflow gaps
- agreement generation / manual-signing flow not implemented yet (P5 target)
- billing / Invoice Ninja sync not implemented yet (P6 target)
- admin **CSV export delivered (P7 Slice B, 2026-06-13)** — staff-only audited member + registration CSV export (safe default + superuser-gated sensitive; UTF-8 BOM + `;` for Latvian Excel; formula-injection guard).
- admin **review consolidation delivered (P7 Slice C-i, 2026-06-14)** — the registration review+edit flow now lives on the Django admin change page (panels + agreement/training-group modules + a top action bar), with status-aware one-click quick actions on the changelist; the bespoke custom review queue/detail views, URLs, and templates were removed. **Remaining = P7 Slice C-ii** (admin flow polish). **Batch 1 delivered (2026-06-14)** — the three user-prioritised items: (a) Registrations app now at the **top** of the admin left-side menu (`FkAdminSite` via `AdminConfig.default_site`); (b) **agreement-status column** ("Līguma statuss") on the applications changelist; (c) **one-click confirm** of a billing record — top button on the BillingRecord change page + per-row POST button on the billing-records list (replacing the open→dropdown→save dance). Gate: 1252 passed, ruff + mypy clean, no migrations. Spec/plan: `docs/superpowers/{specs,plans}/2026-06-14-p7-cii-admin-quick-wins*`. **Broader C-ii (batch 2)** specced as three plans (`docs/superpowers/{specs,plans}/2026-06-15-p7-cii-batch2*`). **Plan 1 (cross-links) delivered (2026-06-15)** — shared `apps/core/admin_links.py` helper; related-records rows on Member/Guardian/Agreement/BillingRecord change pages + the registrations review block; clickable member column on applications + guardian/agreement columns on billing. Gate: 1267 passed, no migrations. **Plan 2 (visibility) delivered (2026-06-15)** — shared `status_badge` helper + `fk_badges.css`; sync-health badges + filters on billing/agreements (Latvian error tooltips); search/filter/date-drill polish across Document/TrainingGroup/MembershipPlan/Application/Agreement/Billing admins; document active-vs-replaced badge + filter. Gate: 1292 passed, no migrations. **Plan 3 (training-group de-duplication) delivered (2026-06-15)** — case-insensitive unique `TrainingGroup.name` (migration `members/0005`) + `clean()` Latvian form error; `merge_training_groups` admin action (confirmation page → reparent members → bulk-delete spares; gated on delete permission, target validated in-selection) + name search. Gate: 1301 passed. **P7 Slice C-ii is COMPLETE** (batch 1 + batch 2 Plans 1–3); with C-i, **all of P7 Slice C is delivered.**

### Billing gaps (P6 follow-ups, deferred during Slice C live validation 2026-06-09)
- **Invoice issue/send policy** — **delivered (2026-06-12).** Decision: *scheduled per-installment send*. Push still creates invoices as Draft; a nightly `send_due_invoices` job issues + emails each installment on/after the 1st of its due month (IN bulk `email` action flips Draft→Sent). Gated by `BILLING_AUTOSEND_ENABLED` (**default off** — set true in prod to activate). `BillingInvoice.sent_at` added; daily `billing-send-due-invoices` Schedule registered; per-row error isolation; no-email guardians skipped+logged. **LAN acceptance signed off 2026-06-12** (real IN `in.mplytics.eu`: push→Draft, flag-off no-op, due installment→Sent + parent emailed, idempotent, no-email skip — all pass; test data cleaned up). Before prod activation, disable IN's admin "Invoice Sent" notification, then set `BILLING_AUTOSEND_ENABLED=true`. Spec/plan under `docs/superpowers/`.

### Data integrity gaps
- **Guardian dedup by email** — **fully landed (Slices A + B1 + B2 + C, 2026-06-10/11).** `Guardian` is 1:1 with `ParentAccount` (Slice A); read-through accessors read `Guardian`/`ParentAccount` only (Slice B1 + B2); the five `guardian_*` columns are dropped (Slice B2, migration `registrations/0010`); locked-profile UX (returning parents see guardian fields read-only + "Rediģēt vecāka datus" unlock toggle) and admin-initiated email change (`change_parent_email` service with uniqueness + `Guardian.email` mirror; `ParentAccount` registered in admin) landed in Slice C (**LAN acceptance signed off 2026-06-11** — lock/unlock, propagation, first-registration-unlocked, admin email change + uniqueness all pass). Parent self-service email change (with OTP re-verification of the new address) remains **deferred**. **Consolidation Plan 1 delivered (2026-06-15)** — the `Guardian.email`/`phone` columns (and the email mirror) are **removed**; they are now read-only `@property` proxies of the linked `ParentAccount` (single source of truth), and `Guardian.parent_account` is **NOT NULL** (migrations `members/0006` data link+merge of orphan/duplicate guardians, `members/0007` schema). Spec/plans: `docs/superpowers/{specs,plans}/2026-06-15-guardian-*`. Gate: 1316 passed. **Plan 2 (unified admin) delivered (2026-06-15)** — single "Vecāki" admin entry (`GuardianAdminForm` edits account email/phone/is_active; email via `change_parent_email`; add disabled; relabel, migration `members/0008`); `ParentAccount` filtered out of the admin menu (still registered); `ParentAccountAdmin` slimmed; redundant "Vecāka konts" cross-link dropped. Gate: 1321 passed. **Guardian/ParentAccount double-bookkeeping fully resolved** (single contact source-of-truth + enforced 1:1 + one admin entry).

---

## 5. Priority order for future development

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
- Slice A delivered 2026-05-27 — admin review uses Django admin shell (`admin/base_site.html`), thumbnail grid per document kind opens a `<dialog>` lightbox on click, member portrait surfaced, active vs replaced docs distinguished via `<details>` history with per-doc `preview_kind`; OCR readout uses Latvian-labeled `<dl>` + translated confidence chips; approval-ready inspection grouped on one screen. Covers acceptance items 1 + 2 (item 4 was already implemented pre-Slice A via `approved_member_id` early-return). Includes Revision A (admin styling pivot away from fk-* branding + thumbnail/lightbox UX) and Slice A.1 (templated review-action emails with application/portal URL). Manual LAN re-verification still pending.
- Slice B delivered 2026-05-28 — training-group assignment inline on the review detail page (during approval via a bundled dropdown; post-approval via a Treniņu grupa module with reassign/clear). New `assign_training_group` service. Approve email enriched with the assigned group name when assignment happens at approval time. Currently-assigned-but-inactive groups surface with a `(neaktīva)` marker so existing state is never hidden. No model changes. Item 3 closed.
- Slice C delivered 2026-05-29 — internal-only Agreement domain (new `apps/agreements/` app): `Agreement` model with `ForeignKey(Member)` + `is_current` flag and partial `UniqueConstraint` enforcing at most one current per member; state machine `generated → sent → signed` with `void` + regenerate-after-void; auto-created inside `approve_application` (now `@transaction.atomic`) honouring the application's `preferred_agreement_signing` (default `electronic`); admin Līgums module on the review-detail page with five POST transitions; parent portal + workspace render Latvian status copy via the `agreement_status_copy` helper; plain-text emails on `sent`, `signed`, and `void` (Slice D will suppress these for the electronic path); Django admin `VIEW ON SITE` link bridges from the read-only Agreement detail to the review-detail page; bidirectional sync invariant keeps `application.preferred_agreement_signing` and `agreement.signing_path` always-equal post-approval; backfill migration creates Agreements for approved Members from before Slice C. DocuSeal reservation fields (`external_*`) on the model stay empty until Slice D. Items 5, 7, 11 closed.
- Slice D delivered 2026-06-06 — DocuSeal self-hosted adapter + signed-state sync + manual signing tracking (items 6, 8, 9, 10). New `apps/integrations/agreement_platform.py` boundary (stub/docuseal dispatch on `AGREEMENT_PROVIDER_MODE`, exception taxonomy, frozen `SubmissionResult`) + concrete `apps/integrations/docuseal.py` provider (HTTP via `requests`, `X-Auth-Token`, status→exception mapping, HMAC-SHA256 webhook verify). django-q2 jobs create/sync/archive submissions with transient-retry vs terminal-fail classification (`external_state="failed"` + `external_error_code` → Latvian copy via `apps/agreements/messages.py`). Electronic path: optimistic `sent`, sent/signed guardian emails suppressed (DocuSeal notifies), enqueue create; empty guardian email degrades to paper; void enqueues archive. HMAC-verified `submission.completed` webhook (`integrations/docuseal/webhook/`, mounted before the registrations catch-all) drives `sent`/`generated` → `signed`; bad signature 403, all other cases ack 200. Līgums module surfaces the failed-state error + retry and a live-submission DocuSeal link + manual sync button. Migration `0003_agreement_external_error_code`. Closes P5.

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

**Status:** Slices A–C delivered (A 2026-06-07, B 2026-06-08, C 2026-06-08). Acceptance items 7, 8, 9 addressed and 1, 2 verified by Slice C. **Code complete + gates green (1113 passed); live-IN end-to-end validation (push + read-back) is the remaining P6 sign-off step.**
- Slice A delivered 2026-06-07 — local-only billing domain (new `apps/billing/` app): `MembershipPlan` (staff-editable plan config, one active row by convention) + `BillingRecord` (one per `(member, season)`, money snapshotted at creation, draft/confirmed + upfront/installments choices, manual override). Pure sibling-discount engine (`compute_billing_amounts`) derives the discount from the guardian's children (earliest-created full price, rest discounted; opt-out reuses `support_club_instead_of_multi_child_discount`) plus an installment-schedule helper. `agreement_signed` signal emitted from `mark_agreement_signed`; billing connects a receiver in `BillingConfig.ready()` that auto-creates a DRAFT `BillingRecord` on signing (idempotent; no-ops without an active plan). `recompute_billing_record` + admin plan/record surfaces with a `Pārrēķināt no plāna` action. New `preferred_payment_mode` registration field (`Maksājuma veids`). `backfill_billing` management command for pre-existing signed agreements. No Invoice Ninja calls — that is Slice B. Gate after Slice A: 1053 passed, ruff + mypy clean. **Manual LAN smoke confirmed + signed off 2026-06-07** (7/7 acceptance items: plan activation, signing→draft trigger, billing admin surface, recompute action draft-update + confirmed-skip, idempotent `backfill_billing`, parent `Maksājuma veids` render+persist; sibling discount + opt-out via the green discount-engine unit suite). Plan: `docs/superpowers/plans/2026-06-07-p6-slice-a-billing-domain.md`.
- Slice B delivered 2026-06-08 — admin-confirmed Invoice Ninja push (push-only; payment read-back is Slice C). New `apps/integrations/invoice_platform.py` boundary (stub/`invoiceninja` dispatch on `INVOICE_PROVIDER_MODE`, exception taxonomy, frozen result dataclasses) + `apps/integrations/invoice_ninja.py` provider (HTTP via `requests`, `X-Api-Token`, status→exception map incl. 429→transient, duplicate-invoice-number idempotency recovery). Mapping: Guardian→IN Client, MembershipPlan→IN Product (mirrored, referenced by derived `product_key`), each child's `BillingRecord`→its own invoice stream (no sibling consolidation), upfront=1 invoice / installments=one IN invoice per `derive_installment_schedule()` row, net per line with the sibling discount as a Latvian note. New `BillingInvoice` model (one row per installment) + `external_*` sync fields on `Guardian`/`MembershipPlan`/`BillingRecord`. `push_billing_record` django-q2 job (ensure product → ensure client → materialize → create invoices → roll up; deterministic `{PREFIX}-{record}-{seq}` numbers for idempotency; transient-retry vs terminal-fail with Latvian error copy). `BillingRecordAdmin` "Izrakstīt rēķinus (Invoice Ninja)" confirmed-only action. Gate after Slice B: 1080 passed, ruff + mypy clean. **Manual LAN smoke confirmed + signed off 2026-06-08** (stub provider mode + django-q worker): confirm→push→`synced` with 10 `BillingInvoice` rows, verified IN payload (number/product_key/Latvian label), idempotent re-push, draft skipped, and a testing refinement so already-`synced` records are reported separately rather than re-counted as pushed. Live-IN end-to-end deferred until an instance is provisioned. Plan: `docs/superpowers/plans/2026-06-07-p6-slice-b-invoice-ninja-push.md`.
- Slice C delivered 2026-06-08 — payment read-back + nightly scheduled sync + sync health (acceptance items 7, 8, 9; verifies 1, 2). `invoice_platform.fetch_invoice_payment` + provider `GET /invoices/{id}` with IN `status_id`→`payment_status` mapping (+ amount-derived fallback) and latest-payment-date extraction; payment-projection fields on `BillingInvoice`/`BillingRecord` (migration `billing/0004`, new `PaymentStatus` choices). `sync_billing_payments` nightly batch sweep (per-row error isolation) + `sync_billing_record_payments` manual per-record sync (terminal-error surface / transient re-raise), rolled up by `roll_up_payment_status`. Nightly django-q2 `Schedule` via idempotent data migration `billing/0005` + configurable `BILLING_PAYMENT_SYNC_HOUR`. Read-back terminal errors land on a dedicated `BillingRecord.payment_error_code` (migration `billing/0006`), separate from the push-side `external_error_code`. Admin: confirmed-only "Pārbaudīt maksājumus (Invoice Ninja)" action, payment columns/filter, read-only `BillingInvoiceInline`. Folded in the deferred Slice-B dedup hardening (`ensure_product` by `product_key`, `ensure_client` by `custom_value1=guardian.pk`) and an honest `backfill_billing` count. Gate: 1114 passed, ruff + mypy clean (240 files). Fixed a pre-existing TZ gap (no `TIME_ZONE`/`USE_TZ` was set → Django default America/Chicago): now `TIME_ZONE="Europe/Riga"` + `USE_TZ=True`, so the nightly hour is interpreted in local time. **Live-validated against a real Invoice Ninja instance (2026-06-09):** push (product/client/invoice create + dedup + dup-number recovery) and read-back (paid/partial/date mapping) both confirmed end-to-end through the django-q worker. **Six stub-hidden bugs found + fixed live:** (1) missing `X-Requested-With`/`Accept` headers (IN returned 200+HTML on errors); (2) dup-number message text; (3) `?include=payments` for the payment date; (4) generic line note + invoice `public_notes` to stop product-note pollution; (5) client/product dedup trusting `rows[0]` from IN's ignored `?custom_value1=`/`?product_key=` filters → narrow with `?filter=` + exact-match client-side; (6) dedup reusing archived/soft-deleted rows → `?status=active` + skip `is_deleted`/`archived_at`. Test suite hardened to never hit live providers from `.env`. Gate: 1126 passed, ruff + mypy clean. **Follow-ups deferred:** invoices push as IN **Draft** (auto-issue vs. staff-send policy); guardian dedup-by-email (repeated registrations create separate guardians → separate clients + no sibling linkage). **Operational note:** wiping IN data requires clearing Django `external_*` ids; restart the `qcluster` worker after task-code changes (no hot-reload). Remaining P6 close-out: confirmation pass on the deployed cloud `:dev` artifact.
- Installment calendar + per-plan due day delivered 2026-06-09 (completes acceptance item 6) — `derive_installment_schedule` now skips configured break months (per-plan `skip_months`, default July + December) placing N real installments (Jan–Jun + Aug–Nov for a Jan start), each due on a per-plan `payment_due_day` (default 20, clamped to month length); migration `billing/0007`; go-forward only. Gate: 1123 passed. Plan: `docs/superpowers/plans/2026-06-09-p6-installment-calendar-due-day.md`. **Live-IN end-to-end validation (push + read-back) is the remaining P6 sign-off step** — the instance now exists. Plan: `docs/superpowers/plans/2026-06-08-p6-slice-c-payment-readback-sync-health.md`. Design: `docs/superpowers/specs/2026-06-08-p6-slice-c-payment-readback-sync-health-design.md`.
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

### P8 — Calendar + WhatsApp attendance integration
**Why last**
- explicitly future scope
- likely separate platform/integration boundary

**Target outcome**
- calendar integration, likely external platform such as Google Calendar
- automated WhatsApp attendance polling integration

---

## 6. Acceptance criteria by priority block

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

### P8 acceptance — Calendar + WhatsApp attendance integration
P8 is complete when all of the following are true:

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

---

## 7. Milestone map

### M1 — Security and foundation completion
Delivered:
- background-job baseline (django-q2, delivered in P3.5)
- OCR metadata security posture (delivered in P3)
Remaining focus:
- audit baseline

### M2 — Parent intake completion
Remaining focus:
- dual-document registration flow
- OCR-backed prefill
- parent-flow UX polish (step-gated wizard, auto-save, consent gate, camera capture, mobile-first workspace, Latvian copy normalization)

### M3 — Approval-to-membership and agreement completion
Remaining focus:
- inline document preview in review flow
- training-group assignment workflow
- agreement generation + manual signing tracking

### M4 — Billing completion
Remaining focus:
- Invoice Ninja orchestration
- sibling discount rules
- payment visibility and retry paths

### M5 — Admin operations completion
Remaining focus:
- export
- filters/search polish
- document/admin operations polish

### M6 — Production readiness

Delivered:
- two-channel deployment pipeline (2026-05-26): containerized stack (`Dockerfile`, `compose.yaml` — `web` + `qcluster` + `postgres` 18, non-root UID 10001, whitenoise static, `/healthz` probe, configurable host port). Branch strategy: `dev` → floating `:dev` (dev server auto-pulls); `main` → floating `:main` plus immutable `:<major>.<minor>` from the `VERSION` file (prod server auto-pulls `:main`, can pin to a `:<X.Y>` for rollback). Codeberg Woodpecker CI orchestrates lint → test → branch-specific build → HMAC-signed POST to per-channel server listener. All host-side services run as the unprivileged `fkmms` user (UID 10001 matches in-container `app`).
- deployment runbook: `docs/deployment.md`.

Remaining focus:
- prod environment / second host (same image, `:prod` floating tag, separate `.env`)
- recovery/backup notes (today: ad-hoc `pg_dump`; need scheduled job + off-host shipping)
- integration configuration docs (Invoice Ninja, SMTP provider choice)
- final security checklist (CSP, rate-limit, fail2ban, audit-log review)

### Future / post-MVP
- calendar integration
- WhatsApp attendance polling

---

## 8. Explicit non-priorities right now
- coach portal
- adult members
- attendance tracking inside this monolith
- event / competition / travel planning
- direct national FA integration
- multilingual architecture
- SPA or API-first rewrite

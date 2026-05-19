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

### Documents
- `Document` model exists
- private storage root `PRIVATE_DOCUMENTS_ROOT` / `private-uploads/` exists
- admin-only protected preview/download endpoints exist
- anonymous users redirect to admin login
- authenticated non-admin users receive `404`
- placeholder OCR status exists on documents

### Admin review and member creation
- admin review queue/detail baseline exists
- review actions exist: request fix, reject, approve
- approval creates `Guardian` and `Member`
- `TrainingGroup` model exists, but approval currently leaves assignment empty

---

## 3. Confirmed target direction not yet implemented

### Documents and OCR
- registration should handle both `guardian_identity` and `member_identity` documents
- existing verified guardian should reuse active guardian document by default, with optional refresh/replacement
- OCR should prefill person data from uploaded documents
- OCR should also store serialized sensitive metadata such as document number, issuer, issuance date, expiry, and similar fields
- OCR metadata must be protected with same posture as raw identity documents
- OCR mode must be configurable between real provider and stub/dummy provider
- preferred OCR direction: **tiny-IDP** (only provider)
- live sample-document validation required before implementation sign-off

### Agreement handling
- after approval, generate agreement
- first slice uses manual signing outside Django app
- agreement platform is source of truth for agreement artifact and signed state
- signed state sync comes back to Django through API
- preferred future richer agreement-processing direction: **DocuSeal self-hosted**

---

## 4. Open gaps and debt

### Security and architecture gaps
- audit/event baseline still incomplete
- OCR extracted metadata storage/security not implemented yet

### Registration UX gaps
- guardian/child-player field visual presentation needs polish (fields finalized in P1)
- unnecessary re-upload can replace earlier file and create confusing admin rows

### Admin UX gaps
- admin review should show inline identity-document previews beside applicant data
- admin document UX should better distinguish active vs replaced documents
- training-group assignment flow still incomplete
- review-action audit entries still incomplete

### Business workflow gaps
- agreement generation / manual-signing flow not implemented yet
- billing / Invoice Ninja sync not implemented yet
- admin export and operations polish still pending

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
**Status:** implemented in code, live validation pending final sign-off

**Provider decision (2026-05-15):**
- Provider: **tiny-IDP** (only provider)
- Open risks: no Latvian-specific accuracy data; tiny-IDP post-incident operational resilience unverified; pricing not publicly documented; legal review of DPA still needed; live benchmark required before implementation sign-off
- Live sample-document validation still required before implementation sign-off

**Why third**
- depends on final field model and stable registration flow
- introduces real extraction and sensitive metadata handling

**Delivered code outcome**
- stub/real OCR provider boundary exists in `apps/integrations/ocr.py`
- identity uploads for `guardian_identity` and `member_identity` trigger synchronous OCR in draft flow
- `member_portrait` stays outside OCR scope
- OCR success persists encrypted payload and encrypted summary in `DocumentExtraction`
- `/applications/new/` reuses active guardian identity document by default and merges prior OCR extraction into parent prefill
- parent workspace shows OCR source markers and decrypted OCR summaries
- admin review detail shows separate guardian/member preview sections, decrypted OCR summaries, and confidence values when provider returns them
- non-blocking OCR failure path is covered in tests

**Verification evidence**
- full suite green: `584 passed`
- lint green: `uv run ruff check .`
- types green: `uv run mypy .`

**Remaining sign-off work**
- run live tiny-IDP sample-document validation and record evidence before calling P3 complete

### P4 — Approval-to-agreement flow
**Why fourth**
- agreement is business basis for billing
- admin review quality should improve before agreement decisions
- simpler first slice avoids premature in-app e-sign orchestration

**Target outcome**
- inline admin document preview in approval flow
- training-group assignment workflow
- generate agreement after approval
- track agreement state from external agreement platform

### P5 — Billing / Invoice Ninja sync
**Why fifth**
- should follow agreement flow in business sequence

**Target outcome**
- membership plan rules
- sibling discount
- automatic billing trigger after agreement platform `completed` state
- Invoice Ninja sync and payment-status visibility

### P6 — Admin operations / export / audit polish
**Why sixth**
- builds on earlier workflow completion
- improves day-to-day operations and controls

**Target outcome**
- CSV export
- search/filter polish
- audit completion
- document/admin UX polish

### P7 — Calendar + WhatsApp attendance integration
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
**Status:** implemented in code; live validation still pending

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

### P4 acceptance — Approval-to-agreement flow
P4 is complete when all of the following are true:

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

### P5 acceptance — Billing / Invoice Ninja sync
P5 is complete when all of the following are true:

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

### P6 acceptance — Admin operations / export / audit polish
P6 is complete when all of the following are true:

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

### P7 acceptance — Calendar + WhatsApp attendance integration
P7 is complete when all of the following are true:

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
Remaining focus:
- background-job baseline where still missing
- audit baseline
- OCR metadata security posture

### M2 — Parent intake completion
Remaining focus:
- dual-document registration flow
- OCR-backed prefill

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
Remaining focus:
- deployment docs
- recovery/backup notes
- integration configuration docs
- final security checklist

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

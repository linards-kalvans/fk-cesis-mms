# P2 Design — Parent Visual System and Registration UX Redesign

**Date:** 2026-05-11  
**Status:** Drafted for user review  
**Scope:** P2 planning for parent-facing visual system, registration UX redesign, document state clarity, and OCR review presentation.

---

## 1. Purpose

P1 made verified parent access and registration continuation secure, but the parent experience is still visually fragmented and operationally unclear in several places. P2 should create one cohesive FK Cēsis parent-facing visual system and apply it across registration entry, verification, portal, and application pages.

This milestone is meant to improve clarity, confidence, and maintainability without expanding into OCR provider work, agreement flow, billing, or admin redesign.

---

## 2. Confirmed scope

### In scope
- redesign all parent-facing pages using one shared visual system
- use `style-guide/fk_cesis_responsive_registration.html` as the main source pattern for registration-oriented pages
- use `style-guide/fk_cesis_list.html` as the main source pattern for portal/listing pages
- use canonical tokens from `style-guide/tokens.md`
- support route reshaping where it improves UX
- allow small backend or form-contract changes when needed to support cleaner UX
- make uploaded document state clear to parent users
- make OCR-prefilled vs user-entered values clear to parent users
- improve validation and form comprehension
- preserve current verified-parent security and ownership model

### Out of scope
- admin or staff visual redesign
- OCR provider integration or OCR job orchestration changes
- agreement generation or agreement platform work
- billing or Invoice Ninja work
- major business-model expansion unrelated to parent UX
- brittle pixel-perfect reproduction of static HTML files

---

## 3. Design goals

1. **Cohesion** — parent-facing screens should feel like one product, not separate pages.
2. **Clarity** — each page should make next action obvious.
3. **Trust** — secure identity/document flow should feel understandable and intentional.
4. **Maintainability** — templates should be built from shared primitives, not page-by-page one-off copies.
5. **Safety** — verified access and ownership protections from P1 must remain unchanged.

---

## 4. Recommended approach

Use a **shared parent shell plus route polish** approach.

This means:
- build reusable parent-facing template primitives in Django
- preserve current workflow/security rules
- allow route consolidation or reshaping only where it improves user understanding
- keep backend changes small and UX-driven

### Why this approach
- it fits both source HTML files well
- it gives enough flexibility to improve flow without risky domain churn
- it allows document and OCR review UX to become first-class parts of the experience
- it keeps future design iteration practical because reusable primitives can be refined without rewriting view logic

---

## 5. Parent UX architecture

All parent-facing pages should use one shared design system.

### Shared parent shell
The shell should provide:
- branded FK Cēsis header
- consistent page width and spacing rules
- optional hero/introduction block when useful
- reusable cards and action rows
- shared alert/callout patterns
- shared status badge patterns

### Core reusable primitives
#### Layout primitives
- parent shell
- hero card
- section card
- summary card
- action card
- empty-state block

#### Form primitives
- labeled field wrapper
- hint/help text
- inline field error
- top-level error summary
- grouped form rows
- action button row

#### Status primitives
- workflow badge for `draft`, `submitted`, `fix_requested`, `approved`, `rejected`
- info, success, and warning banners
- guidance blocks for “what happens next”

#### Document primitives
- document card per document role
- active document state label
- replacement guidance text
- uploaded file metadata row
- replace control presentation

#### OCR primitives
- source badges or source hints such as `extracted`, `entered`, `verified`
- field-level explanatory copy for editable extracted values
- grouped notes where OCR-derived values require review

---

## 6. Page model and route design

### Proposed page flow

```text
/register/
  -> guardian email entry
  -> /register/verify/

/register/verify/
  -> one-time code verification
  -> /portal/

/portal/
  -> continue active draft if present
  -> start new registration
  -> application history list

/applications/<id>/
  -> unified application workspace
     - editable for draft/fix_requested
     - read-focused for submitted/approved/rejected
```

### Route reshaping rules
Allowed:
- consolidate create/edit/detail behavior into a unified application workspace if that produces a clearer parent experience
- keep compatibility redirects from older routes where appropriate
- rename headings and page framing to better match the new UX
- restructure navigation between register, verify, portal, and application pages

Not allowed:
- exposing registrations before verified access
- weakening verified-parent gating
- weakening ownership checks
- changing editable-state rules outside existing `draft` and `fix_requested` behavior without separate planning

### Why unified application workspace
A single application workspace matches the registration HTML pattern better than fragmented create/edit/detail pages. It reduces mental overhead and makes status-based adaptation easier:
- editable view when application can still be worked on
- read-focused summary when application is no longer editable

---

## 7. Page-by-page behavior

### 7.1 `/register/` — guardian email entry
Purpose: secure, calm first step.

Behavior:
- strong branded intro
- short explanation of secure parent verification
- single obvious email field/action
- clear explanation of what happens next
- rate-limit and error states shown in same system

Success standard:
- user understands this is step one of a secure process
- next step after submission is easy to predict

### 7.2 `/register/verify/` — code verification
Purpose: explain email verification clearly and reduce confusion.

Behavior:
- show which email is being verified
- explain that verification unlocks that guardian’s registrations
- centered simple code form
- clear resend/help/error states
- success leads to portal/dashboard

Success standard:
- page makes purpose of code entry obvious
- user understands verification is tied to secure access

### 7.3 `/portal/` — chooser and registration history
Purpose: combine dashboard, next-step chooser, and registration list.

Behavior:
- top summary area with primary next action
- if active draft exists, `continue application` is primary CTA
- `start new registration` always visible
- registrations list below using `fk_cesis_list.html` patterns
- statuses readable and next actions obvious

Success standard:
- parent can immediately tell whether they should continue, review history, or start a new registration

### 7.4 `/applications/<id>/` — unified application workspace
Purpose: one place for create, edit, review, and status understanding.

Behavior:
- top header with application/member context and status
- grouped sections:
  1. guardian information
  2. player information
  3. documents
  4. review before submit / status summary
- editable states keep explicit `save draft` and `submit application` actions
- non-editable states become read-focused and status-oriented

Success standard:
- parent can understand where to work, what is missing, and what state the application is in

---

## 8. Document UX design

P2 must fix parent confusion around already-uploaded documents.

### Required parent-visible behavior
For each document role shown in parent flow:
- clearly show whether an active document already exists
- distinguish guardian and member documents clearly
- show filename or equivalent upload state summary
- explain that uploading a new file replaces the currently active one
- present replace action consistently

### Scope note
This milestone improves parent-facing clarity only. It does not redesign admin document handling or change OCR provider integration.

### Why this matters
Current behavior allows unnecessary re-uploading because users do not realize a document is already present. P2 should make existing state visible and replacement understandable.

---

## 9. OCR review UX design

P2 does not implement OCR provider work. It improves how OCR-derived values are presented in parent-facing forms.

### Required behavior
- when a value is OCR-prefilled, that should be visible to the user
- user should be able to correct OCR-prefilled values directly in normal form fields
- extracted vs manually entered values should be distinguishable
- guidance should stay lightweight; no separate OCR review wizard is needed in P2

### Presentation rule
Use subtle, comprehensible source indicators rather than complex workflow semantics. The message should be:
- this value was prefilled from document extraction
- please review it
- you may correct it before submission

### Security note
Sensitive OCR metadata remains protected under existing sensitive-data posture. P2 should only reveal source/review cues where appropriate in parent flow.

---

## 10. Validation UX design

Validation should be improved without changing business rules.

### Required behavior
- inline errors next to relevant fields
- top-level error summary on invalid submit where useful
- clearer grouping of fields by section
- action labels remain explicit: `save draft`, `submit application`

### Goal
Invalid submission should feel understandable rather than abrupt or confusing.

---

## 11. Backend impact boundaries

P2 should keep domain/business layers mostly stable.

### Allowed backend changes
- adjust parent-facing views for new page composition
- add template/context helpers for portal CTA selection, grouped rendering, document state, and OCR source markers
- make small form changes to support grouped rendering, better help text, and replacement messaging
- add compatibility redirects if routes are reshaped

### Avoid unless clearly required
- new business states
- major schema churn
- admin-only data model work unrelated to parent UX
- integration-layer expansion

### Why this boundary exists
P2 is a UX-system milestone, not a workflow or integration milestone. Backend work should serve clarity, not expand scope.

---

## 12. Test strategy for implementation

Tests for P2 should verify behavior and state, not visual pixel details.

### Must test
- verified entry still gates parent access correctly
- portal still prioritizes resumable draft when present
- start-new registration action remains available
- unified application workspace respects ownership checks
- editable vs non-editable states still map correctly to application status
- document cards reflect active upload state correctly from backend data
- replacement flow preserves intended active/replaced semantics
- OCR source markers appear when extracted values exist
- invalid submit still shows expected error handling behavior
- route reshaping or redirects still land parent in correct destination
- no insecure ownership regression

### Do not test
- exact CSS classes unless they encode behavior
- exact spacing, typography metrics, or visual decoration
- hero copy art direction beyond meaningful text behavior

---

## 13. Acceptance criteria

P2 is complete when all of the following are true:

1. Parent-facing pages visibly follow FK Cēsis visual system and canonical tokens.
2. Registration entry, verification, portal, and application pages feel cohesive.
3. Portal clearly shows primary next action and registration history.
4. Application workspace groups guardian, player, document, and review/status concerns coherently.
5. Parent can see whether active uploaded documents already exist.
6. Replace action for documents is understandable.
7. OCR-prefilled values are understandable and editable.
8. Validation and error presentation are clearer than current baseline.
9. Verified-parent and ownership protections from P1 remain intact.
10. Tests prove no key workflow or security regression.
11. Implementation uses shared Django template primitives so later designer refinement stays practical.

---

## 14. Non-goals and future handoff

### Explicit non-goals for P2
- real OCR provider integration
- OCR retry/admin controls expansion
- agreement generation or signature tracking
- billing automation or Invoice Ninja sync
- admin review redesign

### Future milestone relationship
- P3 can build on P2’s clearer document and field presentation to add real OCR integration
- P4 can later improve admin review and agreement flow on top of the stabilized parent UX

---

## 15. Recommended implementation direction for planning phase

Implementation planning should assume:
- one shared parent template system
- portal/list patterns derived from `fk_cesis_list.html`
- registration/workspace patterns derived from `fk_cesis_responsive_registration.html`
- route simplification is allowed where it reduces parent confusion
- backend changes must remain subordinate to UX goals and P1 security constraints

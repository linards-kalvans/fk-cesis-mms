# P1 Design Spec — Field Contract and Verified Registration Gate

**Date:** 2026-05-08  
**Status:** Implemented  
**Scope:** P1 only — field-set finalization and guardian-email-first verified registration gate.

---

## 1. Purpose

P1 closes the biggest confirmed security and workflow gap in the current MVP:

- typed guardian email must no longer act as proof of ownership
- registration continuation and parent portal access must require verified identity
- guardian and member field contracts must be finalized before later UX, OCR, agreement, and billing work

This design defines the final P1 field list, verification flow, route gating rules, data model direction, and test expectations.

---

## 2. In scope

P1 includes:

1. Finalize guardian, member, and application field sets
2. Define required/optional behavior for submit and draft save
3. Replace anonymous draft continuation with guardian-email-first verified entry
4. Use one-time email code as the only P1 verification method
5. Create an existing-guardian chooser/dashboard after verification
6. Create new `ParentAccount` immediately after successful verification for new guardians
7. Protect registration continuation and parent portal behind the same verified session
8. Introduce minimal model support needed for finalized fields:
   - document kinds for guardian identity, member identity, member portrait
   - admin-managed kit size options
   - application snapshot fields
9. Provide explicit source mapping classification for each field
10. Add tests for field contract, verified gate, chooser behavior, and security regressions

---

## 3. Out of scope

P1 does **not** include:

- visual redesign beyond minimal functional pages
- broader OCR workflow implementation beyond source mapping and future extension hooks
- rich existing-document reuse UX
- admin workflow expansion beyond what P1 model and flow changes require
- agreement generation/sync behavior
- billing execution, sibling discount engine, or Invoice Ninja orchestration

---

## 4. Design decisions

### 4.1 Field-contract-first approach

P1 will be implemented field-contract-first rather than flow-first.

**Why:**
- field definitions drive form structure, validation, snapshot storage, OCR mapping, member creation, and later billing inputs
- this reduces churn when implementing verified entry and future UX redesign
- milestone guidance already states that field contract should drive later flow work

### 4.2 One-time code only

P1 verification will use **one-time email code only**.

**Why:**
- milestone acceptance explicitly says email code is the primary entry verification method
- single mode keeps P1 smaller and clearer than supporting both code and magic link
- this avoids splitting tests and UX around dual verification modes

### 4.3 Verified identity before any continuation

A guardian must complete code verification before they can:
- continue a registration draft
- see their registration list
- access chooser/dashboard
- access parent portal routes

**Why:**
- typed email is a claim, not proof of account ownership
- this removes current insecure same-browser anonymous continuation behavior

### 4.4 Existing guardian gets chooser page

After verification, an existing guardian lands on a single chooser/dashboard page.

**Why:**
- P1 acceptance requires continue-draft priority, start-new option visibility, and registrations list visibility on the same screen
- this keeps next actions explicit and testable

### 4.5 New guardian account created immediately after verification

For a new guardian email, successful code verification immediately creates the verified `ParentAccount` and signs the guardian into a verified session before registration starts.

**Why:**
- it makes verified identity the system anchor from the first post-verification step
- it avoids temporary half-owned drafts that later need reassignment
- it simplifies route gating and guardian-field prefill behavior

### 4.6 Drafts may be incomplete after verified entry

After successful verified entry, draft save may persist incomplete values for all P1 fields.

**Why:**
- secure access is already established at that point
- registration is likely to span multiple document gathering steps
- this preserves MVP draft behavior while fixing insecure access path

---

## 5. Final P1 field contract

## 5.1 Guardian fields

All guardian fields are required for submission.

| Field | Required on submit | Draft may be blank | Source class | Notes |
|---|---|---:|---|---|
| Guardian ID document photo | yes | yes | manual-only | uploaded document; later OCR may read from it |
| Guardian full name | yes | yes | guardian OCR / manual-only | parent-editable |
| Guardian personal ID | yes | yes | guardian OCR / manual-only | parent-editable |
| Guardian declared address | yes | yes | guardian OCR / manual-only | parent-editable |
| Guardian email | yes | yes | derived/system-filled | comes from verified account/session; not trusted from anonymous input |
| Guardian phone | yes | yes | manual-only | parent-editable |

## 5.2 Member fields

All member fields are required for submission.

| Field | Required on submit | Draft may be blank | Source class | Notes |
|---|---|---:|---|---|
| Member ID document photo | yes | yes | manual-only | uploaded document; later OCR may read from it |
| Member full name | yes | yes | member OCR / manual-only | parent-editable |
| Member personal ID | yes | yes | member OCR / manual-only | parent-editable |
| Member date of birth | yes | yes | member OCR / manual-only | parent-editable |
| Member actual address | yes | yes | derived/system-filled / manual-only | copied from guardian address when same-address toggle enabled |
| Member same as guardian declared address | yes | yes | manual-only | boolean toggle stored separately |
| Member kit size — shirt | yes | yes | manual-only | dropdown from admin-managed options |
| Member kit size — shorts | yes | yes | manual-only | dropdown from admin-managed options |
| Member portrait photo | yes | yes | manual-only | separate from identity document |

## 5.3 Application fields

| Field | Required on submit | Draft may be blank | Source class | Notes |
|---|---|---:|---|---|
| Preferred way to sign agreement | yes | yes | manual-only | enum: `paper`, `electronic` |
| Do not apply discount in order to support club | conditional | yes | derived condition + manual answer | shown and required only for 2nd / 3rd / later child application |

### 5.4 Submit-time rules

1. Every listed guardian, member, and unconditional application field is required at submit time.
2. The application discount-support field is required when the application qualifies as 2nd or later child for the guardian.
3. No P1 submit-time fields are optional.

### 5.5 Draft-save rules

1. After verified entry, draft save accepts incomplete values for all P1 fields.
2. Validation for requiredness is enforced on submit, not draft save.

---

## 6. Address behavior

Member actual address supports a same-address toggle.

### Rule
When the guardian selects **same as guardian declared address**:
- store the boolean toggle on the application
- copy the guardian declared address into the member actual address snapshot
- disable direct editing of the member actual address field while the toggle remains enabled

### Why store both toggle and copied snapshot
- preserves a clear historical snapshot of what was submitted
- avoids ambiguity if guardian address changes later
- keeps member address independently queryable in application snapshot data

---

## 7. Verification and routing flow

## 7.1 Entry flow

```text
/register/
  -> guardian enters email
  -> system sends one-time code
  -> guardian submits code
  -> if code valid:
       -> create verified session
       -> existing ParentAccount? yes -> chooser/dashboard
       -> existing ParentAccount? no  -> create ParentAccount -> start registration
```

## 7.2 Core verification rules

1. Registration starts with guardian email only.
2. Typed email alone grants no access to registrations, drafts, or portal data.
3. One-time code is the only P1 entry verification method.
4. Code must be:
   - single-use
   - short-lived
   - rate-limited on send and verify paths
5. Successful verification establishes a verified session used by both registration flow and parent portal.

## 7.3 Existing guardian path

After successful code verification for an existing guardian account:

- land on a single chooser/dashboard page
- if at least one draft exists:
  - **continue draft** is primary action
  - **start new registration** is secondary action
  - registration list is visible on same page
- if no draft exists:
  - **start new registration** is primary action
  - registration list is still visible on same page

## 7.4 New guardian path

After successful code verification for a new guardian email:

- create `ParentAccount` immediately
- establish verified session immediately
- route directly into new registration creation flow

## 7.5 Prefill rules

For an existing guardian starting a new registration:
- prefill guardian fields only
- do not prefill member fields from earlier children in P1
- do not offer member-template reuse in P1

---

## 8. Data model direction

## 8.1 `ParentAccount`

`ParentAccount` remains the verified identity anchor and reusable guardian profile source.

P1 should ensure it can store reusable guardian values needed for prefill:
- email
- full name
- personal ID
- declared address
- phone

## 8.2 `RegistrationApplication`

P1 should expand application snapshot fields to represent finalized field contract.

### Guardian snapshot
- guardian_full_name
- guardian_personal_id
- guardian_declared_address
- guardian_email
- guardian_phone

### Member snapshot
- member_full_name
- member_personal_id
- member_birth_date
- member_actual_address
- member_same_address_as_guardian
- member_kit_size_shirt
- member_kit_size_shorts

### Application snapshot
- preferred_agreement_signing
- support_club_instead_of_multi_child_discount
  - required only when sibling-order condition says 2nd or later child

The exact internal field name may be implementation-specific, but business meaning must remain:
> “Do not apply discount in order to support club.”

## 8.3 `Document`

P1 requires stable document kinds at minimum:
- `guardian_identity`
- `member_identity`
- `member_portrait`

P1 also needs a minimal way to resolve the active/current document per kind so later document-reuse UX can build on it.

## 8.4 Kit size lookup

P1 requires an admin-managed lookup for kit sizes.

Recommended model direction:
- `KitSizeOption`
  - `kind`: `shirt` / `shorts`
  - `label`
  - `sort_order`
  - `active`

Application snapshot may store selected option references, copied labels, or both depending on implementation constraints, but user-facing values must remain stable for submitted applications.

---

## 9. Source-mapping rules

Every finalized field value must store one source classification from this enum:

- `guardian_ocr`
- `member_ocr`
- `manual_only`
- `derived_system_filled`

P1 does not need full OCR extraction yet, but the design must preserve room for later OCR-prefill behavior.

The table below lists the allowed source classification for each field value. Some fields may be filled from OCR in future flows or entered manually instead; the stored source on each saved value must still be exactly one enum value.

| Field | Allowed stored source |
|---|---|
| guardian email | `derived_system_filled` |
| guardian full name | `guardian_ocr` or `manual_only` |
| guardian personal ID | `guardian_ocr` or `manual_only` |
| guardian declared address | `guardian_ocr` or `manual_only` |
| guardian phone | `manual_only` |
| guardian document photo | `manual_only` |
| member full name | `member_ocr` or `manual_only` |
| member personal ID | `member_ocr` or `manual_only` |
| member date of birth | `member_ocr` or `manual_only` |
| member actual address | `derived_system_filled` or `manual_only` |
| member same-address toggle | `manual_only` |
| kit sizes | `manual_only` |
| member portrait photo | `manual_only` |
| preferred agreement signing | `manual_only` |
| support-club-instead-of-discount answer | `manual_only` |

The visibility condition for the support-club discount field is system-derived from sibling order, but the stored answer itself is a manual parent choice.

---

## 10. Security requirements

P1 is complete only if these security conditions hold:

1. Typed email can no longer reveal or auto-link another guardian’s registrations.
2. Anonymous same-browser draft continuation path is removed.
3. Verified session is required for draft continuation, chooser/dashboard, registration list, and parent portal routes.
4. Code verification for one guardian must never unlock another guardian’s data.
5. Rate limiting exists for verification-related endpoints.

---

## 11. Testing strategy

P1 test coverage must prove the approved behavior rather than only current implementation details.

## 11.1 Field-contract tests

Tests must verify:
- all guardian/member/application fields are required on submit
- conditional discount-support field is required only for 2nd+ child case
- verified draft save accepts incomplete values
- same-address toggle stores both toggle and copied address snapshot
- verified guardian email populates application/account consistently

## 11.2 Verification-gate tests

Tests must verify:
- email entry alone reveals no registration data
- send-code flow works for existing guardian
- send-code flow works for new guardian
- code is single-use
- expired code is rejected
- rate limiting is enforced
- verified session is required for chooser, draft continuation, and portal routes

## 11.3 Existing-guardian chooser tests

Tests must verify:
- with draft: continue-draft is primary, start-new is secondary, list visible
- without draft: start-new is primary, list visible
- starting a new registration prefills guardian fields only
- member fields are not prefilled from older registrations

## 11.4 Security regression tests

Tests must verify:
- one guardian cannot access another guardian’s draft/list by typing their email
- verifying one account’s code cannot expose another account’s records

---

## 12. Acceptance criteria

**Implementation status:** complete in current codebase. Full verification passed with `349 passed`, `ruff check .`, and `mypy .`.

P1 is accepted when all of the following are true:

1. Guardian, member, and application field contracts are finalized in code and tests.
2. Registration starts from guardian email only.
3. One-time code is the only P1 verification method.
4. Verified session is established before any registration continuation.
5. Existing guardian lands on chooser page with correct CTA priority.
6. New guardian account is created immediately after verification.
7. Registration continuation and portal routes share same verified gate.
8. Old insecure anonymous ownership path is removed.
9. Minimal document-kind support exists for guardian identity, member identity, and member portrait files.
10. Admin-managed kit size options exist.
11. P1 ships without visual-redesign, OCR-expansion, or unrelated admin-workflow scope creep.

---

## 13. Open implementation notes for planning phase

These are not open product decisions; they are implementation details to settle in planning:

- exact route structure for email entry, code verify, chooser, and registration create/continue
- whether code verification extends current auth tables or adds dedicated email-code model/service
- exact persistence shape for kit size snapshot vs FK reference
- exact sibling-order rule source for deciding when the support-club discount question appears
- whether guardian email field is rendered read-only or hidden on the registration form after verification

These details should be resolved in the implementation plan without changing the approved product behavior in this design.

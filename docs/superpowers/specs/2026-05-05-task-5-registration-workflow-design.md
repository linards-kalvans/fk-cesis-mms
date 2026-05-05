# Task 5 Registration Workflow Design

## 1. Goal

Deliver the first usable parent registration slice for FK Cēsis MMS.

At the end of this task, a parent should be able to:

- open the registration form without prior login
- start a registration immediately
- save an incomplete draft
- upload one required child identity document
- resume later through a magic link
- submit the application once required data is present
- view application status in a parent portal after submission

This design intentionally covers the parent-side registration workflow only. Admin review, member creation, billing setup, and real OCR integration remain outside this task.

## 2. Scope

### In scope

- server-rendered Django registration form flow
- hybrid entry flow: start first, account linked/created on first save or submit
- one `ParentAccount` owning multiple registration applications
- application draft save and later resume via magic link
- parent portal/status page
- one required private child ID/passport upload
- OCR placeholder status on uploaded document
- application status enum prepared for later admin workflow
- parent-side permission and ownership checks

### Out of scope

- real OCR provider integration
- admin request-fix, reject, approve actions
- member creation
- billing and Invoice Ninja sync
- multiple required document types
- public file delivery or final document audit views
- richer frontend application or SPA behavior

## 3. Requirements summary

### User-visible behavior

1. Parent can open the registration form without being logged in.
2. Parent can save a draft even when some form fields are incomplete.
3. First save or submit creates or links a `ParentAccount` using the submitted email.
4. Parent can request or use a magic link later to resume their own applications.
5. Parent can upload one required child identity document.
6. Parent can submit only when all required fields and the required document exist.
7. Submitted applications become read-only to the parent.
8. Parent can view their own application statuses in a portal page.
9. One parent account can have multiple applications for different children.

### Field set

Guardian fields:

- full name
- personal ID
- email
- phone
- address

Child fields:

- full name
- personal ID
- birth date

### Status model

The application model should include these statuses now:

- `draft`
- `submitted`
- `fix_requested`
- `approved`
- `rejected`

Task 5 only implements parent behavior for `draft` and `submitted`. Later tasks will use the remaining statuses.

## 4. Architecture recommendation

### Recommended option

Use a split domain design:

- `apps/registrations` owns application workflow, forms, service rules, and parent-facing views
- `apps/documents` owns the private uploaded document record

This is preferred over placing uploaded files directly on the registration model because it preserves a cleaner boundary for later secure download, audit, OCR, and deletion work.

### High-level flow

```text
Anonymous parent opens /register/
        |
        v
Parent fills form and optionally uploads document
        |
        +--> save draft
        |      |
        |      +--> create/link ParentAccount
        |      +--> create/update RegistrationApplication
        |      +--> create/update required Document
        |      \--> keep status = draft
        |
        \--> submit
               |
               +--> create/link ParentAccount
               +--> validate required fields
               +--> validate required document exists
               \--> set status = submitted

Later resume
magic link -> parent session -> portal -> continue draft or view status
```

## 5. Data model

### 5.1 `ParentAccount`

`ParentAccount` remains the account and resume identity layer, not the full legal source of truth for each application.

Current fields already support this role:

- `email`
- `phone`

The account will be used for:

- magic-link login/resume
- ownership of applications
- reusable prefill defaults for later applications

### 5.2 `RegistrationApplication`

`RegistrationApplication` stores the submitted guardian and child snapshot.

Recommended fields:

- `parent_account` → FK to `accounts.ParentAccount`
- `status`
- `guardian_full_name`
- `guardian_personal_id`
- `guardian_email`
- `guardian_phone`
- `guardian_address`
- `child_full_name`
- `child_personal_id`
- `child_birth_date`
- `submitted_at`

### Why guardian details stay on the application

Guardian submission data should stay on the application because:

- admin review needs a stable submitted snapshot
- changing account profile details later must not silently rewrite older submissions
- login identity and legal/billing identity are related but not guaranteed to stay identical

### 5.3 Prefill behavior

Prefill should be convenience-only, not shared mutable state.

When a parent starts a new application:

- if they already have a resumed account session, prefill from `ParentAccount.email` and `ParentAccount.phone`
- optionally prefill guardian fields from the parent account's most recent application

When a parent saves or submits:

- application snapshot fields update from current form input
- `ParentAccount.phone` may update from current form input
- `ParentAccount.email` remains the account key

### 5.4 `Document`

Task 5 needs a minimal private document record in `apps/documents`.

Recommended fields:

- `application` → FK to `registrations.RegistrationApplication`
- `kind` with fixed Task 5 value `child_identity`
- `file`
- `original_filename`
- `content_type`
- `file_size`
- `ocr_status`
- `uploaded_by_parent_at`
- `deleted_at` nullable

### OCR placeholder state

Task 5 does not call any OCR provider. It only stores placeholder state such as:

- `not_requested`
- `pending`
- `completed`
- `failed`

The exact enum may be narrowed during implementation, but it must clearly support later OCR orchestration without a schema rewrite.

### Relationship shape

```text
ParentAccount 1 --- * RegistrationApplication 1 --- * Document
```

Although Task 5 requires exactly one active `child_identity` document at submit time, the relationship should remain one-to-many to avoid a future schema rewrite.

## 6. Workflow rules

### Draft creation and saving

- parent can start without a session
- first save or submit creates or links the `ParentAccount`
- draft save allows incomplete business fields
- draft save may also create or replace the required document
- multiple applications may belong to the same parent account

### Resume behavior

- parent uses magic link to establish session
- portal shows only that parent's applications
- parent can reopen only their own draft applications

### Submission behavior

- submit allowed only from `draft`
- submit requires all required fields
- submit requires one active `child_identity` document
- submit sets `submitted_at`
- submit changes status to `submitted`

### Editability

- parent may edit only while status is `draft`
- once submitted, the application becomes read-only until a later admin-driven `fix_requested` flow is implemented

## 7. Routes and views

Recommended routes:

- `/register/` → start new registration
- `/applications/<id>/edit/` → edit draft only
- `/applications/<id>/submit/` → submit draft only
- `/portal/` → parent portal/status page

### View responsibilities

#### `start_registration`

- GET shows blank or prefilled form
- POST creates draft and optional required document upload
- creates or links `ParentAccount` on first save/submit

#### `edit_registration`

- owner-only access
- draft-only editability
- GET shows stored values
- POST updates snapshot fields and optionally replaces document

#### `submit_registration`

- POST only
- checks owner
- checks status is `draft`
- validates required data and document
- sets submitted state

#### `parent_portal`

- requires parent session
- lists current parent's applications only
- shows draft continuation or read-only submitted status

## 8. Forms and services

### Form

Create a `RegistrationApplicationForm` that includes guardian fields, child fields, and the required document upload field.

Validation should support two modes:

- draft save mode: tolerate incomplete business fields
- submit mode: enforce required fields and required document

### Service layer

Keep workflow rules out of views.

Recommended service functions:

- `get_application_prefill(account)`
- `create_or_update_draft(...)`
- `submit_application(application, actor_account)`
- `can_edit_application(application, actor_account)`

Service responsibilities include:

- creating or linking `ParentAccount`
- updating application snapshot fields
- syncing reusable account phone value
- creating or replacing the required document
- enforcing state and ownership rules

## 9. Security shape

- uploaded identity document must be stored in non-public storage
- no public file URL should be exposed
- Task 5 only needs upload and persistence; protected streaming views can follow in later work
- ownership checks must prevent one parent from viewing or editing another parent's application

## 10. Testing strategy

### Main test files

- `tests/registrations/test_application_workflow.py`
- `tests/registrations/test_parent_edit_permissions.py`

### Workflow tests

Cover:

- first draft save auto-creates or links `ParentAccount`
- second application can be created under same account
- draft save updates snapshot fields
- submit requires required document
- submit moves `draft -> submitted`
- submit sets `submitted_at`
- submitted app becomes non-editable
- non-owner cannot edit or submit
- prefill uses account or recent application values
- upload creates `Document` with OCR placeholder status

### View and permission tests

Cover:

- owner can open draft edit page
- owner cannot edit submitted application
- different parent cannot access another parent's application
- portal lists only current parent's applications
- start page works without existing session
- resumed parent can continue their own draft

### What not to test in Task 5

- exact HTML rendering details
- real OCR integration
- protected document download view
- admin review transitions
- billing or member creation

## 11. Acceptance criteria

Task 5 is complete when all of the following are true:

- parent can open registration form without prior login
- first save or submit auto-creates or links `ParentAccount`
- parent can save incomplete draft
- parent can resume through magic link and continue their own draft
- parent can upload one private child identity document
- parent can submit only when required fields and required document exist
- submitted application becomes read-only to parent
- parent portal shows only that parent's applications and statuses
- one parent account can own multiple applications
- OCR placeholder status is stored on the uploaded document
- targeted registration tests pass
- full `uv run pytest -q && uv run ruff check . && uv run mypy .` passes before completion

## 12. File plan

### Create

- `apps/registrations/models.py`
- `apps/registrations/forms.py`
- `apps/registrations/services.py`
- `apps/registrations/views.py`
- `apps/registrations/urls.py`
- `apps/registrations/migrations/0001_initial.py`
- `apps/documents/models.py`
- `apps/documents/migrations/0001_initial.py`
- `tests/registrations/test_application_workflow.py`
- `tests/registrations/test_parent_edit_permissions.py`
- `templates/registrations/start_registration.html`
- `templates/registrations/edit_registration.html`
- `templates/registrations/parent_portal.html`

### Modify

- `fk_cesis_mms/urls.py`
- `fk_cesis_mms/settings.py` if needed for local media/private upload handling
- account flow files only if resume redirect improvements are needed

## 13. Recommendation

Proceed with a clean split now:

- workflow in `apps/registrations`
- file record in `apps/documents`
- guardian details stored as application snapshot
- prefill from account and recent application only

This delivers the first real parent registration slice while keeping the security and workflow architecture aligned with later milestones.

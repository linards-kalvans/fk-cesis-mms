# FK Cēsis Member Management System — Product Specification

**Date:** 2026-05-08  
**Status:** Canonical product spec  
**Scope:** MVP product architecture, workflows, security policy, and approved design direction for FK Cēsis youth football club member management.

---

## 1. Purpose and goals

Build a Django-based MVP for FK Cēsis that lets parents register children online, lets staff review and approve those registrations, stores identity documents securely, creates official member records, and orchestrates recurring billing through Invoice Ninja.

**Primary outcomes**
- parents register a child online
- staff review applications and approve, reject, or request fixes
- approved applications become official member records
- training-group assignment is supported in member domain
- identity documents remain private and backend-protected
- membership billing is orchestrated through Invoice Ninja

**Product principles**
- Django monolith with PostgreSQL
- parent-facing pages are server-rendered, Latvian-only, lightly branded
- Django admin is primary staff shell
- business rules live in service layer, not views or admin glue
- external integrations run through background jobs with retry state
- third-party integrations must satisfy GDPR / EU compliance requirements
- self-hosted services are not assumed safer by default than SaaS; integrations stay loosely coupled through adapters and external config

---

## 2. Scope

### In scope (MVP)
- Latvian-only parent registration flow
- guardian-email-first registration entry with immediate account lookup
- verified parent registration flow through email verification gate
- admin review workflow: request fix, reject, approve
- member registry with `Member`, `Guardian`, and `TrainingGroup`
- secure identity-document handling and protected admin access
- OCR-assisted document extraction as non-blocking helper
- Invoice Ninja billing sync, sibling discount, billing start month, payment-status visibility
- search, filtering, and CSV export for admin operations
- audit trail for sensitive actions

### Out of scope
- coach portal
- adult members
- attendance tracking
- WhatsApp bot or WhatsApp notifications
- event / competition / travel planning
- direct national FA integration
- multilingual support
- SPA or API-first rewrite
- custom invoice workflows beyond membership-fee MVP

---

## 3. Users and roles

### Parent
- starts registration by entering guardian email
- receives magic link if account already exists, or verifies email before continuing if it does not
- reviews and confirms prefilled guardian and child/player data
- uploads guardian and child/player identity documents
- edits OCR-prefilled values before submission
- edits applications while status is `draft` or `fix_requested`
- views application status and review feedback

### Admin
- reviews submitted applications from Django admin
- previews and downloads private identity documents through protected backend endpoints
- requests fixes, rejects, or approves applications
- creates official member records through approval flow
- optionally assigns training group during or after approval
- monitors OCR and billing sync states
- exports data and reviews payment status

### System
- sends verification and workflow emails
- runs OCR extraction jobs
- runs Invoice Ninja sync jobs
- records audit events for sensitive actions

---

## 4. Architecture principles

### 4.1 Runtime shape
Use a Django monolith with PostgreSQL, private file storage, and background jobs.

### 4.2 Domain app boundaries
- `apps/core` — shared base models, enums, audit helpers
- `apps/accounts` — `ParentAccount`, verification and magic-link auth
- `apps/registrations` — registration workflow and parent/admin rules
- `apps/members` — `Member`, `Guardian`, `TrainingGroup`
- `apps/billing` — membership rules and Invoice Ninja sync state
- `apps/documents` — private documents and protected access helpers
- `apps/integrations` — OCR, email, Invoice Ninja adapters
- `apps/admin_ops` — export and admin operations tooling

### 4.3 Responsibility split
- parent-facing UX: Django templates + Django forms
- staff/admin UX: Django admin as primary shell, with small custom admin action views where explicit workflow handling is needed
- business rules: service-layer functions
- external APIs: adapter-based integration behind project-owned interfaces

### 4.4 Security architecture
- identity documents live under `PRIVATE_DOCUMENTS_ROOT` and are never public URLs
- every sensitive file access goes through authenticated Django views
- typed email is never treated as proof of ownership
- personal identifiers are masked in list/search views
- sensitive external payloads are redacted in logs and sync history

---

## 5. Domain model

### `ParentAccount`
Verified identity and parent portal account.
- `email` — unique verified account key
- `phone` — reusable contact/prefill value
- verification state derived from successful auth flow

`ParentAccount` represents verified ownership. Registration begins with guardian email lookup, but account ownership is recognized only after successful magic-link or equivalent verification.

### `MagicLinkToken`
Single-use, short-TTL token for parent verification or portal access.

### `RegistrationApplication`
Workflow record for intake and review.
- status: `draft`, `submitted`, `fix_requested`, `approved`, `rejected`
- `verified_parent` — FK to `ParentAccount`; registration flow continues only after verified email access
- guardian snapshot fields — finalized in P1
- child/player snapshot fields — finalized in P1
- review fields: `review_message`, `reviewed_by`, `reviewed_at`
- `submitted_at`
- `approved_member` — nullable one-to-one link to created `Member`

Guardian and child values stay on application as submitted snapshot so later account/profile changes do not rewrite historical intake data. Field sets finalized in P1.

### `Document`
Private uploaded identity document linked to application.
- `application`
- `kind` with MVP values `guardian_identity` and `member_identity`
- `file`, `original_filename`, `content_type`, `file_size`
- `ocr_status`: `not_requested`, `pending`, `completed`, `failed`
- `ocr_extracted_fields` — serialized sensitive OCR output, including identity-document metadata such as number, issuer, issuance date, expiry, and similar extracted fields
- `uploaded_by_parent_at`
- `deleted_at` for soft delete / replacement tracking

### `Guardian`
Legal and billing person linked to member.
- full name
- personal ID
- email
- phone
- address

### `Member`
Official approved club member created on approval.
- full name
- personal ID
- birth date
- guardian FK
- nullable training-group FK

### `TrainingGroup`
Admin-managed training group.
- name
- active state
- optional coach-name display field if needed later

### `MembershipPlan`
Per-member billing configuration.
- annual fee baseline
- payment mode: upfront or installments
- sibling discount applied / opted out
- billing start month

### `InvoiceProfile`
Invoice Ninja linkage.
- external customer/contact IDs
- sync health/status
- last sync timestamps

### `InvoiceSyncEvent`
Operational billing sync history with redacted metadata and retry state.

### `AuditEvent`
Structured history for approvals, rejections, document view/download/delete, billing sync actions, and other sensitive admin operations.

---

## 6. Parent identity and access model

System uses verified guardian email as front gate for registration and portal access.

| Layer | Purpose | Access condition |
|---|---|---|
| Email-entry gate | determine whether guardian already exists and where to route next | guardian email submitted |
| Verified parent layer | continue registration and access all registrations for that parent | successful email verification or future social-login equivalent |

### Core rules
1. Guardian email is checked immediately at registration start.
2. Existing guardian account: send magic link and continue registration only after it is used.
3. New guardian email: require verification before continuing registration.
4. Portal and registration continuation both depend on verified parent ownership.
5. Future social login may satisfy same verified-identity gate if it proves email ownership.

### Verification flow
1. Parent opens `/register/` and enters guardian email.
2. System checks whether verified guardian account already exists.
3. If account exists, system sends magic link and asks guardian to continue through it.
4. If account does not exist, system requires email verification before registration continues.
5. After verified access, system creates or links `ParentAccount`, prefills known guardian data where available, and opens registration flow.
6. Verified parent can see all registrations tied to that verified identity.

### Verification token policy
- single-use
- short TTL (target 15 minutes)
- revoked after use
- send endpoint rate-limited

---

## 7. Parent registration workflow

### 7.1 Registration entry
- registration starts with guardian email entry at `/register/`
- system immediately checks whether guardian email already exists
- existing guardian: send magic link and ask guardian to continue through verified link for prefill
- new guardian: require email verification before registration continues

### 7.2 Registration form
- after verified access, form opens with grouped guardian, child/player, and document sections
- guardian and child/player field sets are finalized in P1
- native browser date input may still be used for birth-date fields if retained in final field set
- visible field-level errors and top-level error summary
- single form with **save draft** and **submit application** actions

### 7.3 Document and OCR behavior
- guardian and child/player identity documents can be uploaded from registration flow
- OCR runs on both document types where uploaded
- OCR prefills person data and serialized document metadata for review and correction
- existing verified guardian may reuse active guardian document by default, with optional refresh / replacement
- child/player identity document remains required for new registration submission

### 7.4 Draft behavior
- draft save tolerates incomplete business fields after verified access is established
- draft save stores current application snapshot data
- documents can be uploaded or replaced while draft remains editable

### 7.5 Submission behavior
- submit allowed from `draft` and from `fix_requested`
- submit requires all required fields plus required active documents according to final field/document policy
- successful submit sets `submitted_at` and changes status to `submitted`
- submitted applications are read-only until reopened by staff through `fix_requested`

### 7.6 Parent portal
- portal available only after verified parent identity
- shows statuses and review feedback
- shows edit action only for `draft` and `fix_requested`
- lists only registrations belonging to verified parent

### 7.7 Fix-request loop
- `request fix` reopens application for parent editing
- parent can update same application and resubmit it
- resubmission clears prior review message/metadata and re-enters staff queue

---

## 8. Admin review and member creation workflow

### 8.1 Admin shell decision
Django admin is primary staff shell. Custom standalone review pages are superseded.

### 8.2 Review queue
Primary queue is Django admin changelist for `RegistrationApplication`.
- default queue contains `submitted` applications
- newest submitted first
- filters, search, ordering, badges, and linked related-object inspection use stock Django admin features first

### 8.3 Review detail
Admin change view acts as inspection screen.
It should emphasize:
- guardian and child summary
- status and timestamps
- verified parent / member linkage where applicable
- inline preview of active guardian and child/player identity documents beside rest of applicant data
- preview/download actions for protected files
- OCR-extracted person fields and document metadata when relevant
- explicit workflow actions rather than freeform editing

### 8.4 Review actions
- **Request fixes** — requires message, changes status to `fix_requested`, notifies parent, reopens application
- **Reject** — requires message, changes status to `rejected`, notifies parent, terminal state
- **Approve** — changes status to `approved`, creates exactly one `Guardian` and one `Member`, links `approved_member`, notifies parent

### 8.5 Approval rules
- approval must be idempotent
- member creation happens only once per application
- training group may remain empty initially, but approval UI may optionally allow assignment
- downstream billing and agreement flows may be triggered later through background jobs or follow-up actions

---

## 9. Document privacy and access policy

### 9.1 Storage policy
- registration identity documents live under private storage root `private-uploads/`
- private document storage remains separate from `MEDIA_ROOT`
- templates, admin pages, and code must not use direct public file URLs for registration documents
- future object-storage migration must preserve same authorization model
- serialized OCR output, including document number, issuer, issuance date, expiry, and similar extracted identity metadata, is sensitive data and must be stored with same security posture as underlying identity documents

### 9.2 Access policy
| Requester | Result |
|---|---|
| Anonymous user | redirect to admin login |
| Authenticated non-admin user | return `404` |
| Admin user | allow preview/download |

### 9.3 Endpoint policy
- preview and download share same permission gate
- preview uses `Content-Disposition: inline`
- download uses `Content-Disposition: attachment`
- soft-deleted or replaced documents are treated as unavailable for normal access

### 9.4 Admin UX rule
Admin review should prioritize active document and avoid confusing reviewers with replaced rows. Replaced documents should be hidden from normal review or clearly disabled/distinguished.

### 9.5 Audit rule
Document view, download, and delete actions are audited.

---

## 10. UI and design-system direction

### 10.1 Source of truth
`style-guide/` is canonical visual source of truth and supersedes `design-template.html` on conflict.

**Canonical tokens**
- display font: `Anton`
- FK Cēsis blue: `#0f0851`
- FK Cēsis red: `#ce1c20`

### 10.2 Parent-facing direction
- calm, centered, trustworthy tone
- full-width centered layout with max-width around 640px for forms
- club logo hero-style on parent entry screens
- single-column form stack
- minimal navigation
- grouped sections in cards/panels
- Anton reserved for brand / headings, not body text
- lightweight shared template partials for fields, errors, buttons, shell layout
- public copy remains Latvian-only

### 10.3 Admin direction
- denser admin shell
- Django admin remains primary UI foundation
- wider content area, table-first queues and lists
- filters, inline badges, and quick workflow actions
- custom code limited to native Django admin extension points where stock admin is insufficient

### 10.4 Email branding
Email templates should carry same lightweight brand direction, with logo/header treatment consistent with style guide.

---

## 11. Integrations

### 11.1 Invoice Ninja
Purpose:
- create/update customer and contact data
- create recurring invoice configuration
- sync invoice and payment status back into app

Principles:
- Invoice Ninja is source of truth for invoice objects and payment state
- app owns membership rules and synchronization, not a parallel ledger
- all integration work runs through background jobs with retry state
- external IDs stored explicitly
- failures visible and retryable by admin

### 11.2 OCR / document extraction
Purpose:
- speed data entry from uploaded guardian and child/player identity documents

Principles:
- background job only
- OCR failure never blocks registration
- extracted values remain editable by parent/admin
- provider-specific logic hidden behind adapter / protocol interface
- extracted data treated as sensitive PII
- extracted payload should include both person fields and document metadata such as number, issuer, issuance date, expiry, and similar fields when available
- current preferred service direction: **tiny-IDP** (only provider), provided it satisfies compliance, accuracy, and integration requirements
- provider choice is provisional pending live Latvian sample-document validation

### 11.3 Email delivery
Purpose:
- verification codes / links
- magic-link access
- workflow notifications
- later agreement delivery

Principles:
- provider-specific logic isolated behind delivery adapter
- debug preview adapter allowed only in development
- switching providers must not require domain-model rewrites

### 11.4 Agreement handling
Initial post-approval agreement scope is intentionally narrow.
Required direction:
- generate agreement after admin approval
- support manual signing outside platform, either by Latvian qualified electronic signature or on paper
- allow admin to mark agreement as signed
- optionally upload signed agreement copy into platform
- keep room for later configurable signing-order and countersign flow if richer agreement orchestration is introduced
- current preferred future platform direction: **DocuSeal self-hosted**, if later automated agreement processing is expanded and security/operations evaluation remains favorable

---

## 12. Billing rules

### Base pricing
- default annual fee: **€300**
- payment modes: upfront or 10 installments

### Installment months
- chargeable months: January–June, August–November
- no-fee months: July, December

### Billing start
- admin chooses start month per member

### Sibling discount
- second child gets **50% discount**
- parent may opt to pay full price instead
- discount detection uses guardian personal ID matching
- manual exception handling remains possible

### Manual discounts
Other discount handling may remain manual in Invoice Ninja for MVP.

---

## 13. Security and compliance baseline

### Sensitive data categories
- guardian personal IDs
- guardian identity documents
- child/player identity documents
- OCR-extracted identity data
- OCR-extracted document metadata such as document number, issuer, issuance date, expiry, and similar fields
- billing payer details

### Security rules
- HTTPS required in production
- secrets stored outside repo
- no sensitive PII in logs
- personal IDs masked in list/search views
- document access always backend-authorized
- verification tokens single-use, short-lived, and rate-limited
- sensitive admin and file actions audited

### GDPR / EU compliance rules
- mandatory for all third-party integrations
- EU data residency required where applicable
- GDPR Article 28 DPA required from vendors
- no vendor training on project data
- deletion/retention policies must cover extracted data and signed documents

---

## 14. Research and deferred items

### Active research tracks
1. **Agreement generation and signing module**
2. **SMTP / email provider strategy for scale**

### Resolved direction
- **ID document extraction:** tiny-IDP (only provider). Live Latvian sample validation still required before implementation sign-off.

### Deferred / follow-up product items
- training-group assignment workflow polish
- admin activity audit details for review actions
- clearer parent-side display of already uploaded identity documents
- clearer admin distinction between active vs replaced documents
- production email gateway integration
- optional social login as verified-identity path
- calendar integration, likely through separate platform such as Google Calendar
- automated WhatsApp attendance polling, likely as separate integration/platform boundary rather than core MVP module

---

## 15. Acceptance criteria for this spec

This spec is correct if implementation can produce:
- Latvian parent registration flow for minors
- guardian-email-first registration entry with required verified access before registration continues
- secure private document storage with admin-only backend preview/download
- guardian and child/player document upload with OCR-assisted non-blocking extraction flow
- storage and protection of extracted document metadata with same security posture as other identity data
- admin review workflow in Django admin with inline document preview plus request-fix / reject / approve actions
- one-time member creation on approval
- recurring membership billing setup in Invoice Ninja
- sibling discount behavior based on guardian identity matching
- payment-status visibility from Invoice Ninja sync
- lightweight FK Cēsis-branded parent UI and native Django admin-based staff UI
- auditability and GDPR-aware handling of sensitive data

---

## 16. Superseded decisions and replaced docs

### Superseded decisions
- custom staff review pages as primary workflow shell → superseded by Django admin as primary shell
- typed-email auto-linking as ownership proof → superseded by verified parent identity gate
- `design-template.html` as visual reference of record → superseded by `style-guide/`
- filename prefix or storage convention alone as document security boundary → superseded by private storage plus protected backend access only

### Spec files replaced by this canonical doc
- `docs/superpowers/specs/2026-05-04-fk-cesis-mms-mvp-design.md`
- `docs/superpowers/specs/2026-05-05-registration-design-and-integrations-design.md`
- `docs/superpowers/specs/2026-05-05-parent-identity-verification-design.md`
- `docs/superpowers/specs/2026-05-05-task-5-registration-workflow-design.md`
- `docs/superpowers/specs/2026-05-07-private-registration-document-access-design.md`
- `docs/superpowers/specs/2026-05-07-admin-review-and-member-creation-design.md`
- `docs/superpowers/specs/2026-05-08-native-django-ui-and-admin-design.md`

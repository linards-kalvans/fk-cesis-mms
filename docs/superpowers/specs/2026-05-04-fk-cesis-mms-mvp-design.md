# FK Cēsis MMS MVP Design

## 1. Goal
Build an MVP member registration and management system for FK Cēsis youth football club.

Primary outcome:
- parents register a child online
- admins review and approve applications
- approved members are tracked in the system
- admins assign each member to a training group
- membership billing is automated through Invoice Ninja

This MVP is intentionally focused on registration, member registry, secure document handling, and billing orchestration. Attendance, coach portal, event planning, and WhatsApp automation are future phases.

## 2. Scope

### In scope
- Latvian-only parent registration flow
- magic-link parent access
- admin backoffice for application review
- admin request-fix / approve / reject workflow
- approved member registry
- manual assignment of one training group per member
- secure storage of identity documents
- OCR-assisted prefill from uploaded ID/passport image
- billing setup and recurring invoice creation in Invoice Ninja
- payment status sync from Invoice Ninja into admin overview
- member search/filter and CSV export
- multiple admins with same permissions

### Out of scope
- coach role and coach portal
- adult member support
- attendance tracking
- WhatsApp bot and WhatsApp notifications
- event / competition / travel planning
- direct national FA integration
- custom invoice workflows beyond membership fee MVP
- in-app manual discount engine beyond sibling-discount rules

## 3. Users and roles

### Parent
- enters child and guardian data
- uploads identity documents
- receives magic-link access by email
- can view application status
- can edit application until approval
- can upload/fix missing documents after admin request

### Admin
- reviews applications
- requests fixes
- approves or rejects registrations
- creates official member record through approval flow
- assigns training group
- chooses billing start month
- confirms payment mode and sibling-discount behavior
- monitors document, OCR, and invoice sync status
- views payment status from Invoice Ninja

## 4. Recommended architecture
Use a **Django monolith** with PostgreSQL, private document storage, and background jobs.

### Why this architecture
- admin-heavy workflow fits Django well
- secure forms, auth, ORM, and server-rendered backoffice are mature
- monolith reduces operational complexity for MVP
- background jobs isolate slow or failure-prone external API work
- future phases can still extend the same app or split later if needed

### High-level shape
```text
Parent portal
  └─ magic-link access, application form, status, fixes

Admin backoffice
  └─ review queue, member registry, group assignment, billing controls

Django app
  ├─ registration workflow
  ├─ member registry
  ├─ billing rules engine
  ├─ Invoice Ninja integration
  ├─ OCR orchestration
  ├─ document access control
  └─ audit trail

Infrastructure
  ├─ PostgreSQL
  ├─ private file/object storage
  └─ background workers for email, OCR, billing sync, retries
```

## 5. Core domain model

### ParentAccount
Authentication/login identity for parent access.
- email
- optional phone
- magic-link session identity
- active/disabled state

### Guardian
Legal/billing person linked to the child.
- name
- personal ID number
- address/contact data
- billing defaults

Reason for separation from `ParentAccount`:
login identity is not the same as legal/billing identity and this keeps future family complexity manageable.

### RegistrationApplication
Draft/submitted workflow record for intake.
- draft / submitted / fix-requested / approved / rejected
- child details
- guardian details snapshot
- uploaded document references
- OCR metadata/status
- admin notes

Reason for separation from `Member`:
approval workflow needs drafts and revisions without creating partial member records.

### Member
Official approved club member.
- created only on approval
- child personal/profile data
- club status
- group assignment
- guardian linkage

### TrainingGroup
Admin-managed training group.
- title/code
- active state
- optional coach-name text field for MVP display only

### MembershipPlan
Per-member billing configuration.
- year fee baseline
- payment mode: upfront or installments
- sibling discount applied or opted out
- billing start month

Reason for separate record:
billing settings can vary by member and by year; this keeps finance logic traceable.

### Document
Stored identity document.
- private file reference
- file metadata
- OCR processing status
- deletion status
- created/viewed/deleted audit references

### InvoiceProfile
Integration linkage to Invoice Ninja.
- external customer/contact IDs
- payer selection
- sync health/status
- last sync timestamps

### InvoiceSyncEvent
Operational history for billing integration.
- sync attempt type
- request/response metadata with redaction
- success/failure state
- retry count

### AuditEvent
Structured history for security and workflow actions.
- approvals/rejections
- document view/download/delete
- admin edits
- billing sync actions

## 6. Workflow design

### Registration flow
1. Parent opens registration form.
2. Parent enters child and guardian data.
3. Parent uploads child passport or national ID image.
4. OCR job runs in background and returns suggested field values.
5. Parent can accept/correct OCR-prefilled data.
6. Parent submits application.
7. Application status becomes `submitted`.

### Admin review flow
1. Admin opens submitted application.
2. Admin reviews data and documents.
3. Admin chooses one of:
   - request fixes
   - reject
   - approve
4. If fixes requested, parent receives email with magic link and can update application.
5. If approved:
   - Member record is created
   - Guardian linkage is finalized
   - training group is assigned
   - billing start month is selected
   - payment mode is selected
   - sibling discount state is confirmed

### Billing flow
1. Approval triggers billing setup job.
2. App creates or updates Invoice Ninja customer/contact records.
3. App creates recurring membership invoice setup in Invoice Ninja.
4. App stores external IDs and sync result.
5. Scheduled sync jobs pull invoice/payment status snapshots back into admin overview.
6. Failures are visible and retryable by admin.

### OCR behavior
- OCR is assistive only
- OCR failure never blocks registration
- parent/admin can always manually correct values
- OCR extracted data is treated as sensitive PII

## 7. Billing rules

### Base pricing
- default annual fee: **€300**
- payment modes:
  - upfront
  - 10 installments

### Billing months for installments
- chargeable months: January–June, August–November
- no fee months: July, December

### Billing start
- admin chooses start month per member

### Sibling discount
- second child gets **50% discount**
- parent may opt to pay full price instead
- discount offer is detected by matching guardian personal ID number
- admin may handle manual exception cases

### Manual discounts
Other discounts may remain manual in Invoice Ninja for MVP.

### Source of financial truth
Invoice Ninja remains the source of truth for:
- invoice objects
- payment status
- payment collection state

The app owns membership rules and synchronization, but not a separate internal finance ledger.

## 8. Security baseline

### Data sensitivity
System stores:
- full guardian personal ID numbers
- child identity document images
- OCR-extracted identity data
- billing payer details

This requires a deliberate baseline even in MVP.

### Access control
- admins can access all records
- parent can access only own application/member context
- no public document URLs
- document access is always checked by application authorization

### Magic links
- email-based
- single-use
- short TTL
- revoked on successful use
- rate-limited send endpoint

### UI/logging rules
- personal IDs masked in list/search screens
- full values shown only on restricted detail views
- raw personal IDs and OCR fields must never appear in logs
- external API failures must redact sensitive payloads

### Storage rules
- HTTPS required in production
- secrets stored outside repository
- documents kept in private file/object storage
- downloads streamed through backend rather than direct public links
- document view/download/delete actions audited
- document deletion supported by admin

### Recommended hardening for MVP
- encrypted disk/volume at infrastructure level
- app-level encryption for most sensitive fields if implementation remains practical
- structured audit log for sensitive actions

## 9. Admin backoffice requirements
- submitted application review queue
- member list
- search/filter by status and group
- billing/invoice sync status visibility
- payment status overview from Invoice Ninja sync
- CSV export
- document review and deletion actions

## 10. Parent portal requirements
- Latvian UI only
- magic-link login
- view application status
- edit application before approval
- respond to admin fix requests
- upload missing/replacement documents

## 11. External integrations

### Invoice Ninja
Purpose:
- create/update customer/contact data
- create recurring membership invoice configuration
- sync invoice/payment status back

Integration principles:
- run through background jobs
- store external IDs explicitly
- keep retryable status history
- never treat app as the payment ledger

### OCR provider (e.g. Tiny IDP)
Purpose:
- extract data from child identity document to speed registration

Integration principles:
- background job only
- failure never blocks parent workflow
- extracted data editable by user/admin
- provider responses treated as sensitive

## 12. Future phases
Planned but excluded from MVP:
- coach role and coach portal
- attendance tracking
- WhatsApp attendance bot
- event/competition/travel planning
- custom non-membership invoice flows
- adult member support
- direct national FA integration

## 13. Acceptance criteria for design
This design is considered correct if implementation can produce:
- a Latvian parent registration flow for minors
- admin approval workflow with fix/reject/approve states
- secure document storage and controlled access
- OCR-assisted, non-blocking prefill
- approved member registry with training-group assignment
- automatic recurring membership invoice setup in Invoice Ninja
- payment status visibility synced from Invoice Ninja
- sibling discount offer based on guardian personal ID
- CSV export and admin search/filtering

## 14. Open implementation choices intentionally left for planning
These are not unresolved requirements; they are implementation decisions for next phase:
- exact Django app/module boundaries
- exact storage backend (local private storage vs S3-compatible object storage)
- exact queue/job tool choice
- exact field-encryption package choice
- exact admin UI approach (Django admin only vs custom backoffice pages where needed)

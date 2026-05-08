# Admin Review and Member Creation Design

**Date:** 2026-05-07
**Status:** Draft for review
**Scope:** M3 initial slice — admin review for submitted registration applications, parent feedback loop, and member creation on approval.

## 1. Problem

Submitted registration applications can be created by parents, but staff cannot yet process them through an internal review workflow. This blocks milestone M3 because there is no supported path to:

- see submitted applications in a staff-facing queue,
- inspect full application data and private identity documents,
- request corrections from parents,
- reject unsuitable applications,
- approve valid applications and create first-class member records.

Without this feature, registration intake cannot transition into club operations.

## 2. Goals

This slice must provide:

- a staff-only review queue for submitted applications,
- a staff-only detail page for reviewing application data and documents,
- review actions for `request fix`, `reject`, and `approve`,
- parent-facing visibility of review status and staff message,
- email notifications for `request fix`, `reject`, and `approve`,
- creation of `Guardian`, `Member`, and empty training-group assignment placeholder on approval,
- automated tests for queue access, review actions, notifications, reopen/resubmit flow, and one-time member creation.

## 3. Non-goals

Out of scope for this slice:

- billing or Invoice Ninja sync,
- OCR improvements or extraction automation,
- agreement/signing workflow,
- advanced admin analytics or bulk processing,
- rich audit-event framework beyond what is necessary to keep code structured for later enhancement,
- real training-group assignment logic beyond storing an empty placeholder.

## 4. Current constraints and context

- `RegistrationApplication` already supports statuses: `draft`, `submitted`, `fix_requested`, `approved`, `rejected`.
- Parent-facing registration and portal flows already exist.
- Current editability logic only treats `draft` as editable and must be expanded for `fix_requested`.
- `apps/members` exists as app shell only; member-domain models are not implemented yet.
- Custom admin pages are preferred over Django admin-only workflow, but Django admin should link into review pages.
- Existing document privacy controls must remain intact.
- Existing email path should be reused where practical.

## 5. Recommended approach

Use thin custom staff-only review pages over current registration models.

Why this approach:

- It is the smallest change that unlocks M3 workflow.
- It matches preferred UX direction: custom admin pages with optional Django admin entry links.
- It avoids premature workflow/event abstraction before real review usage is validated.
- It keeps `RegistrationApplication` as the source of truth and lets later milestones extend rather than replace this slice.

Alternatives considered and rejected:

1. **Heavier workflow module now** — rejected because it adds extra modeling and coordination cost before basic staff processing exists.
2. **Django admin-first actions** — rejected because it conflicts with chosen UI direction and gives a weaker review experience.

## 6. High-level architecture

```text
Staff user
   |
   v
Custom admin review queue ----> custom admin review detail
   |                                   |
   |                                   +--> request fix form
   |                                   +--> reject form
   |                                   +--> approve action
   |
   v
Registration review service
   |
   +--> validate allowed transition
   +--> persist status + review message + reviewer metadata
   +--> send parent notification email
   +--> on approve: create Guardian + Member + empty group placeholder
   +--> enforce idempotent approval
   |
   v
Parent portal / application detail
   |
   +--> show new status
   +--> show fix/reject message
   +--> allow edit + resubmit only when reopened
```

## 7. Domain model changes

### 7.1 RegistrationApplication changes

Extend `RegistrationApplication` with review metadata:

- `review_message: TextField(blank=True, default="")`
- `reviewed_by: ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL)`
- `reviewed_at: DateTimeField(null=True, blank=True)`
- `approved_member: OneToOneField("members.Member", null=True, blank=True, on_delete=SET_NULL, related_name="source_application")`

Design notes:

- `review_message` stores staff reason for `fix_requested` or `rejected`.
- `reviewed_by` and `reviewed_at` record latest staff action for this slice.
- `approved_member` prevents duplicate member creation and provides direct lookup from application to member.
- `submitted_at` will be overwritten on each resubmission, which is acceptable for MVP. Historical workflow events are deferred.

### 7.2 Member-domain models

Add initial `apps/members/models.py` with:

#### `Guardian`
Fields:
- `full_name`
- `personal_id`
- `email`
- `phone`
- `address`

#### `TrainingGroup`
Minimal placeholder model so `Member` can carry nullable assignment.
Fields:
- `name`
- `is_active`

This model exists mainly to support future assignment and admin display. No assignment logic is required in this slice.

#### `Member`
Fields:
- `full_name`
- `personal_id`
- `birth_date`
- `guardian` (FK to `Guardian`)
- `training_group` (nullable FK to `TrainingGroup`)
- `registration_application` is represented by the reverse one-to-one from `RegistrationApplication.approved_member`

Design notes:

- Approval creates one guardian and one member from application data.
- No deduplication across separate applications is required in this slice.
- `training_group` remains `NULL` on approval.

## 8. Workflow and state transitions

### 8.1 Review queue eligibility

The admin queue lists only applications with status `submitted`.

`fix_requested`, `approved`, and `rejected` applications are excluded from the active queue but remain available via direct detail/admin navigation.

### 8.2 Request fix

When staff requests a fix:

- status changes from `submitted` to `fix_requested`,
- `review_message` is required,
- `reviewed_by` and `reviewed_at` are updated,
- parent receives notification email,
- parent portal shows status and message,
- same application becomes editable for parent.

### 8.3 Parent resubmission after fix request

When parent edits a `fix_requested` application and submits again:

- application is allowed through existing edit flow,
- `submit_application(...)` accepts `fix_requested` in addition to `draft`,
- status changes to `submitted`,
- `submitted_at` is refreshed,
- `review_message`, `reviewed_by`, and `reviewed_at` are cleared,
- application re-enters staff queue.

### 8.4 Reject

When staff rejects an application:

- status changes from `submitted` to `rejected`,
- `review_message` is required,
- `reviewed_by` and `reviewed_at` are updated,
- parent receives notification email,
- parent portal shows rejection status and reason,
- application is terminal and not editable.

### 8.5 Approve

When staff approves an application:

- status changes from `submitted` to `approved`,
- `review_message` is cleared,
- `reviewed_by` and `reviewed_at` are updated,
- system creates `Guardian` and `Member` if not already created,
- created member is linked back through `approved_member`,
- `training_group` remains empty,
- parent receives approval email,
- second approval attempt must not create duplicates.

## 9. Business rules

- Only staff users may access review queue, detail page, or review actions.
- Only `submitted` applications may be reviewed by staff actions.
- `request fix` and `reject` require non-empty staff message.
- `approve` must be idempotent: if approval logic is triggered again for an already approved application with linked member, no duplicate records are created.
- Parent may edit application only when:
  - they satisfy ownership/session access checks, and
  - application status is `draft` or `fix_requested`.
- Parent may submit application when status is `draft` or `fix_requested`.
- Existing private document authorization paths remain unchanged.

## 10. UI design

### 10.1 Custom staff review pages

Add custom staff-only pages under a dedicated admin-review URL namespace, preferably `/admin/review/applications/` and `/admin/review/applications/<id>/`.

#### Queue page
Display:
- child full name,
- guardian full name,
- guardian email,
- submitted timestamp,
- status,
- link to detail page.

Behavior:
- default ordering: newest submitted first,
- only staff access,
- simple table layout is sufficient for MVP.

#### Detail page
Display:
- full registration summary,
- active identity document preview/download links,
- review status metadata,
- action controls:
  - request fix form with required message,
  - reject form with required message,
  - approve button.

### 10.2 Django admin integration

In Django admin for registration applications:
- add link to custom review page from changelist and/or object detail,
- optionally expose readonly review status metadata.

The custom pages remain primary workflow entry.

### 10.3 Parent-facing updates

Update parent portal and application detail templates to show:
- status badge/text,
- `review_message` for `fix_requested` and `rejected`,
- edit action only when application is editable,
- approval status message once approved.

## 11. Notifications

Reuse current email sending path where practical.

### Notification cases

#### Fix requested email
Must include:
- explanation that changes are needed,
- staff review message,
- link back to parent portal or application.

#### Rejection email
Must include:
- explanation that application was rejected,
- staff review message,
- portal link if useful for reference.

#### Approval email
Must include:
- confirmation that application was approved,
- note that member record has been created,
- next-step pointer if one exists; otherwise keep message simple.

## 12. Service-layer design

Add review workflow service functions in `apps/registrations/services.py` or split to a dedicated review service module if file clarity requires it.

Required responsibilities:

- fetch and validate target application,
- enforce allowed transitions,
- persist review metadata,
- send notification emails,
- create member-domain records on approval,
- keep approval idempotent.

Suggested service functions:

- `request_application_fix(application, reviewer, message)`
- `reject_application(application, reviewer, message)`
- `approve_application(application, reviewer)`
- `create_member_from_application(application)`

If `services.py` becomes too crowded, move review logic into `apps/registrations/review_services.py` while keeping parent draft/submit flow in existing `services.py`.

## 13. Access control

- Review queue and detail views require authenticated staff user.
- Anonymous users should be redirected to admin login.
- Authenticated non-staff users should receive `404` to avoid exposing review surface.
- Parent-facing pages keep existing ownership checks.
- Private document links on review page must continue using authenticated backend views, not direct file URLs.

## 14. Testing strategy

Use `pytest` + `pytest-django`.

### Must-test scenarios

1. **Queue access control**
   - anonymous denied,
   - non-staff denied,
   - staff allowed.

2. **Queue contents**
   - submitted applications shown,
   - non-submitted applications excluded.

3. **Request fix**
   - requires message,
   - changes status to `fix_requested`,
   - stores review metadata,
   - sends email.

4. **Parent reopen/resubmit**
   - `fix_requested` application becomes editable,
   - parent can update and resubmit same application,
   - status returns to `submitted`,
   - review message cleared,
   - queue shows application again.

5. **Reject**
   - requires message,
   - changes status to `rejected`,
   - stores review metadata,
   - sends email.

6. **Approve**
   - changes status to `approved`,
   - creates guardian and member,
   - member has empty training-group assignment,
   - sends approval email.

7. **Approve idempotency**
   - repeated approve path does not create duplicate member or guardian records for same application.

8. **Parent portal visibility**
   - fix/reject reason shown to parent,
   - edit action shown only for `draft`/`fix_requested`.

### Explicitly not tested in this slice

- billing follow-on behavior,
- OCR/document extraction integration,
- advanced visual styling,
- complex email template copy fidelity,
- training-group assignment workflows.

## 15. Acceptance criteria

Feature is complete when all of the following are true:

1. Staff can open a custom queue of submitted applications.
2. Staff can open a detail page showing registration data and private-document actions.
3. Staff can request fixes with a required message.
4. Parent can see fix message, edit same application, and resubmit it.
5. Staff can reject with a required message.
6. Parent can see rejection reason.
7. Staff can approve an application.
8. Approval creates exactly one `Guardian` and one `Member`, linked to source application.
9. Approved member has no training-group assignment yet.
10. Fix, reject, and approve actions all send email notifications.
11. Automated tests cover queue access, state transitions, notifications, reopen/resubmit flow, and one-time member creation.

## 16. Risks and follow-up

Known deferred items:

- richer audit/event trail for every review action,
- dedicated review-history model,
- duplicate-person detection across separate applications,
- admin queue filtering/search,
- training-group assignment workflow,
- downstream billing/integration triggers from approval.

These are intentionally deferred to keep this slice focused and implementable.

# FK Cēsis MMS Milestones

## Current Execution Snapshot
- **Completed implementation tasks:** Task 1 (project bootstrap), Task 2 (absorbed into Task 1), Task 3 (core app skeleton and `TimeStampedModel`), Task 4 (parent accounts and magic links)
- **Next active implementation task:** Task 5 — Registration application workflow
- **Current milestone focus:** `M2` has not started yet; remaining `M1` deliverables still need implementation (private documents, background jobs, auth foundations, audit baseline)
- **Current acceptance-test baseline:** LAN URL `http://192.168.3.245:8000`
- **Future sprint note:** add automatic `.env` loading for management commands and local app startup so env-driven workflows do not require manual `source .env`
- **Future sprint note:** when starting work from a new worktree, copy project-root `.env` into that worktree and refresh `SITE_URL` / trusted-origin config for the active tunnel URL; current tunnel admin login failure is consistent with missing tunnel-aware CSRF configuration

## M1 — Foundation and security baseline
**Priority:** High
**Status:** In progress
**Goal:** Create secure project foundation for sensitive youth-member data.

**Deliverables**
- Django project scaffold with `uv`
- PostgreSQL configuration
- private document storage abstraction
- background job framework
- authentication foundations for admin + magic-link parent access
- baseline audit/event logging
- `.env.example`, setup docs, local run/test commands

**Acceptance criteria**
- fresh checkout can boot app locally with documented steps
- tests, lint, and type checks run from documented commands
- secrets not committed
- document downloads require authorization path, not public file URLs
- first usable app slice can be exposed on LAN for early acceptance testing

## M2 — Parent registration intake
**Priority:** High
**Status:** Pending — next milestone after remaining M1 foundation work
**Goal:** Allow parent to create and submit child registration with secure document upload.

**Execution rule**
- Implement this milestone in isolated git worktree branches and merge back only after user approval.

**Deliverables**
- Latvian registration form
- guardian + child data capture
- identity document upload
- OCR assist pipeline with manual correction
- draft/submitted workflow state
- parent magic-link access to resume application

**Acceptance criteria**
- parent can start, save, return, and submit application
- OCR failure does not block submission
- uploaded documents are private

## M3 — Admin review and member creation
**Priority:** High
**Status:** Pending
**Goal:** Let admins review applications and convert approved ones into official members.

**Deliverables**
- admin application queue
- request-fix / reject / approve actions
- member creation on approval
- training group assignment
- admin activity audit entries

**Acceptance criteria**
- admins can process submitted applications end-to-end
- parent receives notification for fix request
- approved application creates member exactly once

## M4 — Billing and Invoice Ninja sync
**Priority:** High
**Status:** Pending
**Goal:** Automate recurring membership billing setup and payment-status visibility.

**Deliverables**
- membership plan model
- sibling discount logic
- billing start month choice
- Invoice Ninja customer/contact sync
- recurring invoice creation
- payment status sync overview and retry tools

**Acceptance criteria**
- approved member can be synced to Invoice Ninja
- recurring billing follows €300 yearly rules and installment schedule
- sync failures are visible and retryable

## M5 — Admin operations and export
**Priority:** Medium
**Status:** Pending
**Goal:** Provide usable day-to-day administration tools.

**Deliverables**
- member search/filter by status/group
- invoice/payment overview
- CSV export
- document deletion controls

**Acceptance criteria**
- admins can find records quickly
- CSV export includes agreed MVP fields
- document actions are audited

## M6 — Production readiness
**Priority:** Medium
**Status:** Pending
**Goal:** Make MVP deployable and supportable.

**Deliverables**
- deployment docs
- backup/restore notes
- environment setup for OCR + Invoice Ninja
- error monitoring hooks
- final security checklist

**Acceptance criteria**
- documented deployment path exists
- key integrations configurable without code changes
- restore and operational recovery steps documented

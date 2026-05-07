# FK Cēsis MMS Milestones

## Current Execution Snapshot
- **Completed implementation tasks:** Task 1 (project bootstrap), Task 2 (absorbed into Task 1), Task 3 (core app skeleton and `TimeStampedModel`), Task 4 (parent accounts and magic links), Task 5 (registration application workflow)
- **Next active implementation task:** Visual system + registration form redesign (build-now), followed by Task 6 — Admin review and member creation
- **Current milestone focus:** `M2` registration intake is substantially implemented (draft/submit, magic-link portal, document upload); private document access controls are now implemented; remaining `M1` deliverables still need implementation (background jobs, audit baseline)
- **Current acceptance-test baseline:** LAN URL `http://192.168.3.245:8000` — registration workflow is usable for acceptance flow
- **Task 5 polish:** `/register/` accessible without login; anonymous save-draft creates/links `ParentAccount`; single edit form with save-draft and submit actions; native date picker for child birth date
- **Technical debt:** registration edit flow does not show existing uploaded identity document state, so unnecessary re-uploads can replace earlier files; Django admin also needs clearer active vs replaced document UX for soft-deleted rows.
- **New approved direction (2026-05-05):** Whole-app visual system and registration form redesign approved. Parent identity verification security fix approved — typed email in registration draft is a claim, not proof of ownership; two-layer model (unverified browser-session drafts + verified parent identity gate); portal access based on verified identity only. See `docs/superpowers/specs/2026-05-05-parent-identity-verification-design.md`. Three research spikes launched: ID document extraction vendor, agreement generation/signing module, SMTP/email provider strategy. Hosting stance: self-hosted is not assumed more secure by default; compare self-hosted and SaaS by security posture, ops maturity, compliance, and API portability. Self-hosted services may live in separate infrastructure/Ansible projects while this repo integrates loosely through adapters and external config. Visual style source of truth is now `style-guide/`, which supersedes `design-template.html`; current canonical tokens are font `Anton`, blue `#0f0851`, red `#ce1c20`. See `docs/superpowers/specs/2026-05-05-registration-design-and-integrations-design.md`.
- **Future sprint note:** add automatic `.env` loading for management commands and local app startup so env-driven workflows do not require manual `source .env`
- **Future sprint note:** when starting work from a new worktree, copy project-root `.env` into that worktree and refresh `SITE_URL` / trusted-origin config for the active tunnel URL; current tunnel admin login failure is consistent with missing tunnel-aware CSRF configuration
- **Future sprint note:** email gateway — automated verification emails (not just debug-mode magic links) with proper SMTP provider integration; social login (Google/Facebook) as alternative verification method for parent identity gate

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
**Status:** Partially complete — draft/submit workflow, parent portal, magic-link resume, and document upload implemented; OCR assist still placeholder; visual redesign and UX improvements planned; **verified identity gating required as follow-up**
**Goal:** Allow parent to create and submit child registration with secure document upload.

**Security note:** Current draft flow auto-links `ParentAccount` by typed email — a security flaw. Follow-up work must implement the two-layer model (unverified drafts + verified parent identity gate) described in `docs/superpowers/specs/2026-05-05-parent-identity-verification-design.md`.

**Execution rule**
- Implement this milestone in isolated git worktree branches and merge back only after user approval.

**Deliverables**
- Latvian registration form ✅
- guardian + child data capture ✅
- identity document upload ✅
- OCR assist pipeline with manual correction *(placeholder only)*
- draft/submitted workflow state ✅
- parent magic-link access to resume application ✅

**Acceptance criteria**
- parent can start, save, return, and submit application ✅
- OCR failure does not block submission ✅ *(no OCR integration yet)*
- uploaded documents are private *(model exists; access controls now implemented — private storage root + admin-only preview/download endpoints)*

## M3 — Admin review and member creation
**Priority:** High
**Status:** Pending — depends on M1 security baseline and agreement research outcomes
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

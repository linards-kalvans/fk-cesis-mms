# Parent Identity Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the registration ownership flaw so typed email is treated as a claim, not proof of ownership, while preserving same-browser draft continuity and adding verified parent portal access.

**Architecture:** Split draft ownership from verified parent identity. Registration drafts become browser-session-owned records with `claimed_email`, while portal visibility and cross-registration access are unlocked only after email verification through the existing magic-link mechanism. Keep provider-specific email delivery separate from the identity model so future SMTP/API backends and social login can reuse the same verified identity gate.

**Tech Stack:** Django models/views/forms/templates, existing magic-link token flow, pytest + pytest-django, Ruff, mypy, Django migrations.

---

## 1. Design decisions

### 1.1 Make verified parent link nullable
**Why:** A draft created by an anonymous browser must not auto-attach to an existing parent account. The application needs to exist before identity proof exists.

### 1.2 Store claimed email on the application
**Why:** The draft still needs an email destination for later verification, but that value is only a claim until verified.

### 1.3 Add browser-session draft ownership token
**Why:** Same-browser draft continuation must keep working without verified login. A draft session token provides continuity without granting account-wide visibility.

### 1.4 Reuse magic-link verification for parent identity
**Why:** Existing token issuance/consume flow already verifies email ownership. Reusing it keeps scope smaller than introducing a second verification mechanism now.

### 1.5 Portal queries by verified parent only
**Why:** Account-wide visibility must derive from verified identity, never from a typed email claim.

### 1.6 Separate delivery backend from identity logic
**Why:** Email gateway choice is infrastructure. The verification domain flow should survive later SMTP relay, API provider, or future social login changes.

---

## 2. File-by-file architecture plan

### Modify
- `apps/registrations/models.py`
  - make `parent_account` nullable and reinterpret it as verified parent owner
  - add `claimed_email`
  - add `draft_session_key`
  - update helper methods for draft edit vs verified visibility
- `apps/registrations/services.py`
  - stop auto-linking `ParentAccount` during draft save
  - assign/use `claimed_email`
  - assign/use `draft_session_key`
  - add helper to attach unverified applications to verified parent after magic-link consume
- `apps/registrations/views.py`
  - allow same-browser draft editing by session token
  - prevent portal/account visibility without verified parent session
  - ensure submitted applications remain read-only
- `apps/accounts/forms.py`
  - adjust request form validation so verification can be requested for claimed-email drafts even if no `ParentAccount` exists yet
- `apps/accounts/views.py`
  - after successful magic-link verification, attach matching claimed-email applications to the verified parent account
  - keep debug preview flow intact
- `apps/accounts/services.py`
  - add helper for requestable email existence check if needed by form/view logic
- `tests/registrations/test_application_workflow.py`
  - update ownership expectations around draft save
- `tests/registrations/test_parent_edit_permissions.py`
  - cover same-browser continuation vs cross-browser restriction
- `tests/accounts/test_login_views.py`
  - cover claimed-email verification request and post-verify attachment
- `docs/milestones.md`
  - add email gateway and social login future features explicitly
- `docs/superpowers/plans/2026-05-04-fk-cesis-mms-mvp-implementation.md`
  - reflect parent identity gate as next security task and future auth/email roadmap
- `AGENTS.md`
  - keep current-status and future-feature notes accurate if new roadmap items are added

### Create
- `apps/registrations/migrations/0002_parent_identity_gate.py`
  - nullable verified parent link, claimed email, draft session key
- `tests/registrations/test_parent_identity_gate.py`
  - focused security regression tests for claim-vs-proof behavior

---

## 3. Test strategy

### What to test
- saving a draft with another parent's email does not make that parent's registrations visible in the same browser or a different browser
- same browser can reopen draft via `draft_session_key` without verified login
- different browser cannot access draft by guessed application ID alone
- magic-link request works for claimed-email draft even if no `ParentAccount` existed before
- successful magic-link verification attaches matching claimed-email applications to verified parent
- portal lists only `parent_account`-attached applications
- submitted applications remain view-only

### What not to test
- exact email provider implementation details
- social login implementation (roadmap only)
- CSS behavior already covered by existing redesign tests

---

## 4. Acceptance criteria

- typing an existing parent's email on a new draft does not expose that parent's registrations
- anonymous user can save and resume a draft in the same browser
- different browser cannot access a draft without successful email verification
- successful email verification grants portal visibility to claimed-email registrations by attaching them to verified parent identity
- portal queries use `parent_account`, not `claimed_email`
- real email delivery remains configurable; roadmap docs explicitly mention future email gateway and social login features

---

## 5. Documentation scope

Update docs to make future follow-up explicit:
- **Email gateway feature:** production delivery backend selection/implementation remains a roadmap item
- **Social account login feature:** future provider-based login can satisfy the same verified identity gate
- milestones and master plan should both mention these as planned follow-up features, not implemented behavior

# Test Suite Runtime Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce full test-suite runtime from the current measured 114.53s toward 60–80s by deleting or merging duplicate expensive tests while preserving behavior coverage.

**Architecture:** Keep full-suite coverage as the source of truth, and reduce repeated Django admin/page rendering rather than changing application code. Consolidate cluster-by-cluster: registrations admin tests first, parent visual/copy contracts second, billing/agreement/member admin tests third. Stop if a deletion risks removing unique coverage for security, money, audit, document access, migrations, data-loss prevention, or external payload builders.

**Tech Stack:** Python 3.12+, Django 5.x, pytest, pytest-django, uv. No new dependencies and no production-code changes.

---

## Baseline

Measured on 2026-07-02 after fast-lane work:

- Fast lane: `uv run pytest -q -m "not slow" --durations=25` → 1294 passed, 257 deselected, 50.37s.
- Full suite: `uv run pytest -q --durations=25` → 1551 passed, 114.53s.

The working tree contains unrelated pre-existing changes. Do not touch unrelated files. Do not commit unless explicitly asked.

---

## Design Decisions

1. Tests-only consolidation. Do not modify production app code.
2. Delete duplicate view/admin coverage, not core behavior checks.
3. Prefer parametrization and moving one unique assertion into an existing test over adding new files.
4. Stop before risky deletion. It is acceptable to miss the 60–80s target if the next cuts would remove unique protected coverage.
5. Keep the fast lane and full suite commands unchanged.

---

## Protected Coverage

Do not remove or mark away the only coverage for:

- security permissions;
- billing money calculations;
- document access controls;
- audit writes;
- migrations;
- data-loss prevention;
- external payload builders.

If a slow admin/view test covers one of these, keep it unless an equivalent fast service/unit test already exists.

---

## Task 1: Registrations Admin Cluster Audit and Consolidation

**Files:**
- Modify: `tests/registrations/test_admin_agreement_lifecycle.py`
- Modify: `tests/registrations/test_admin_review_agreement_ui.py`
- Modify: `tests/registrations/test_admin_review_actions.py`
- Modify: `tests/registrations/test_admin_changelist_quick_actions.py`
- Modify: `tests/registrations/test_admin_inline_preview.py`
- Modify: `tests/registrations/test_admin_cross_links.py`

- [ ] **Step 1: Run focused baseline**

```bash
uv run pytest tests/registrations/test_admin_agreement_lifecycle.py tests/registrations/test_admin_review_agreement_ui.py tests/registrations/test_admin_review_actions.py tests/registrations/test_admin_changelist_quick_actions.py tests/registrations/test_admin_inline_preview.py tests/registrations/test_admin_cross_links.py -q --durations=25
```

Expected: pass. Record runtime and slowest tests.

- [ ] **Step 2: Build a coverage map before deletion**

For each file, list each test and classify it as one of:

- unique state transition or permission behavior;
- duplicate admin page render smoke;
- duplicate CSS/HTML/class assertion;
- duplicate redirect/message assertion;
- protected coverage.

- [ ] **Step 3: Consolidate duplicate action tests**

Where several tests POST the same admin endpoint and differ only by action/state, replace them with a parametrized test. Keep separate tests only when setup and assertions represent different behavior.

- [ ] **Step 4: Consolidate render smoke tests**

Keep one rendered admin change-page smoke per major surface. Move any unique text/class assertion from deleted render tests into that smoke.

- [ ] **Step 5: Run focused tests**

```bash
uv run pytest tests/registrations/test_admin_agreement_lifecycle.py tests/registrations/test_admin_review_agreement_ui.py tests/registrations/test_admin_review_actions.py tests/registrations/test_admin_changelist_quick_actions.py tests/registrations/test_admin_inline_preview.py tests/registrations/test_admin_cross_links.py -q --durations=25
```

Expected: pass.

- [ ] **Step 6: Run lanes**

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass. Record runtimes.

---

## Task 2: Parent Visual and Copy Contract Consolidation

**Files:**
- Modify: `tests/registrations/test_visual_contract.py`
- Modify: `tests/registrations/test_parent_surface_copy_contract.py`
- Modify: `tests/registrations/test_portal_polish.py` only if an assertion is moved there.

- [ ] **Step 1: Run focused baseline**

```bash
uv run pytest tests/registrations/test_visual_contract.py tests/registrations/test_parent_surface_copy_contract.py tests/registrations/test_portal_polish.py -q --durations=25
```

Expected: pass.

- [ ] **Step 2: Identify repeated assertions**

Look for repeated checks of:

- `fk-` class presence;
- stylesheet links;
- logo/hero copy;
- English-token leakage;
- mobile CSS snippets;
- empty-state partial rendering.

- [ ] **Step 3: Keep one smoke per behavior**

Keep one fast static/template scan and one slow rendered copy scan. Delete repeated CSS/string tests where the same selector/string is asserted elsewhere.

- [ ] **Step 4: Run focused tests**

```bash
uv run pytest tests/registrations/test_visual_contract.py tests/registrations/test_parent_surface_copy_contract.py tests/registrations/test_portal_polish.py -q --durations=25
```

Expected: pass.

- [ ] **Step 5: Run lanes**

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass. Record runtimes.

---

## Task 3: Billing, Agreement, and Member Admin Consolidation

**Files:**
- Modify: `tests/billing/test_admin_sync_health.py`
- Modify: `tests/billing/test_admin_confirm_action.py`
- Modify: `tests/billing/test_billing_adjustment_admin.py`
- Modify: `tests/agreements/test_admin_sync_health.py`
- Modify: `tests/members/test_admin_group_merge.py`

- [ ] **Step 1: Run focused baseline**

```bash
uv run pytest tests/billing/test_admin_sync_health.py tests/billing/test_admin_confirm_action.py tests/billing/test_billing_adjustment_admin.py tests/agreements/test_admin_sync_health.py tests/members/test_admin_group_merge.py -q --durations=25
```

Expected: pass.

- [ ] **Step 2: Collapse badge/filter variants**

If several tests differ only by status/error values and assert the same badge/filter behavior, replace them with parametrized tests. Keep helper-level tests such as `tests/core/test_admin_badges.py` as the detailed HTML escaping/style coverage.

- [ ] **Step 3: Collapse admin action variants**

Where confirm/retry/merge tests repeat the same admin action path, keep one end-to-end admin path and rely on service/audit tests for detailed behavior. Do not remove audit coverage unless another test asserts the same `AuditEvent` action and metadata.

- [ ] **Step 4: Run focused tests**

```bash
uv run pytest tests/billing/test_admin_sync_health.py tests/billing/test_admin_confirm_action.py tests/billing/test_billing_adjustment_admin.py tests/agreements/test_admin_sync_health.py tests/members/test_admin_group_merge.py -q --durations=25
```

Expected: pass.

- [ ] **Step 5: Run lanes**

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass. Record runtimes.

---

## Task 4: Final Measurement and Documentation

**Files:**
- Modify: `docs/testing.md`

- [ ] **Step 1: Run final verification**

```bash
uv run pytest -q -m "not slow" --durations=50
uv run pytest -q --durations=50
uv run ruff check .
uv run mypy .
```

Expected: all pass.

- [ ] **Step 2: Update measured runtime section**

Update `docs/testing.md` with the final measured fast and full-suite runtimes. If the full suite remains above 80s, add a short note with the slowest remaining tests and why they were not removed.

- [ ] **Step 3: Generate diff URL**

Run `bunx critique --web` with filters for changed files and share the URL.

---

## Acceptance Criteria

- Fast lane passes.
- Full suite passes.
- `ruff` and `mypy` pass.
- Full suite runtime is reduced materially from 114.53s, ideally to 60–80s.
- If 60–80s is missed, `docs/testing.md` and final report state actual runtime and why further cuts were not safe.
- No production code changed.
- No unique protected coverage removed.

---

## Self-Review

- Spec coverage: includes user-requested real full-suite consolidation.
- Placeholder scan: no TBD/TODO placeholders.
- Scope check: tests/docs only; production code out of scope.
- Type/name consistency: commands and marker names match existing fast-lane work.

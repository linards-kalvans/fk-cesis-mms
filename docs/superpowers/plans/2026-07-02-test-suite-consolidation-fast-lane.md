# Test Suite Consolidation + Fast Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce full test-suite runtime toward 60–80 seconds and add a PR fast lane that runs all tests not marked `slow`.

**Architecture:** Keep the full suite as the source of truth. Add one behavior-changing marker, `slow`, and use it only for tests that are too expensive for PR feedback but still required on `dev`/`main`. Consolidate only the largest duplicate areas: registrations admin/view tests, parent visual/copy contracts, and billing/admin render tests.

**Tech Stack:** Python 3.12+, Django 5.x, pytest, pytest-django, uv, Woodpecker CI. No new dependencies.

---

## Current Baseline

Measured on 2026-07-02 in the current checkout:

- `uv run pytest -q --durations=50` → `1547 passed`, `123.64s`.
- `tests/` contains 175 `test_*.py` files and 30,171 LOC.
- `tests/registrations/` is the largest hotspot: 63 files and 16,230 LOC.
- Slowest individual tests are mostly OCR failure path and Django admin page/action tests, but many ~0.5s admin tests add up.

The working tree already contains unrelated uncommitted changes. Implementation must avoid changing or depending on those files except where explicitly listed below.

---

## Design Decisions

### Test lane contract

```text
PR event        -> uv run pytest -q -m "not slow"
dev/main push   -> uv run pytest -q
manual event    -> uv run pytest -q
local fast      -> uv run pytest -q -m "not slow"
local full      -> uv run pytest -q
```

Why: PRs get quick feedback; deploy branches still get full safety.

### Marker model

Use these markers:

- `slow`: excluded from PR fast lane; runs in the full suite.
- `admin_view`: Django admin render/action coverage. Label only; does not affect selection by itself.
- `external_contract`: adapter/provider contract coverage. Label only; does not affect selection by itself.

Only `slow` changes behavior. `uv run pytest -q -m "not slow"` runs every unmarked test and every test that has labels other than `slow`.

### Consolidation model

Consolidate only high-value duplication:

1. registrations admin/view tests;
2. parent visual/copy/template contract tests;
3. billing/admin sync and render tests;
4. repeated DB-heavy bootstrap in fixtures/builders.

Do not refactor production code for this work.

### Coverage preservation rules

Before deleting or merging a test:

1. identify the exact behavior assertion;
2. move the assertion into a consolidated parametrized test;
3. run focused old and new tests while both exist;
4. delete only duplicate coverage.

Never mark the only test for a security, money, document access, audit, migration, or data-loss path as `slow` unless a fast lower-level test covers the same risk.

---

## File Structure

### Create

- `docs/testing.md` — developer-facing test lane and marker guide.
- `tests/deployment/test_test_lanes_contract.py` — contract tests for pytest marker config and Woodpecker lane selection.

### Modify

- `pyproject.toml` — add pytest marker declarations.
- `.woodpecker.yml` — run fast lane on PR, full suite on `dev`/`main`/manual.
- `AGENTS.md` — point test command guidance to `docs/testing.md`.
- selected files under `tests/registrations/` — add markers and consolidate duplicate tests.
- selected files under `tests/billing/` — add markers and consolidate duplicate admin tests.
- selected files under `tests/integrations/` — add `external_contract`; add `slow` only if measurement still misses fast-lane target.

---

## Task 1: Add Test Lane Contract Tests

**Files:**
- Create: `tests/deployment/test_test_lanes_contract.py`

- [ ] **Step 1: Write failing tests**

Create `tests/deployment/test_test_lanes_contract.py`:

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pytest_markers_are_documented():
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert "[tool.pytest.ini_options]" in pyproject
    assert "slow:" in pyproject
    assert "admin_view:" in pyproject
    assert "external_contract:" in pyproject


def test_woodpecker_pr_uses_fast_test_lane():
    ci_config = (ROOT / ".woodpecker.yml").read_text()

    assert 'CI_PIPELINE_EVENT" = "pull_request"' in ci_config
    assert 'uv run pytest -q -m "not slow"' in ci_config


def test_woodpecker_pushes_keep_full_test_suite():
    ci_config = (ROOT / ".woodpecker.yml").read_text()

    assert "else" in ci_config
    assert "uv run pytest -q" in ci_config
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/deployment/test_test_lanes_contract.py -q
```

Expected: at least `test_pytest_markers_are_documented` and `test_woodpecker_pr_uses_fast_test_lane` fail.

- [ ] **Step 3: Do not commit yet**

This task creates the red phase only. Commit after Task 2 makes it green.

---

## Task 2: Add Marker Config and CI Fast Lane

**Files:**
- Modify: `pyproject.toml`
- Modify: `.woodpecker.yml`
- Test: `tests/deployment/test_test_lanes_contract.py`

- [ ] **Step 1: Add pytest marker config**

Append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: excluded from PR fast lane; runs in full suite",
    "admin_view: Django admin render/action coverage",
    "external_contract: adapter/provider contract coverage",
]
```

If `[tool.pytest.ini_options]` already exists, merge these marker declarations into it instead of creating a second section.

- [ ] **Step 2: Update Woodpecker test command**

Replace the `test` step commands:

```yaml
    commands:
      - uv sync --frozen
      - uv run pytest -q
```

with:

```yaml
    commands:
      - uv sync --frozen
      - |
        if [ "$CI_PIPELINE_EVENT" = "pull_request" ]; then
          uv run pytest -q -m "not slow"
        else
          uv run pytest -q
        fi
```

Keep lint/typecheck and build steps unchanged.

- [ ] **Step 3: Run contract tests**

Run:

```bash
uv run pytest tests/deployment/test_test_lanes_contract.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run full suite once**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass. Runtime should be close to the baseline because no tests are marked yet.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .woodpecker.yml tests/deployment/test_test_lanes_contract.py
git commit -m "test: add pytest fast lane contract"
```

---

## Task 3: Document Test Lanes

**Files:**
- Create: `docs/testing.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Create docs/testing.md**

Create `docs/testing.md`:

```markdown
# Testing

## Commands

Run the fast local lane:

```bash
uv run pytest -q -m "not slow"
```

Run the full suite:

```bash
uv run pytest -q
```

Run lint and type checks:

```bash
uv run ruff check .
uv run mypy .
```

## CI lanes

Pull requests run the fast lane:

```bash
uv run pytest -q -m "not slow"
```

Pushes to `dev` and `main` run the full suite:

```bash
uv run pytest -q
```

## Markers

- `slow` — excluded from the PR fast lane; still runs in the full suite.
- `admin_view` — Django admin render/action coverage. Label only.
- `external_contract` — adapter/provider contract coverage. Label only.

Only `slow` changes test selection.

## Rules for using `slow`

Use `slow` for expensive tests that are valuable in the full suite but not needed for every PR feedback cycle.

Do not mark the only coverage for these paths as `slow` unless a fast lower-level test covers the same risk:

- security permissions;
- billing money calculations;
- document access controls;
- audit writes;
- migrations;
- data-loss prevention;
- external payload builders.

Prefer one fast service/unit test plus one slow end-to-end admin/view test over many repeated slow admin/view tests.
```

- [ ] **Step 2: Update AGENTS.md commands section**

In `AGENTS.md`, near the existing test commands, add:

```markdown
Testing lanes:
- Fast local/PR lane: `uv run pytest -q -m "not slow"`
- Full suite: `uv run pytest -q`
- Marker rules live in `docs/testing.md`.
```

- [ ] **Step 3: Run docs-adjacent checks**

Run:

```bash
uv run pytest tests/deployment/test_test_lanes_contract.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add docs/testing.md AGENTS.md
git commit -m "docs: document test lanes"
```

---

## Task 4: Mark Obvious Slow Admin View Tests

**Files:**
- Modify selected `tests/registrations/test_admin_*.py`
- Modify selected `tests/billing/test_*admin*.py`
- Modify selected `tests/agreements/test_admin_*.py`
- Modify selected `tests/members/test_admin_*.py`

- [ ] **Step 1: Add module-level marks to full-page admin tests**

For files that primarily render Django admin pages or execute admin UI actions, add near imports:

```python
import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]
```

If the file already has `pytestmark = pytest.mark.django_db`, replace it with the list above.

Start with these files if present:

```text
tests/registrations/test_admin_inline_preview.py
tests/registrations/test_admin_change_page_panels.py
tests/registrations/test_admin_review_group_assignment_ui.py
tests/registrations/test_admin_review_agreement_ui.py
tests/registrations/test_admin_agreement_lifecycle.py
tests/registrations/test_admin_changelist_quick_actions.py
tests/billing/test_billing_adjustment_admin.py
tests/billing/test_billing_admin_payment_sync.py
tests/billing/test_admin_confirm_action.py
tests/agreements/test_admin_sync_health.py
tests/members/test_admin_group_merge.py
```

Do not mark pure helper/unit admin tests that only call small functions and do not render admin pages.

- [ ] **Step 2: Run fast lane and collect durations**

Run:

```bash
uv run pytest -q -m "not slow" --durations=25
```

Expected: pass. Record total runtime in the final implementation summary.

- [ ] **Step 3: Run full suite**

Run:

```bash
uv run pytest -q --durations=25
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/registrations tests/billing tests/agreements tests/members
git commit -m "test: mark slow admin view coverage"
```

---

## Task 5: Consolidate Parent Visual and Copy Contract Tests

**Files:**
- Modify: `tests/registrations/test_visual_contract.py`
- Modify: `tests/registrations/test_parent_surface_copy_contract.py`
- Modify nearby parent-surface tests only if duplicate assertions are moved.

- [ ] **Step 1: Identify duplicate broad rendered-page assertions**

Search within the two files for repeated checks of:

```text
fk-
logo
stylesheet
English leakage
Latvian phrase presence
mobile CSS snippets
```

Keep one fast smoke test per page/surface. Mark broad matrix scans `slow`.

- [ ] **Step 2: Convert repeated page checks to parametrized tests**

Use this shape for repeated GET assertions:

```python
import pytest


@pytest.mark.parametrize(
    ("url", "expected_text"),
    [
        ("/register/", "Reģistrācija"),
        ("/register/verify/", "kods"),
        ("/portal/", "Sveiks"),
    ],
)
def test_parent_surfaces_render_fast_smoke(client, url, expected_text):
    response = client.get(url)

    assert response.status_code in {200, 302}
    assert expected_text in response.content.decode()
```

Use the actual existing fixtures and expected Latvian phrases from the current tests. Do not weaken ownership/auth assertions into only `200` checks if the old test asserted redirects or login state.

- [ ] **Step 3: Mark exhaustive copy scan slow**

For the broad English-token sweep in `test_parent_surface_copy_contract.py`, add:

```python
@pytest.mark.slow
```

Keep at least one fast static/template copy smoke if it is cheap and not DB-heavy.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/registrations/test_visual_contract.py tests/registrations/test_parent_surface_copy_contract.py -q
```

Expected: pass.

- [ ] **Step 5: Run lanes**

Run:

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add tests/registrations/test_visual_contract.py tests/registrations/test_parent_surface_copy_contract.py
git commit -m "test: consolidate parent surface contracts"
```

---

## Task 6: Consolidate Registrations Admin Action Tests

**Files:**
- Modify: `tests/registrations/test_admin_review_actions.py`
- Modify: `tests/registrations/test_admin_review_agreement_ui.py`
- Modify: `tests/registrations/test_admin_agreement_lifecycle.py`
- Modify: `tests/registrations/test_admin_changelist_quick_actions.py`

- [ ] **Step 1: Group same-action tests by endpoint/action**

Look for repeated POST shapes like:

```python
client.post(url, {"action": "mark_agreement_sent"})
client.post(url, {"action": "mark_agreement_signed"})
client.post(url, {"action": "void_agreement", ...})
```

Move repeated success cases into one parametrized test per endpoint when assertions differ only by resulting state/message/redirect.

- [ ] **Step 2: Keep fast service coverage separate**

Do not move service-level tests from `tests/agreements/test_lifecycle_services.py` or billing service tests into admin files. Admin tests should verify routing/form contract only.

- [ ] **Step 3: Replace duplicate admin lifecycle success checks with parameterization**

Use this pattern where current fixtures allow it:

```python
@pytest.mark.parametrize(
    ("action", "expected_state"),
    [
        ("mark_agreement_sent", "sent"),
        ("mark_agreement_signed", "signed"),
    ],
)
def test_agreement_quick_actions_transition_state(staff_client, agreement, action, expected_state):
    url = agreement.application_admin_action_url

    response = staff_client.post(url, {"action": action})

    agreement.refresh_from_db()
    assert response.status_code in {302, 303}
    assert agreement.state == expected_state
```

Adapt names to the actual current fixtures and URL helpers. Do not invent `agreement.application_admin_action_url`; use the URL construction already present in the file.

- [ ] **Step 4: Delete exact duplicates only**

Delete a test only when the parametrized test covers the same:

- action value;
- expected state;
- redirect target or message contract;
- audit side effect if the old test asserted one.

- [ ] **Step 5: Run focused registrations admin tests**

Run:

```bash
uv run pytest tests/registrations/test_admin_review_actions.py tests/registrations/test_admin_review_agreement_ui.py tests/registrations/test_admin_agreement_lifecycle.py tests/registrations/test_admin_changelist_quick_actions.py -q
```

Expected: pass.

- [ ] **Step 6: Run lanes**

Run:

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass.

- [ ] **Step 7: Commit**

```bash
git add tests/registrations/test_admin_review_actions.py tests/registrations/test_admin_review_agreement_ui.py tests/registrations/test_admin_agreement_lifecycle.py tests/registrations/test_admin_changelist_quick_actions.py
git commit -m "test: consolidate registration admin actions"
```

---

## Task 7: Consolidate Billing Admin Render Tests

**Files:**
- Modify: `tests/billing/test_admin_confirm_action.py`
- Modify: `tests/billing/test_admin_confirm_audit.py`
- Modify: `tests/billing/test_billing_admin_payment_sync.py`
- Modify: `tests/billing/test_billing_adjustment_admin.py`

- [ ] **Step 1: Separate service assertions from admin surface assertions**

Keep fast tests for:

- status transition service behavior;
- audit event creation;
- enqueue helper calls;
- permission checks when they are cheap and direct.

Mark full admin page render/action checks `slow`.

- [ ] **Step 2: Parameterize repeated admin action skip/enqueue cases**

Use one parametrized test for repeated selected-action outcomes where possible:

```python
@pytest.mark.parametrize(
    ("initial_status", "should_enqueue"),
    [
        ("draft", False),
        ("confirmed", True),
    ],
)
def test_payment_sync_admin_action_filters_records(staff_client, billing_record, initial_status, should_enqueue, monkeypatch):
    billing_record.status = initial_status
    billing_record.save(update_fields=["status", "updated_at"])

    calls = []
    monkeypatch.setattr(
        "apps.integrations.tasks.enqueue_sync_billing_record_payments",
        lambda record_id: calls.append(record_id),
    )

    # Use the real admin action invocation already present in the current test file.

    assert bool(calls) is should_enqueue
```

Adapt field names and action invocation to current tests. Do not duplicate this exact snippet if existing helper is shorter.

- [ ] **Step 3: Run focused billing admin tests**

Run:

```bash
uv run pytest tests/billing/test_admin_confirm_action.py tests/billing/test_admin_confirm_audit.py tests/billing/test_billing_admin_payment_sync.py tests/billing/test_billing_adjustment_admin.py -q
```

Expected: pass.

- [ ] **Step 4: Run lanes**

Run:

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add tests/billing/test_admin_confirm_action.py tests/billing/test_admin_confirm_audit.py tests/billing/test_billing_admin_payment_sync.py tests/billing/test_billing_adjustment_admin.py
git commit -m "test: consolidate billing admin coverage"
```

---

## Task 8: Label External Contract Tests

**Files:**
- Modify selected files under `tests/integrations/`

- [ ] **Step 1: Add `external_contract` marker to adapter/provider tests**

Add module-level marker to tests that verify provider payload/response contracts:

```python
import pytest

pytestmark = pytest.mark.external_contract
```

If the file already has `pytestmark = pytest.mark.django_db`, use:

```python
pytestmark = [pytest.mark.django_db, pytest.mark.external_contract]
```

Likely files:

```text
tests/integrations/test_invoice_ninja_provider.py
tests/integrations/test_docuseal_provider.py
tests/integrations/test_tiny_idp_adapter.py
tests/integrations/test_tiny_idp_post_document.py
tests/integrations/test_invoice_payment_readback.py
tests/integrations/test_invoice_credit_adapter.py
```

- [ ] **Step 2: Add `slow` only if measurement still misses target**

If fast lane remains above 45 seconds after Tasks 4–7, mark only broad provider matrix tests as both `external_contract` and `slow`. Keep request-builder and error-classification tests fast.

- [ ] **Step 3: Run integration tests**

Run:

```bash
uv run pytest tests/integrations -q
```

Expected: pass.

- [ ] **Step 4: Run lanes**

Run:

```bash
uv run pytest -q -m "not slow" --durations=25
uv run pytest -q --durations=25
```

Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integrations
git commit -m "test: label external contract tests"
```

---

## Task 9: Final Measurement and Documentation Update

**Files:**
- Modify: `docs/testing.md`
- Modify: `docs/milestones.md` only if final measured numbers are materially useful to record.

- [ ] **Step 1: Run final fast lane**

Run:

```bash
uv run pytest -q -m "not slow" --durations=50
```

Expected: pass. Record:

- number of tests run;
- runtime;
- slowest remaining tests.

- [ ] **Step 2: Run final full suite**

Run:

```bash
uv run pytest -q --durations=50
```

Expected: pass. Record:

- number of tests run;
- runtime;
- slowest remaining tests.

- [ ] **Step 3: Run lint and types**

Run:

```bash
uv run ruff check .
uv run mypy .
```

Expected: both pass.

- [ ] **Step 4: Update docs/testing.md with measured results**

Add a short section:

```markdown
## Current measured runtime

Measured on 2026-07-02:

- Fast lane: `<N> passed`, `<seconds>s`.
- Full suite: `<N> passed`, `<seconds>s`.
```

Use real command output.

- [ ] **Step 5: Update docs/milestones.md if useful**

If the final result changes the project test baseline materially, add one bullet in the current-status area:

```markdown
- Test suite fast lane delivered (2026-07-02): PRs run `uv run pytest -q -m "not slow"`; `dev`/`main` keep the full suite. Measured fast lane: `<runtime>`; full suite: `<runtime>`.
```

Do not rewrite milestone history.

- [ ] **Step 6: Commit**

```bash
git add docs/testing.md docs/milestones.md
git commit -m "docs: record test lane baseline"
```

---

## Acceptance Criteria

- `uv run pytest -q -m "not slow"` passes.
- `uv run pytest -q` passes.
- `uv run ruff check .` passes.
- `uv run mypy .` passes.
- PR CI runs fast lane only.
- `dev`, `main`, and manual CI runs full suite.
- pytest marker warnings are absent.
- Full suite runtime is reduced toward 60–80 seconds, or any miss is documented with slowest remaining tests.
- Fast lane target is 45 seconds or less, or any miss is documented with slowest remaining tests.
- No unique security, billing money, audit, document access, migration, or data-loss coverage is removed from the full suite.

---

## Self-Review

- Spec coverage: requirements for bigger consolidation, fast lane, PR-only fast lane, dev/main full suite, and marker use are covered.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type/name consistency: marker names are `slow`, `admin_view`, and `external_contract` throughout.
- Scope check: production code changes are explicitly out of scope.

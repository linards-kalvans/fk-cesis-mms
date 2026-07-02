# Testing

## Commands

Fast local lane (matches the PR CI lane):

```bash
uv run pytest -q -m "not slow"
```

Full suite (matches `dev` / `main` / manual CI lanes):

```bash
uv run pytest -q
```

Lint + type check:

```bash
uv run ruff check .
uv run mypy .
```

## CI lanes

| Event                        | Command                            |
| ---------------------------- | ---------------------------------- |
| `pull_request`               | `uv run pytest -q -m "not slow"`   |
| push to `dev` / `main`       | `uv run pytest -q`                 |
| `manual`                     | `uv run pytest -q`                 |
| local fast feedback          | `uv run pytest -q -m "not slow"`   |
| local full safety            | `uv run pytest -q`                 |

The lane is selected in `.woodpecker.yml` from `$CI_PIPELINE_EVENT`.

## Markers

Declared in `pyproject.toml` under `[tool.pytest.ini_options]`.

- `slow` — excluded from the PR fast lane; still runs in the full suite.
  Use for expensive tests that are valuable in the full suite but not needed
  for every PR feedback cycle.
- `admin_view` — Django admin render/action coverage. **Label only**; does
  not change selection.
- `external_contract` — adapter / provider contract coverage (Invoice
  Ninja, DocuSeal, tiny-IDP). **Label only**; does not change selection.

Only `slow` changes which tests run. `uv run pytest -q -m "not slow"` runs
every unmarked test and every test labelled only with `admin_view` /
`external_contract`.

## Rules for using `slow`

Prefer `slow` on broad admin / view / contract matrix scans, not on the
only test for a high-risk path.

Do not mark the only coverage for these paths as `slow` unless a fast
lower-level test covers the same risk:

- security permissions;
- billing money calculations;
- document access controls;
- audit writes;
- migrations;
- data-loss prevention;
- external payload builders.

Prefer one fast service / unit test plus one slow end-to-end admin / view
test over many repeated slow admin / view tests.

## Lanes (CI contract)

The contract is enforced by `tests/deployment/test_test_lanes_contract.py`:

- `pyproject.toml` documents the three markers;
- `.woodpecker.yml` selects the fast lane on `pull_request`;
- `.woodpecker.yml` keeps the full suite on every other event.

If you add a new marker, register it in `pyproject.toml` and update both
this file and the contract test.

## Current measured runtime

Measured on 2026-07-02:

- Fast lane: 1289 passed, 246 deselected, 49.55s.
- Full suite: 1535 passed, 107.86s.

The fast lane is still above the aspirational 45s target, and the full suite
is still above the 60–80s target after the safe duplicate-test consolidation.
Slowest remaining tests from the final full-suite run:

- `tests/registrations/test_parent_ocr_prefill_flow.py::TestManualFallbackOnOcrFailure::test_workspace_shows_fallback_on_ocr_failure` — 1.87s
- `tests/accounts/test_admin_bootstrap.py::TestEnsureAdminUser::test_creates_superuser` — 1.25s setup
- `tests/registrations/test_parent_ocr_prefill_flow.py::TestManualFallbackOnOcrFailure::test_form_still_editable_after_ocr_failure` — 1.22s
- `tests/accounts/test_admin_bootstrap.py::TestEnsureAdminUser::test_rerun_updates_password` — 0.68s
- `tests/registrations/test_admin_review_actions.py::test_reject_on_approved_application_is_blocked_by_guard` — 0.55s

These stayed in the fast lane because they are not broad duplicate admin-view
matrix tests; mark them `slow` only after adding equivalent fast lower-level
coverage. External contract tests are labelled with `external_contract` but not
`slow` because they were not among the slowest remaining fast-lane tests.

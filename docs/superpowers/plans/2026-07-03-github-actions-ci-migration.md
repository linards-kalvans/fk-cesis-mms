# GitHub Actions CI Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Woodpecker/Codeberg CI with GitHub Actions publishing the same two-channel image tags to GHCR.

**Architecture:** Use one GitHub Actions workflow for lint, tests, and branch-specific image publishing. Keep current test-lane and version-tag semantics. Update only current CI/runtime contract docs and tests; leave deployment manual and infra-owned by `fk-cesis`.

**Tech Stack:** GitHub Actions, GHCR, Docker Buildx, uv, Python 3.12, pytest, ruff, mypy, PostgreSQL service container.

---

## File map

- Delete: `.woodpecker.yml` — removes legacy Woodpecker source of truth.
- Create: `.github/workflows/ci.yml` — GitHub Actions workflow for lint/test/build/push.
- Modify: `tests/deployment/test_test_lanes_contract.py` — contract tests for PR fast lane and push/manual full lane in GitHub Actions.
- Modify: `tests/deployment/test_runtime_split_contract.py` — contract tests for GHCR image name, workflow presence, build/push, no deploy webhooks, and Woodpecker removal.
- Modify: `compose.yaml` — default local-smoke image changes to GHCR.
- Modify: `docs/testing.md` — CI lane source changes from Woodpecker to GitHub Actions.
- Modify: `docs/deployment.md` — registry image changes to GHCR.
- Modify: `docs/runtime-contract.md` — registry image changes to GHCR.
- Modify: `AGENTS.md` — current CI/registry guidance changes to GitHub Actions/GHCR.

## Design decisions

### One workflow file

Use `.github/workflows/ci.yml` with three jobs: `lint`, `test`, and `build-and-push`.

Why: the repo has one CI contract. Splitting workflows adds drift risk without adding value.

### Build only after lint and tests

`build-and-push` must declare:

```yaml
needs: [lint, test]
```

Why: do not publish unverified images.

### No image publish for pull requests

`build-and-push` must have an `if` guard equivalent to:

```yaml
if: github.event_name != 'pull_request' && (github.ref_name == 'dev' || github.ref_name == 'main')
```

Why: PRs are validation-only and should not publish registry images.

### GHCR auth

Use `GITHUB_TOKEN` with workflow permissions:

```yaml
permissions:
  contents: read
  packages: write
```

Why: no repo secret is needed for publishing to this repository's package namespace.

### Version tag math

Preserve the existing main-branch immutable tag calculation:

```bash
MAJOR=$(tr -d '[:space:]' < VERSION)
LAST_VERSION_SHA=$(git log -1 --format=%H -- VERSION)
MINOR_OFFSET=$(git rev-list --count "$LAST_VERSION_SHA..HEAD")
MINOR=$((MINOR_OFFSET + 1))
VERSION_TAG="$MAJOR.$MINOR"
```

Why: this preserves the current rollback tag model exactly.

## Task 1: Update failing contract tests first

**Files:**
- Modify: `tests/deployment/test_test_lanes_contract.py`
- Modify: `tests/deployment/test_runtime_split_contract.py`

- [ ] **Step 1: Update `tests/deployment/test_test_lanes_contract.py` docstring and workflow path**

Replace the top docstring and add a workflow path constant:

```python
"""Contract tests for pytest marker config and GitHub Actions lane selection.

These verify the test-lane contract from:
  docs/superpowers/plans/2026-07-02-test-suite-consolidation-fast-lane.md

All tests use plain pathlib reads + string assertions. No YAML/TOML parser.
No pytest-django database requirement.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
```

- [ ] **Step 2: Replace Woodpecker lane tests with GitHub Actions lane tests**

Use these test functions:

```python
def test_github_actions_pr_uses_fast_test_lane():
    ci_config = WORKFLOW.read_text()

    assert "pull_request" in ci_config
    assert 'uv run pytest -q -m "not slow"' in ci_config


def test_github_actions_pushes_keep_full_test_suite():
    ci_config = WORKFLOW.read_text()

    assert "github.event_name == 'pull_request'" in ci_config
    assert "uv run pytest -q" in ci_config
```

Keep `test_pytest_markers_are_documented` unchanged.

- [ ] **Step 3: Update runtime contract registry image assertion**

In `tests/deployment/test_runtime_split_contract.py`, update `TestRuntimeContractDoc.test_registry_image_anchor` to:

```python
def test_registry_image_anchor(self):
    """Must document the registry image name."""
    content = self._content()
    assert "ghcr.io/linards-kalvans/fk-cesis-mms" in content, (
        "runtime-contract.md must mention the GHCR registry image"
    )
```

- [ ] **Step 4: Replace Woodpecker CI contract class**

Replace `TestWoodpeckerCIManualDeploy` with:

```python
class TestGitHubActionsCIManualDeploy:
    """GitHub Actions must build/push images and leave deployment manual."""

    @property
    def workflow_path(self) -> Path:
        return REPO_ROOT / ".github" / "workflows" / "ci.yml"

    @property
    def content(self) -> str:
        return _read_all(self.workflow_path)

    def test_workflow_exists_and_woodpecker_is_removed(self):
        """GitHub Actions must replace the legacy Woodpecker pipeline."""
        assert self.workflow_path.is_file(), (
            ".github/workflows/ci.yml must exist"
        )
        assert not (REPO_ROOT / ".woodpecker.yml").exists(), (
            ".woodpecker.yml must be removed after CI migration"
        )

    def test_build_and_push_pipeline_preserved(self):
        """Build/publish pipeline must still be present."""
        assert "build-and-push" in self.content, (
            "GitHub Actions workflow must contain build-and-push job"
        )
        assert "docker/build-push-action" in self.content, (
            "GitHub Actions workflow must use Docker Buildx publishing"
        )
        assert "ghcr.io/linards-kalvans/fk-cesis-mms" in self.content, (
            "GitHub Actions workflow must publish the GHCR image"
        )

    def test_pull_requests_do_not_publish_images(self):
        """Pull requests must run checks only and skip registry publishing."""
        assert "github.event_name != 'pull_request'" in self.content, (
            "build-and-push must exclude pull_request events"
        )

    def test_deploy_notify_steps_removed(self):
        """Deploy webhook steps must be absent while deployment is manual."""
        assert "notify-dev" not in self.content, (
            "GitHub Actions workflow must not call the dev deploy webhook"
        )
        assert "notify-prod" not in self.content, (
            "GitHub Actions workflow must not call the prod deploy webhook"
        )

    def test_deploy_webhook_secrets_removed(self):
        """Deploy webhook secrets must not be referenced by CI."""
        forbidden = [
            "DEV_DEPLOY_WEBHOOK_URL",
            "DEV_DEPLOY_WEBHOOK_SECRET",
            "PROD_DEPLOY_WEBHOOK_URL",
            "PROD_DEPLOY_WEBHOOK_SECRET",
        ]
        for secret_name in forbidden:
            assert secret_name not in self.content, (
                f"GitHub Actions workflow must not reference {secret_name}"
            )
```

- [ ] **Step 5: Run tests and confirm red phase**

Run:

```bash
uv run pytest -q tests/deployment/test_test_lanes_contract.py tests/deployment/test_runtime_split_contract.py
```

Expected: FAIL because `.github/workflows/ci.yml` does not exist yet, `.woodpecker.yml` still exists, and docs still reference Codeberg.

## Task 2: Add GitHub Actions workflow and remove Woodpecker

**Files:**
- Create: `.github/workflows/ci.yml`
- Delete: `.woodpecker.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

Create the file with this content:

```yaml
name: CI

on:
  pull_request:
  push:
    branches:
      - dev
      - main
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  IMAGE_NAME: ghcr.io/linards-kalvans/fk-cesis-mms

jobs:
  lint:
    name: Lint and type check
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run ruff
        run: uv run ruff check .

      - name: Run mypy
        run: uv run mypy .

  test:
    name: Test
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:18-alpine
        env:
          POSTGRES_DB: fkmms
          POSTGRES_USER: fkmms
          POSTGRES_PASSWORD: fkmms
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U fkmms -d fkmms"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DJANGO_SECRET_KEY: ci-not-secret
      DJANGO_DEBUG: "false"
      DATABASE_URL: postgres://fkmms:fkmms@localhost:5432/fkmms
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run tests
        run: |
          if [ "${{ github.event_name }}" = "pull_request" ]; then
            uv run pytest -q -m "not slow"
          else
            uv run pytest -q
          fi

  build-and-push:
    name: Build and push image
    runs-on: ubuntu-latest
    needs: [lint, test]
    if: github.event_name != 'pull_request' && (github.ref_name == 'dev' || github.ref_name == 'main')
    steps:
      - name: Check out repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Prepare image tags
        id: tags
        run: |
          if [ "${{ github.ref_name }}" = "dev" ]; then
            printf 'tags=%s:dev\n' "$IMAGE_NAME" >> "$GITHUB_OUTPUT"
            exit 0
          fi

          MAJOR=$(tr -d '[:space:]' < VERSION)
          LAST_VERSION_SHA=$(git log -1 --format=%H -- VERSION)
          MINOR_OFFSET=$(git rev-list --count "$LAST_VERSION_SHA..HEAD")
          MINOR=$((MINOR_OFFSET + 1))
          VERSION_TAG="$MAJOR.$MINOR"
          {
            echo 'tags<<EOF'
            printf '%s:main\n' "$IMAGE_NAME"
            printf '%s:%s\n' "$IMAGE_NAME" "$VERSION_TAG"
            echo 'EOF'
          } >> "$GITHUB_OUTPUT"
          echo "Computed version tag $VERSION_TAG"

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Dockerfile
          push: true
          tags: ${{ steps.tags.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 2: Delete `.woodpecker.yml`**

Remove the file entirely.

- [ ] **Step 3: Run targeted tests**

Run:

```bash
uv run pytest -q tests/deployment/test_test_lanes_contract.py tests/deployment/test_runtime_split_contract.py
```

Expected: FAIL only on docs/compose references if Task 3 is not complete yet.

## Task 3: Update current docs and compose defaults

**Files:**
- Modify: `compose.yaml`
- Modify: `docs/testing.md`
- Modify: `docs/deployment.md`
- Modify: `docs/runtime-contract.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update `compose.yaml` image defaults**

Replace both occurrences of:

```yaml
image: ${FK_CESIS_MMS_IMAGE:-codeberg.org/linards-kalvans/fk-cesis-mms}:${IMAGE_TAG:-dev}
```

with:

```yaml
image: ${FK_CESIS_MMS_IMAGE:-ghcr.io/linards-kalvans/fk-cesis-mms}:${IMAGE_TAG:-dev}
```

Do not change any service commands, ports, volumes, or health checks.

- [ ] **Step 2: Update `docs/testing.md` CI references**

Replace line-level wording so the CI section says:

```markdown
The lane is selected in `.github/workflows/ci.yml` from `github.event_name`.
```

In the lane contract list, replace:

```markdown
- `.woodpecker.yml` selects the fast lane on `pull_request`;
- `.woodpecker.yml` keeps the full suite on every other event.
```

with:

```markdown
- `.github/workflows/ci.yml` selects the fast lane on `pull_request`;
- `.github/workflows/ci.yml` keeps the full suite on every other event.
```

- [ ] **Step 3: Update `docs/deployment.md` image contract**

Replace:

```markdown
- Registry image: `codeberg.org/linards-kalvans/fk-cesis-mms`
```

with:

```markdown
- Registry image: `ghcr.io/linards-kalvans/fk-cesis-mms`
```

- [ ] **Step 4: Update `docs/runtime-contract.md` image contract**

Replace:

```markdown
- Registry image: `codeberg.org/linards-kalvans/fk-cesis-mms`
```

with:

```markdown
- Registry image: `ghcr.io/linards-kalvans/fk-cesis-mms`
```

- [ ] **Step 5: Update `AGENTS.md` current CI status**

In the M6 containerization section, replace the current two-channel CI and registry wording with:

```markdown
  - **Two-channel CI** (`.github/workflows/ci.yml`): lint + test on every push and PR. PRs run the fast test lane. Push to `dev` → build `ghcr.io/linards-kalvans/fk-cesis-mms:dev` (floating). Push to `main` → read `VERSION` (major), count commits since `VERSION` last changed (minor), build `:main` *and* `:<major>.<minor>` immutable. Deployment is manual for now; runtime ownership stays in `https://github.com/linards-kalvans/fk-cesis`.
```

In the branch strategy rules, replace Codeberg/Woodpecker wording with GitHub Actions/GHCR wording while preserving the branch strategy:

```markdown
- **Two-channel branch strategy (2026-05-26+):** all new development lands on `dev`. `main` is the release branch — merged into from `dev` via PR only after verification on the dev server. Every push to `dev` rebuilds the floating GHCR `:dev` image; every push to `main` rebuilds GHCR `:main` *and* an immutable `:<major>.<minor>` version tag (`<major>` from `VERSION` file, `<minor>` resets on major bump then auto-increments per commit). Dev server tracks `:dev`; prod server tracks `:main` with the option to pin to a `:<X.Y>` for rollback.
```

Do not rewrite historical sections in archived docs.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
uv run pytest -q tests/deployment/test_test_lanes_contract.py tests/deployment/test_runtime_split_contract.py
```

Expected: PASS.

## Task 4: Final verification

**Files:**
- All changed files from Tasks 1-3.

- [ ] **Step 1: Run targeted deployment contract tests**

Run:

```bash
uv run pytest -q tests/deployment/test_test_lanes_contract.py tests/deployment/test_runtime_split_contract.py
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run ruff**

Run:

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 4: Run mypy**

Run:

```bash
uv run mypy .
```

Expected: PASS.

- [ ] **Step 5: Inspect git diff**

Run:

```bash
git status --short
git diff -- .github/workflows/ci.yml tests/deployment/test_test_lanes_contract.py tests/deployment/test_runtime_split_contract.py compose.yaml docs/testing.md docs/deployment.md docs/runtime-contract.md AGENTS.md docs/superpowers/specs/2026-07-03-github-actions-ci-migration-design.md docs/superpowers/plans/2026-07-03-github-actions-ci-migration.md
```

Expected: only planned files changed.

## Self-review

- Spec coverage: every acceptance criterion from `docs/superpowers/specs/2026-07-03-github-actions-ci-migration-design.md` maps to Tasks 1-4.
- Placeholder scan: no placeholders remain.
- Type/name consistency: workflow path, image name, test class names, and commands are consistent across tasks.

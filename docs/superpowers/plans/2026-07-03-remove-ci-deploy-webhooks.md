# Remove CI Deploy Webhooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove deploy webhook calls from Woodpecker while preserving lint/test/image build publishing.

**Architecture:** This is a CI contract change only. Tests read `.woodpecker.yml` as text and assert the manual-deploy stance; the config then removes deploy notification steps and secrets references.

**Tech Stack:** Woodpecker CI YAML, pytest text-contract tests.

---

## File structure

- Modify: `tests/deployment/test_runtime_split_contract.py`
  - Replace webhook-as-optional assertions with webhook-absent assertions.
- Modify: `.woodpecker.yml`
  - Remove deploy webhook comments, secret references, `notify-dev`, and `notify-prod`.
- Create: none.

## Task 1: Update deployment contract tests first

**Files:**
- Modify: `tests/deployment/test_runtime_split_contract.py`

- [ ] **Step 1: Replace the Woodpecker test class docstring and tests**

Replace `TestWoodpeckerCIComments` with `TestWoodpeckerCIManualDeploy`:

```python
class TestWoodpeckerCIManualDeploy:
    """.woodpecker.yml must build/push images and leave deployment manual."""

    @property
    def content(self) -> str:
        return _read_all(REPO_ROOT / ".woodpecker.yml")

    def test_build_and_push_pipeline_preserved(self):
        """Build/publish pipeline must still be present (build-and-push, prepare-tags)."""
        assert "build-and-push" in self.content, (
            ".woodpecker.yml must still contain build-and-push step"
        )
        assert "prepare-tags" in self.content, (
            ".woodpecker.yml must still contain prepare-tags step — dev and main"
        )

    def test_deploy_notify_steps_removed(self):
        """Deploy webhook steps must be absent while deployment is manual."""
        assert "notify-dev:" not in self.content, (
            ".woodpecker.yml must not call the dev deploy webhook"
        )
        assert "notify-prod:" not in self.content, (
            ".woodpecker.yml must not call the prod deploy webhook"
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
                f".woodpecker.yml must not reference {secret_name}"
            )
```

- [ ] **Step 2: Run red-phase targeted test**

Run:

```bash
uv run pytest -q tests/deployment/test_runtime_split_contract.py::TestWoodpeckerCIManualDeploy
```

Expected: failure because `.woodpecker.yml` still contains `notify-dev`, `notify-prod`, and deploy webhook secret names.

## Task 2: Remove Woodpecker deploy webhook config

**Files:**
- Modify: `.woodpecker.yml`

- [ ] **Step 1: Update top comments**

Replace lines describing optional notify steps with concise manual-deploy wording:

```yaml
# Deployment runtime is owned by the fk-cesis infrastructure repository.
# This pipeline publishes images only; deployment is manual for now.
```

- [ ] **Step 2: Remove deploy webhook secret docs**

Delete the comment block listing:

```yaml
# Optional handoff webhook secrets, owned by fk-cesis runtime automation:
#   DEV_DEPLOY_WEBHOOK_URL
#   DEV_DEPLOY_WEBHOOK_SECRET
#   PROD_DEPLOY_WEBHOOK_URL
#   PROD_DEPLOY_WEBHOOK_SECRET
#
# The prod webhook secrets can be added later. Until then the notify-prod
# step is wired to `failure: ignore` so a missing secret won't fail the
# build (the :main and :<version> tags are still pushed).
```

- [ ] **Step 3: Delete `notify-dev` step**

Remove the whole YAML step from `notify-dev:` through the end of its `curl` command.

- [ ] **Step 4: Delete `notify-prod` step**

Remove the whole YAML step from `notify-prod:` through the end of its `curl` command.

- [ ] **Step 5: Run green-phase targeted test**

Run:

```bash
uv run pytest -q tests/deployment/test_runtime_split_contract.py::TestWoodpeckerCIManualDeploy
```

Expected: pass.

## Task 3: Verify deployment contract and repo gates

**Files:**
- No code changes unless tests reveal an issue.

- [ ] **Step 1: Run full deployment contract tests**

Run:

```bash
uv run pytest -q tests/deployment/test_runtime_split_contract.py
```

Expected: pass.

- [ ] **Step 2: Run full repo verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```

Expected: all pass.

## Self-review

- Spec coverage: all goals map to Task 1 and Task 2.
- Placeholder scan: no TBD/TODO placeholders.
- Scope: no app webhook, Docker, compose, or infra repo changes.

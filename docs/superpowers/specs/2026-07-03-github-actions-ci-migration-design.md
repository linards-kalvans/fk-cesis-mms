# GitHub Actions CI Migration — Design

Date: 2026-07-03
Status: approved for implementation planning

## Problem

The repository moved from Codeberg back to GitHub, but CI still lives in `.woodpecker.yml` and publishes images to the Codeberg registry. The app repository must run its test lanes and publish Docker images from GitHub Actions instead.

## Goals

- Replace Woodpecker CI with GitHub Actions.
- Preserve the existing two-channel image strategy:
  - pull requests run lint and the fast test lane only;
  - pushes to `dev` build and publish `ghcr.io/linards-kalvans/fk-cesis-mms:dev`;
  - pushes to `main` build and publish `ghcr.io/linards-kalvans/fk-cesis-mms:main` and `ghcr.io/linards-kalvans/fk-cesis-mms:<major>.<minor>`.
- Preserve the existing version-tag math: `<major>` comes from `VERSION`, and `<minor>` is commit count since the last `VERSION` change plus one.
- Keep deployment manual and infra-owned by `fk-cesis`; do not restore webhook deploy steps.
- Update code, docs, and contract tests so they reference GitHub Actions and GHCR instead of Woodpecker and Codeberg.

## Non-goals

- Do not change Docker runtime behavior, container commands, health checks, or compose service topology.
- Do not add production deploy automation.
- Do not change the `fk-cesis` infrastructure repository.
- Do not change test markers or test selection policy.
- Do not add third-party GitHub Actions beyond standard checkout/setup/build/login actions.

## Chosen approach

Use one workflow file: `.github/workflows/ci.yml`.

Workflow jobs:

1. `lint`
   - runs on pull requests, pushes to `dev`/`main`, and manual dispatch;
   - checks out the repository;
   - installs Python 3.12 and uv;
   - runs `uv sync --frozen`, `uv run ruff check .`, and `uv run mypy .`.
2. `test`
   - runs with a Postgres service matching the current CI database contract;
   - uses the fast lane on pull requests: `uv run pytest -q -m "not slow"`;
   - uses the full lane otherwise: `uv run pytest -q`.
3. `build-and-push`
   - depends on `lint` and `test`;
   - runs only for `push` or `workflow_dispatch` on `dev`/`main`;
   - checks out with full history (`fetch-depth: 0`) so the version-tag command can inspect `VERSION` history;
   - logs in to GHCR with `GITHUB_TOKEN`;
   - builds and pushes the Docker image with Docker Buildx;
   - tags `dev` on `dev`, and `main` plus `<major>.<minor>` on `main`.

Delete `.woodpecker.yml` instead of keeping a disabled legacy pipeline.

## Why

GitHub Actions is now the repository-native CI runner. Buildx is the simplest image builder there, so the old Kaniko workaround for Codeberg runner restrictions is unnecessary. A single workflow is enough because the repo has one CI contract: lint, test, and branch-specific image publish.

## Data flow after change

```text
pull request
  -> lint
  -> fast tests
  -> stop; no image push

push / manual on dev
  -> lint
  -> full tests
  -> build Docker image
  -> push ghcr.io/linards-kalvans/fk-cesis-mms:dev

push / manual on main
  -> lint
  -> full tests
  -> compute VERSION-derived tag
  -> build Docker image
  -> push ghcr.io/linards-kalvans/fk-cesis-mms:main
  -> push ghcr.io/linards-kalvans/fk-cesis-mms:<major>.<minor>
```

## Acceptance criteria

- `.woodpecker.yml` is removed.
- `.github/workflows/ci.yml` exists.
- Pull request workflow path contains `uv run pytest -q -m "not slow"`.
- Push/manual workflow path contains `uv run pytest -q`.
- Build job is skipped for pull requests.
- Build job publishes to `ghcr.io/linards-kalvans/fk-cesis-mms`.
- `dev` branch publishes only the `dev` floating tag.
- `main` branch publishes `main` plus the computed immutable `<major>.<minor>` tag.
- CI contract tests read the GitHub Actions workflow, not `.woodpecker.yml`.
- `compose.yaml`, `docs/deployment.md`, `docs/runtime-contract.md`, `docs/testing.md`, and `AGENTS.md` no longer name Woodpecker/Codeberg as the current CI/registry contract.
- Deployment remains manual; no deploy webhook calls or secrets are introduced.

## Test strategy

- Update deployment/test-lane contract tests from `.woodpecker.yml` expectations to `.github/workflows/ci.yml` expectations.
- Run targeted tests:
  - `uv run pytest -q tests/deployment/test_test_lanes_contract.py tests/deployment/test_runtime_split_contract.py`
- Run standard verification after implementation:
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run mypy .`

## Documentation scope

Update only current operational docs and project guidance:

- `docs/testing.md` — CI lane source becomes GitHub Actions.
- `docs/deployment.md` — registry image becomes GHCR.
- `docs/runtime-contract.md` — registry image becomes GHCR.
- `compose.yaml` — default image becomes GHCR for local smoke.
- `AGENTS.md` — current status and branch-strategy wording becomes GitHub Actions/GHCR.

Historical plans/specs under `docs/superpowers/` remain historical unless a current contract test or current doc depends on them.

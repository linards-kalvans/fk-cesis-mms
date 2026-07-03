# Remove CI Deploy Webhooks — Design

Date: 2026-07-03
Status: approved for implementation planning

## Problem

The Woodpecker pipeline currently builds and publishes images, then runs deploy notification steps that call infra-owned deploy webhooks. Deployment will be manual for now, and automatic deployment can be recreated later.

## Goals

- Keep CI lint, tests, tag preparation, and image publish behavior unchanged.
- Remove CI deploy webhook calls from `.woodpecker.yml`.
- Remove `.woodpecker.yml` documentation for deploy webhook secrets.
- Update deployment contract tests so they assert build-and-publish only, not optional webhook handoff.
- Leave application webhooks untouched, including the DocuSeal integration webhook.

## Non-goals

- Do not change the `fk-cesis` infrastructure repository.
- Do not change Docker runtime, `Dockerfile`, `compose.yaml`, image tags, or registry naming.
- Do not remove DocuSeal, Invoice Ninja, or any application-level webhook/integration code.
- Do not add a manual deployment runbook to this repository.
- Do not add placeholder/no-op deploy steps.

## Chosen approach

Use the minimal cut:

1. Delete `notify-dev` and `notify-prod` from `.woodpecker.yml`.
2. Delete the top-level `.woodpecker.yml` comments that describe optional deploy webhook handoff.
3. Delete the deploy webhook secret comment block from `.woodpecker.yml`.
4. Update `tests/deployment/test_runtime_split_contract.py` so Woodpecker expectations check that:
   - build-and-push remains present;
   - prepare-tags remains present;
   - deploy webhook notify steps are absent;
   - deploy webhook secrets are absent.

## Why

This keeps the app repository focused on building tested images. Manual deployment can pull the already-published `dev`, `main`, or immutable `<major>.<minor>` tag. Removing steps entirely is clearer than disabling them, because CI no longer suggests deploy automation exists.

## Data flow after change

```text
push / manual run
  -> lint
  -> test
  -> prepare image tags
  -> build-and-push image
  -> stop

manual deploy happens outside this repository
```

## Acceptance criteria

- `.woodpecker.yml` has no `notify-dev` or `notify-prod` step.
- `.woodpecker.yml` has no `DEV_DEPLOY_WEBHOOK_URL`, `DEV_DEPLOY_WEBHOOK_SECRET`, `PROD_DEPLOY_WEBHOOK_URL`, or `PROD_DEPLOY_WEBHOOK_SECRET` references.
- `.woodpecker.yml` still has `prepare-tags-dev`, `prepare-tags-main`, and `build-and-push`.
- Deployment tests pass.
- Application webhooks remain unchanged.

## Test strategy

- Update `tests/deployment/test_runtime_split_contract.py` to match the new manual-deploy stance.
- Run `uv run pytest -q tests/deployment/test_runtime_split_contract.py`.
- Run full repo verification if implementation remains small enough: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`.

## Documentation scope

No public docs need major changes. Existing `docs/deployment.md` and `docs/runtime-contract.md` already state this repository owns image build/tag contracts and the `fk-cesis` repo owns runtime deployment.

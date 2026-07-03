# Deployment Runtime Split Design

## Goal

Split deployment ownership so this repository remains responsible for the Django application and Docker image, while `https://github.com/linards-kalvans/fk-cesis` owns server/runtime deployment for the built image.

## Problem

`fk-cesis-mms` currently contains both application delivery concerns and host/runtime deployment guidance. That makes ownership unclear once the broader FK Cēsis infrastructure repository exists. The desired end state is a clean boundary:

- this repository builds and publishes the application image;
- `fk-cesis` consumes that image and owns deploy/runtime orchestration.

## Confirmed Requirements

- Keep this repository as the owner of application code, `Dockerfile`, image build CI, image tag/version policy, and local Docker smoke support.
- Move server/runtime deployment ownership to `fk-cesis`.
- Keep the current tag model:
  - `dev` floating tag for dev deployments;
  - `main` floating tag for prod default tracking;
  - immutable `X.Y` tags for production pin/rollback.
- `fk-cesis` may have its own CI/deploy automation.
- No secrets or host-specific values are committed in either repository.
- Success criteria:
  1. this repository still builds and publishes images with the same tags;
  2. `fk-cesis` can deploy by referencing an image tag;
  3. host-specific deploy scripts/docs are no longer source-of-truth in this repository;
  4. dev/prod rollout documentation lives in `fk-cesis`.

## Out of Scope

- Changing Django application runtime behavior.
- Changing image tag semantics.
- Removing local Docker smoke support from this repository.
- Committing secrets, production `.env` files, or host-specific values.
- Replacing the current container image registry unless explicitly decided later.

## Recommended Approach

Use a hard ownership split now.

### This repository owns

- Application source code.
- `Dockerfile`.
- CI image build and publish flow.
- Version/tag policy documentation for produced images.
- Local-only Docker smoke support.
- A stable runtime contract consumed by infrastructure.

### `fk-cesis` owns

- Server deploy manifests.
- Runtime `compose.yaml` for deployed hosts.
- `.env.example` / configuration templates without secrets.
- Caddy examples or managed Caddy config.
- systemd units and deploy listener scripts, if still used.
- dev/prod rollout and rollback runbooks.
- Optional deployment CI/automation that consumes the image.

## Repository Boundary

```text
fk-cesis-mms repo                     fk-cesis repo
-----------------                     -------------
app code                              host/runtime config
Dockerfile                            server compose manifests
publish CI                            env templates
tag/version logic                     Caddy/systemd/listener
local smoke compose/docs              deploy automation/docs
image registry output  ----------->   image consumption by tag
```

## Shared Runtime Contract

This repository should expose a concise contract that `fk-cesis` must honor:

- image name and registry location;
- supported tags: `dev`, `main`, immutable `X.Y`;
- required environment variables;
- container port and healthcheck endpoint (`/healthz`);
- required volumes for uploads and private uploads;
- expected services:
  - `web` process serving Django via gunicorn;
  - `qcluster` process for django-q2 background jobs;
  - Postgres database reachable through `DATABASE_URL`;
- startup behavior:
  - migrations run before web boot in the current compose shape;
  - static files are baked into the image;
  - `/healthz` must pass before traffic is considered healthy;
- rollback behavior:
  - prod may pin `IMAGE_TAG=X.Y` in `fk-cesis` runtime config.

## Migration Shape

### Phase A — Freeze handoff contract

Document the stable image/runtime contract in this repository before moving deploy ownership. This prevents `fk-cesis` from reverse-engineering assumptions from app internals.

### Phase B — Recreate runtime ownership in `fk-cesis`

Move or recreate these source-of-truth items in `fk-cesis`:

- server runtime `compose.yaml`;
- deploy `.env.example`;
- deploy listener/webhook code if retained;
- systemd unit examples;
- Caddy examples;
- host provisioning guide;
- dev/prod rollout guide;
- rollback guide using immutable `X.Y` tags.

### Phase C — Trim this repository to app + local smoke

This repository should keep:

- `Dockerfile`;
- local smoke compose/docs, clearly labelled as local-only;
- image contract docs.

This repository should remove or deprecate as source-of-truth:

- host provisioning docs;
- deploy listener ownership;
- Caddy/systemd production examples;
- dev/prod server rollout docs.

### Phase D — Verify both paths

Run two checks:

1. local app smoke in this repository:
   - build image;
   - run local compose;
   - verify `/healthz`;
   - verify web and worker boot.
2. infra deploy smoke in `fk-cesis`:
   - deploy `:dev` by image reference;
   - verify `/healthz`;
   - verify `web` and `qcluster`;
   - verify mounted data paths;
   - verify prod pin/rollback path is documented.

## Risk Controls

| Risk | Control |
| --- | --- |
| Two repos disagree on env vars | Keep runtime contract in app repo and mirror deploy `.env.example` in `fk-cesis` |
| Local compose mistaken for prod deploy | Rename or document local compose as local smoke only |
| Tag drift | Keep tag generation in app repo; consume tags in `fk-cesis` |
| Secrets leak | Commit examples only; never commit real `.env` values |
| Worker omitted | Contract requires both `web` and `qcluster` services |
| Rollback unclear | Document prod pin to immutable `X.Y` in `fk-cesis` |

## Acceptance Criteria

### `fk-cesis-mms`

- `Dockerfile` remains the source of application image build.
- CI still publishes `dev`, `main`, and immutable `X.Y` images.
- Local Docker smoke remains possible and documented.
- Documentation states that deployed runtime ownership lives in `fk-cesis`.
- Host-specific deploy scripts/docs are not source-of-truth here.

### `fk-cesis`

- Runtime deploy can reference an image tag from this repository.
- Dev deployment can track floating `dev`.
- Production can track floating `main` or pin immutable `X.Y`.
- Runtime config includes `web`, `qcluster`, Postgres connectivity, volumes, and healthcheck routing.
- Secrets remain outside git.

### Verification

- Local smoke in this repository passes.
- Dev deploy in `fk-cesis` passes.
- Production rollback/pin path is documented before any production cutover.

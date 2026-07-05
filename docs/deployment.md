# Deployment Ownership — fk-cesis-mms

Deployment runtime ownership has moved to `https://github.com/linards-kalvans/fk-cesis`.

This repository owns:

- application source code;
- `Dockerfile`;
- image build and publish CI;
- image tag/version policy;
- local Docker smoke support.

The `fk-cesis` repository owns:

- deployed Docker Compose runtime;
- host `.env` templates;
- Caddy routing;
- systemd units;
- deploy listener/scripts;
- dev/prod rollout and rollback runbooks.

## App repo docs

- Runtime contract for infra consumers: `docs/runtime-contract.md`
- Local Docker smoke: `docs/local-docker-smoke.md`

## Image contract

- Registry image: `ghcr.io/linards-kalvans/fk-cesis-mms`
- Dev floating tag: `dev`
- Production floating tag: `main`
- Immutable rollback tags: `<major>.<minor>`

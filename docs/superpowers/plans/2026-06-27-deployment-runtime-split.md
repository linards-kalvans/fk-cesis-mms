# Deployment Runtime Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split runtime deployment ownership so `fk-cesis-mms` keeps app/image ownership and `fk-cesis` owns server deploy/runtime for the built image.

**Architecture:** Keep the application image contract in this repo, move server deployment source-of-truth into `fk-cesis`, and keep a clearly local-only Docker smoke path here. The published image remains the interface between repositories: this repo builds `codeberg.org/linards-kalvans/fk-cesis-mms:{dev,main,X.Y}`, and `fk-cesis` deploys by tag.

**Tech Stack:** Django 5, Docker, Docker Compose, Woodpecker CI, Codeberg container registry, Caddy, systemd, Python deploy listener, django-q2 worker.

---

## Design decisions

### 1. Keep app repo as image producer

**Decision:** Do not move `Dockerfile`, version-tag computation, or image build/publish responsibility out of `fk-cesis-mms`.

**Why:** The image is coupled to application code, dependencies, static collection, healthcheck, and release tags. Keeping build logic beside application code avoids cross-repo build drift.

### 2. Make `fk-cesis` runtime source-of-truth

**Decision:** Move server runtime artifacts and host deployment docs to `fk-cesis` under a dedicated `deploy/fk-cesis-mms/` tree.

**Why:** Runtime is infrastructure. It includes host ports, Caddy routing, systemd services, deploy webhook listener, deploy scripts, and environment templates. Those belong in the broader FK Cēsis infrastructure repo, not the application repo.

### 3. Keep local smoke support in app repo

**Decision:** Keep a Docker Compose path here, but relabel it as local smoke only.

**Why:** Developers still need to verify that the built image boots with Postgres, `web`, and `qcluster`. Keeping local smoke avoids requiring infra repo access for basic image validation.

### 4. Preserve current tag model

**Decision:** Keep `dev`, `main`, and immutable `X.Y` tags unchanged.

**Why:** Existing CI and rollback flow already uses this model. Changing tags would add risk unrelated to the ownership split.

### 5. Preserve CI deploy notification as an external handoff unless `fk-cesis` replaces it

**Decision:** Keep Woodpecker publish behavior. Update comments/docs so deploy notification is described as calling an infra-owned endpoint, not owning the server listener here. If `fk-cesis` later supplies its own polling/automation, removing notify steps can be a separate change.

**Why:** This avoids breaking current dev auto-deploy while still moving source-of-truth deploy code/docs to `fk-cesis`.

---

## File-by-file plan

### `fk-cesis-mms` repository

- Modify: `compose.yaml`
  - Change header comments from production/server deploy wording to local-smoke wording.
  - Keep service behavior unchanged: `postgres`, `web`, `qcluster`, volumes, healthcheck semantics.
- Modify: `Dockerfile`
  - Replace stale reference to `docs/deployment.md` with `docs/runtime-contract.md` / local smoke guidance.
- Modify: `.woodpecker.yml`
  - Keep image build and tag behavior unchanged.
  - Update comments and secret descriptions so deploy webhook is an external infra-owned handoff.
- Create: `docs/runtime-contract.md`
  - Document image name, tags, required env vars, services, volumes, healthcheck, startup behavior, and rollback contract.
- Create: `docs/local-docker-smoke.md`
  - Document local build and local compose smoke only.
- Modify: `docs/deployment.md`
  - Replace full host deploy runbook with a short pointer stating runtime deployment source-of-truth moved to `fk-cesis`.
  - Link to `docs/runtime-contract.md` and `docs/local-docker-smoke.md`.
- Modify: `README.md`
  - Replace deployment runbook link with runtime contract + local smoke docs.
- Modify: `AGENTS.md`
  - Update command section and M6 notes to state that host deployment runtime lives in `fk-cesis`; local compose is smoke only.
- Modify: `docs/milestones.md`
  - Add a small status note under foundation/platform that deployment runtime ownership has moved to `fk-cesis` while image build remains here.

### `fk-cesis` repository

Resolve the local checkout path during execution with:

```bash
kimaki project list --json | jq -r '.[] | select(.channel_name == "fk-cesis" or .directory | test("/fk-cesis$")) | .directory' | head -n 1
```

If that command prints nothing, clone or add the repository outside this plan only after asking the user for the desired local path.

- Create: `deploy/fk-cesis-mms/compose.yaml`
  - Source-of-truth server compose for `postgres`, `web`, `qcluster`.
  - Use image `codeberg.org/linards-kalvans/fk-cesis-mms:${IMAGE_TAG}`.
- Create: `deploy/fk-cesis-mms/.env.example`
  - Include all runtime env keys without secrets.
  - Include `IMAGE_TAG`, `WEB_HOST_PORT`, Postgres vars, Django vars, OCR vars, DocuSeal vars, Invoice Ninja vars, email vars, audit/billing schedule vars.
- Create: `deploy/fk-cesis-mms/bin/fk-deploy-listener.py`
  - HMAC-verified listener script from the old app repo runbook.
- Create: `deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh`
  - Pull and restart `web` + `qcluster` with compose.
- Create: `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.service`
  - systemd service for the listener.
- Create: `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.env.example`
  - env template for listener secret and bind config, no real values.
- Create: `deploy/fk-cesis-mms/caddy/fk-cesis-mms.Caddyfile.example`
  - Caddy route for app and deploy hook.
- Create: `docs/fk-cesis-mms-deployment.md`
  - Server provisioning, deploy, rollback, and operations runbook.
- Modify: root `README.md` or existing infra index in `fk-cesis`
  - Link to `docs/fk-cesis-mms-deployment.md`.

---

## Test strategy

### What to test

- App repo documentation references point to correct new ownership.
- App repo local smoke compose still validates with Docker Compose.
- App repo image build still works.
- Woodpecker image tag and publish behavior remains unchanged.
- `fk-cesis` server compose renders with example env values.
- Deploy listener script compiles as Python.
- Deploy script is shell-syntax valid.
- Runtime docs contain no real secrets.

### What not to test

- Do not test external Codeberg registry publishing locally.
- Do not execute production deploy against prod host in this implementation task.
- Do not run live Invoice Ninja, DocuSeal, tiny-IDP, or email integrations.
- Do not change Django business logic or application tests for this ownership split.

### Commands

App repo:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
docker compose config
docker build -t fk-cesis-mms:runtime-split-smoke .
WEB_HOST_PORT=18000 FK_CESIS_MMS_IMAGE=fk-cesis-mms IMAGE_TAG=runtime-split-smoke docker compose up -d
curl -fsS http://127.0.0.1:18000/healthz
docker compose down -v
```

`fk-cesis` repo:

```bash
python3 -m py_compile deploy/fk-cesis-mms/bin/fk-deploy-listener.py
bash -n deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh
docker compose --env-file deploy/fk-cesis-mms/.env.example -f deploy/fk-cesis-mms/compose.yaml config
```

---

## Acceptance criteria per unit

### App repo docs and config

- `docs/deployment.md` no longer contains full host provisioning, Caddy, systemd, or deploy listener source-of-truth.
- `docs/runtime-contract.md` lists image name, supported tags, env vars, volumes, services, healthcheck, startup, and rollback contract.
- `docs/local-docker-smoke.md` gives local-only Docker commands.
- `compose.yaml` comments clearly say local smoke only.
- `.woodpecker.yml` still publishes `dev`, `main`, and immutable `X.Y` tags.
- README and AGENTS links point to new docs.

### Infra repo runtime files

- `deploy/fk-cesis-mms/compose.yaml` includes `postgres`, `web`, and `qcluster`.
- `web` runs migrations before gunicorn.
- `qcluster` runs `python manage.py qcluster` and has no HTTP healthcheck.
- Volumes map uploads and private uploads.
- `.env.example` contains keys but no real secret values.
- Caddy example routes `/` to web and `/hooks/codeberg` to listener.
- systemd example runs the listener as the unprivileged service user.
- deploy script pulls and restarts only app services, preserving database volume.

### Verification

- App repo full gate passes.
- App repo local Docker smoke reaches `/healthz`.
- Infra repo compose config renders.
- Listener script compiles.
- Shell script passes `bash -n`.
- No secrets are introduced in either repo.

---

## Documentation scope

### Create/update in app repo

- `docs/runtime-contract.md`
- `docs/local-docker-smoke.md`
- `docs/deployment.md`
- `README.md`
- `AGENTS.md`
- `docs/milestones.md`

### Create/update in `fk-cesis`

- `docs/fk-cesis-mms-deployment.md`
- `deploy/fk-cesis-mms/compose.yaml`
- `deploy/fk-cesis-mms/.env.example`
- `deploy/fk-cesis-mms/bin/fk-deploy-listener.py`
- `deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh`
- `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.service`
- `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.env.example`
- `deploy/fk-cesis-mms/caddy/fk-cesis-mms.Caddyfile.example`
- root README or infra index

---

## Task 1: Add app repo runtime contract and local smoke docs

**Files:**
- Create: `docs/runtime-contract.md`
- Create: `docs/local-docker-smoke.md`
- Modify: `docs/deployment.md`
- Modify: `README.md`

- [ ] **Step 1: Write `docs/runtime-contract.md`**

Use this structure:

```markdown
# Runtime Contract — fk-cesis-mms

This repository builds the application image. The `fk-cesis` infrastructure repository owns deployed runtime configuration.

## Image

- Registry image: `codeberg.org/linards-kalvans/fk-cesis-mms`
- Dev tag: `dev`
- Production floating tag: `main`
- Immutable release tags: `<major>.<minor>`, for example `0.42`

## Processes

Runtime must run two application containers from the same image:

| Service | Command | Notes |
| --- | --- | --- |
| `web` | `python manage.py migrate --noinput && gunicorn fk_cesis_mms.wsgi:application --bind 0.0.0.0:8000 --workers 3 --access-logfile - --error-logfile -` | Serves Django and runs migrations before boot. |
| `qcluster` | `python manage.py qcluster` | Runs django-q2 background jobs; no HTTP server. |

A Postgres database must be reachable through `DATABASE_URL`.

## Ports and health

- Container port: `8000`
- Healthcheck endpoint: `GET /healthz`
- Healthy response: HTTP 200 JSON body with `status=ok`

## Required mounted paths

| Container path | Purpose |
| --- | --- |
| `/app/uploads` | Public/media uploads managed by Django storage |
| `/app/private-uploads` | Private identity-document storage |

## Required environment variables

### Django

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=false`
- `SITE_URL`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL`
- `TIME_ZONE` optional, defaults to `Europe/Riga`

### Database

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`

### OCR

- `OCR_PROVIDER_MODE=stub|tiny_idp`
- `TINY_IDP_API_URL`
- `TINY_IDP_API_KEY`
- `OCR_ENCRYPTION_KEY`

### Agreement platform

- `AGREEMENT_PROVIDER_MODE=stub|docuseal`
- `DOCUSEAL_API_URL`
- `DOCUSEAL_API_KEY`
- `DOCUSEAL_TEMPLATE_ID`
- `DOCUSEAL_WEBHOOK_SECRET`

### Billing / Invoice Ninja

- `INVOICE_PROVIDER_MODE=stub|invoiceninja`
- `INVOICE_NINJA_API_URL`
- `INVOICE_NINJA_API_KEY`
- `INVOICE_NINJA_NUMBER_PREFIX`
- `BILLING_AUTOSEND_ENABLED`
- `BILLING_SEND_DUE_HOUR`
- `BILLING_PAYMENT_SYNC_HOUR`

### Email

- `EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_USE_TLS`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `DEFAULT_FROM_EMAIL`

### Admin bootstrap

- `DJANGO_SUPERUSER_EMAIL`
- `DJANGO_SUPERUSER_USERNAME`
- `DJANGO_SUPERUSER_PASSWORD`

### Audit

- `AUDIT_RETENTION_DAYS`
- `AUDIT_PRUNE_HOUR`

## Rollback contract

Production runtime may pin `IMAGE_TAG=<major>.<minor>` to roll back to an immutable image. Return to `IMAGE_TAG=main` to resume floating production tracking.

## Ownership

- `fk-cesis-mms`: app code, Docker image, tag production, local smoke.
- `fk-cesis`: server compose, Caddy, systemd, deploy listener, host `.env`, rollout docs.
```

- [ ] **Step 2: Write `docs/local-docker-smoke.md`**

Use this structure:

```markdown
# Local Docker Smoke — fk-cesis-mms

This is local developer smoke support only. Deployed runtime configuration lives in `https://github.com/linards-kalvans/fk-cesis`.

## Build image

```bash
docker build -t fk-cesis-mms:dev .
```

## Start local stack

Create a local `.env` from `.env.example`, then run:

```bash
FK_CESIS_MMS_IMAGE=fk-cesis-mms IMAGE_TAG=dev docker compose up -d
```

Use a different host port if `8000` is busy:

```bash
WEB_HOST_PORT=18000 FK_CESIS_MMS_IMAGE=fk-cesis-mms IMAGE_TAG=dev docker compose up -d
```

## Verify

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

or when using `WEB_HOST_PORT=18000`:

```bash
curl -fsS http://127.0.0.1:18000/healthz
```

## Logs

```bash
docker compose logs -f web qcluster
```

## Stop and clean

```bash
docker compose down -v
```

## Notes

- `qcluster` has no HTTP server and intentionally has healthcheck disabled.
- `web` runs migrations before gunicorn in the local compose path.
- Do not use this file as production runtime source-of-truth.
```

- [ ] **Step 3: Replace `docs/deployment.md` with an ownership pointer**

Use this content:

```markdown
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

- Registry image: `codeberg.org/linards-kalvans/fk-cesis-mms`
- Dev floating tag: `dev`
- Production floating tag: `main`
- Immutable rollback tags: `<major>.<minor>`
```

- [ ] **Step 4: Update README documentation links**

Replace the line:

```markdown
- Deployment runbook: `docs/deployment.md`
```

with:

```markdown
- Runtime contract: `docs/runtime-contract.md`
- Local Docker smoke: `docs/local-docker-smoke.md`
- Deployment ownership pointer: `docs/deployment.md` (`fk-cesis` owns deployed runtime)
```

- [ ] **Step 5: Inspect app repo diff**

Run:

```bash
git diff -- docs/runtime-contract.md docs/local-docker-smoke.md docs/deployment.md README.md
```

Expected: only documentation changes; no secrets.

---

## Task 2: Reframe app repo compose, Dockerfile, CI comments, and project docs

**Files:**
- Modify: `compose.yaml`
- Modify: `Dockerfile`
- Modify: `.woodpecker.yml`
- Modify: `AGENTS.md`
- Modify: `docs/milestones.md`

- [ ] **Step 1: Update `compose.yaml` header comment**

Replace lines 1-8 with:

```yaml
# fk-cesis-mms — local Docker smoke stack
#
# Deployed runtime configuration is owned by:
#   https://github.com/linards-kalvans/fk-cesis
#
# This compose file is kept in the app repo so developers can smoke-test the
# built image with Postgres, web, and qcluster locally. Do not treat this file
# as the production server source-of-truth.
```

- [ ] **Step 2: Update `Dockerfile` UID comment**

Replace:

```dockerfile
# Non-root runtime user. UID 10001 must match the host `fkmms` user that owns
# the bind-mounted data directories (see docs/deployment.md).
```

with:

```dockerfile
# Non-root runtime user. UID 10001 should match the service user that owns
# bind-mounted data directories in the infra repo runtime.
```

- [ ] **Step 3: Update `.woodpecker.yml` top comments and secret descriptions**

Keep behavior unchanged. Replace the top branch comment block lines 3-6 with:

```yaml
# Two-channel image strategy:
#   - dev  branch: development.    Push -> build :dev.
#   - main branch: tested releases. Push -> build :main + :<major>.<minor>.
#
# Deployment runtime is owned by the fk-cesis infrastructure repository. The
# optional notify steps call infra-owned webhooks after image publication.
```

Replace secret descriptions lines 21-27 with:

```yaml
# Required Codeberg secrets (Repo Settings -> Secrets):
#   CODEBERG_USER             registry user (deploy bot or your handle)
#   CODEBERG_TOKEN            Codeberg Application Token w/ packages:write
#
# Optional handoff webhook secrets, owned by fk-cesis runtime automation:
#   DEV_DEPLOY_WEBHOOK_URL
#   DEV_DEPLOY_WEBHOOK_SECRET
#   PROD_DEPLOY_WEBHOOK_URL
#   PROD_DEPLOY_WEBHOOK_SECRET
```

- [ ] **Step 4: Update `AGENTS.md` command section**

In the command block, change this comment:

```bash
# Container / deploy (see docs/deployment.md for the full runbook)
```

To:

```bash
# Container local smoke (deployed runtime lives in fk-cesis; see docs/local-docker-smoke.md)
```

Also add this bullet near the M6 containerization note:

```markdown
  - Deployment runtime ownership moved to `https://github.com/linards-kalvans/fk-cesis` on 2026-06-27. This repo keeps the Docker image build/tag contract and local smoke compose only; server compose, Caddy, systemd, deploy listener, env templates, and rollout docs live in `fk-cesis`.
```

- [ ] **Step 5: Update `docs/milestones.md` foundation/platform status**

Add this bullet under `### Foundation and platform`:

```markdown
- deployment runtime ownership is split: this repo owns app image build/tagging and local smoke; `https://github.com/linards-kalvans/fk-cesis` owns deployed runtime configuration and rollout docs.
```

- [ ] **Step 6: Inspect diff**

Run:

```bash
git diff -- compose.yaml Dockerfile .woodpecker.yml AGENTS.md docs/milestones.md
```

Expected: comments/docs only; no runtime behavior changes.

---

## Task 3: Add `fk-cesis` runtime tree

**Files in `fk-cesis`:**
- Create: `deploy/fk-cesis-mms/compose.yaml`
- Create: `deploy/fk-cesis-mms/.env.example`
- Create: `deploy/fk-cesis-mms/bin/fk-deploy-listener.py`
- Create: `deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh`
- Create: `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.service`
- Create: `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.env.example`
- Create: `deploy/fk-cesis-mms/caddy/fk-cesis-mms.Caddyfile.example`

- [ ] **Step 1: Resolve `fk-cesis` checkout path**

Run:

```bash
kimaki project list --json | jq -r '.[] | select(.channel_name == "fk-cesis" or (.directory | test("/fk-cesis$"))) | .directory' | head -n 1
```

Expected: absolute path to local `fk-cesis` checkout.

If empty, stop and ask user for local checkout path. Do not clone into an arbitrary location.

- [ ] **Step 2: Create runtime directories**

Run in `fk-cesis` checkout:

```bash
mkdir -p deploy/fk-cesis-mms/bin deploy/fk-cesis-mms/systemd deploy/fk-cesis-mms/caddy docs
```

- [ ] **Step 3: Create `deploy/fk-cesis-mms/compose.yaml`**

Use app repo `compose.yaml` service behavior, but with production/runtime ownership comments:

```yaml
# fk-cesis-mms — deployed runtime stack
#
# Source-of-truth for FK Cēsis MMS server runtime. The app image is built by
# the fk-cesis-mms application repository and consumed here by tag.

name: fk-cesis-mms

services:
  postgres:
    image: postgres:18-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  web:
    image: ${FK_CESIS_MMS_IMAGE:-codeberg.org/linards-kalvans/fk-cesis-mms}:${IMAGE_TAG:-dev}
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    env_file:
      - .env
    ports:
      - "127.0.0.1:${WEB_HOST_PORT:-8000}:8000"
    volumes:
      - ./data/uploads:/app/uploads
      - ./data/private-uploads:/app/private-uploads
    command:
      - sh
      - -c
      - >
        python manage.py migrate --noinput &&
        exec gunicorn fk_cesis_mms.wsgi:application
        --bind 0.0.0.0:8000
        --workers 3
        --access-logfile -
        --error-logfile -

  qcluster:
    image: ${FK_CESIS_MMS_IMAGE:-codeberg.org/linards-kalvans/fk-cesis-mms}:${IMAGE_TAG:-dev}
    restart: unless-stopped
    depends_on:
      web:
        condition: service_healthy
    env_file:
      - .env
    volumes:
      - ./data/uploads:/app/uploads
      - ./data/private-uploads:/app/private-uploads
    command: ["python", "manage.py", "qcluster"]
    healthcheck:
      disable: true

volumes:
  pgdata:
```

- [ ] **Step 4: Create `deploy/fk-cesis-mms/.env.example`**

Use non-secret values only:

```ini
# Channel / image
FK_CESIS_MMS_IMAGE=codeberg.org/linards-kalvans/fk-cesis-mms
IMAGE_TAG=dev
WEB_HOST_PORT=8000

# Django
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=false
SITE_URL=https://mms.example.lv
DJANGO_ALLOWED_HOSTS=mms.example.lv
TIME_ZONE=Europe/Riga

# Database
DATABASE_URL=postgres://fkmms:change-me@postgres:5432/fkmms
POSTGRES_DB=fkmms
POSTGRES_USER=fkmms
POSTGRES_PASSWORD=change-me

# OCR
OCR_PROVIDER_MODE=stub
TINY_IDP_API_URL=
TINY_IDP_API_KEY=
OCR_ENCRYPTION_KEY=change-me-fernet-key

# Agreement platform
AGREEMENT_PROVIDER_MODE=stub
DOCUSEAL_API_URL=
DOCUSEAL_API_KEY=
DOCUSEAL_TEMPLATE_ID=
DOCUSEAL_WEBHOOK_SECRET=

# Invoice Ninja
INVOICE_PROVIDER_MODE=stub
INVOICE_NINJA_API_URL=
INVOICE_NINJA_API_KEY=
INVOICE_NINJA_NUMBER_PREFIX=MMS
BILLING_AUTOSEND_ENABLED=false
BILLING_SEND_DUE_HOUR=4
BILLING_PAYMENT_SYNC_HOUR=3

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.lv
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=noreply@example.lv

# Admin bootstrap
DJANGO_SUPERUSER_EMAIL=
DJANGO_SUPERUSER_USERNAME=
DJANGO_SUPERUSER_PASSWORD=

# Audit
AUDIT_RETENTION_DAYS=730
AUDIT_PRUNE_HOUR=2
```

- [ ] **Step 5: Create `deploy/fk-cesis-mms/bin/fk-deploy-listener.py`**

Use the listener script currently embedded in app repo `docs/deployment.md`, preserving:

- `X-FK-Signature: sha256=<hmac>` verification;
- loopback bind default;
- background deploy script execution;
- journald-friendly stdout logging.

Set `DEPLOY_CMD` to:

```python
DEPLOY_CMD = ["/opt/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh"]
```

- [ ] **Step 6: Create `deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh`**

Use:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /opt/fk-cesis-mms

docker compose pull web qcluster
docker compose up -d --remove-orphans
```

- [ ] **Step 7: Create systemd unit**

Create `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.service`:

```ini
[Unit]
Description=fk-cesis-mms deploy webhook listener
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=fkmms
Group=fkmms
EnvironmentFile=/etc/fk-cesis-mms-deploy-listener.env
ExecStart=/usr/bin/python3 /opt/fk-cesis-mms/bin/fk-deploy-listener.py
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/fk-cesis-mms

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 8: Create listener env example**

Create `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.env.example`:

```ini
DEPLOY_WEBHOOK_SECRET=change-me
DEPLOY_LISTENER_HOST=127.0.0.1
DEPLOY_LISTENER_PORT=9000
```

- [ ] **Step 9: Create Caddy example**

Create `deploy/fk-cesis-mms/caddy/fk-cesis-mms.Caddyfile.example`:

```caddyfile
mms.example.lv {
    encode zstd gzip

    handle /hooks/codeberg {
        reverse_proxy 127.0.0.1:9000
    }

    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
```

- [ ] **Step 10: Validate new infra files**

Run in `fk-cesis` checkout:

```bash
python3 -m py_compile deploy/fk-cesis-mms/bin/fk-deploy-listener.py
bash -n deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh
docker compose --env-file deploy/fk-cesis-mms/.env.example -f deploy/fk-cesis-mms/compose.yaml config
```

Expected: all commands succeed.

---

## Task 4: Add `fk-cesis` deployment runbook

**Files in `fk-cesis`:**
- Create: `docs/fk-cesis-mms-deployment.md`
- Modify: root `README.md` or existing docs index

- [ ] **Step 1: Create runbook**

Create `docs/fk-cesis-mms-deployment.md` with these sections:

```markdown
# FK Cēsis MMS Deployment

This repository owns deployed runtime for the FK Cēsis MMS application image.

## Image source

- Image: `codeberg.org/linards-kalvans/fk-cesis-mms`
- Dev floating tag: `dev`
- Prod floating tag: `main`
- Immutable rollback tags: `<major>.<minor>`

The application repository owns image builds and tag generation.

## Runtime layout

Server directory:

```text
/opt/fk-cesis-mms/
  compose.yaml
  .env
  bin/
    fk-deploy-listener.py
    deploy-fk-cesis-mms.sh
  data/
    uploads/
    private-uploads/
```

## Provision host

```bash
apt-get update
apt-get install -y docker.io docker-compose-plugin caddy openssl python3
systemctl enable --now docker
systemctl enable --now caddy

useradd --system --uid 10001 --create-home --home-dir /opt/fk-cesis-mms --shell /usr/sbin/nologin fkmms
usermod -aG docker fkmms

install -o fkmms -g fkmms -m 0750 -d /opt/fk-cesis-mms
install -o fkmms -g fkmms -m 0750 -d /opt/fk-cesis-mms/bin
install -o fkmms -g fkmms -m 0750 -d /opt/fk-cesis-mms/data/uploads
install -o fkmms -g fkmms -m 0700 -d /opt/fk-cesis-mms/data/private-uploads
```

## Install runtime files

Copy:

- `deploy/fk-cesis-mms/compose.yaml` to `/opt/fk-cesis-mms/compose.yaml`
- `deploy/fk-cesis-mms/.env.example` to `/opt/fk-cesis-mms/.env`, then replace placeholder values
- `deploy/fk-cesis-mms/bin/*` to `/opt/fk-cesis-mms/bin/`
- `deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.service` to `/etc/systemd/system/`
- listener env file to `/etc/fk-cesis-mms-deploy-listener.env`
- Caddy example into the host Caddyfile, with real domain and port

## Channel config

Dev server:

```ini
IMAGE_TAG=dev
SITE_URL=https://dev-mms.example.lv
DJANGO_ALLOWED_HOSTS=dev-mms.example.lv
```

Prod server:

```ini
IMAGE_TAG=main
SITE_URL=https://mms.example.lv
DJANGO_ALLOWED_HOSTS=mms.example.lv
```

Prod rollback:

```ini
IMAGE_TAG=0.42
```

## Start stack

```bash
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker login codeberg.org'
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker compose pull'
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker compose up -d'
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker compose ps'
```

## Verify

```bash
curl -fsS https://mms.example.lv/healthz
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker compose logs --tail=100 web qcluster'
```

## Deploy listener

```bash
systemctl daemon-reload
systemctl enable --now fk-cesis-mms-deploy-listener
systemctl status fk-cesis-mms-deploy-listener
```

## Rollback

1. Edit `/opt/fk-cesis-mms/.env`.
2. Set `IMAGE_TAG=<known-good-version>`, for example `IMAGE_TAG=0.42`.
3. Run:

```bash
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker compose pull web qcluster && docker compose up -d web qcluster'
```

4. Verify `/healthz`.

Set `IMAGE_TAG=main` to resume floating prod updates.

## Secrets rule

Never commit real `.env` values, deploy webhook secrets, API keys, SMTP passwords, OCR keys, DocuSeal keys, or Invoice Ninja keys.
```

- [ ] **Step 2: Link runbook from `fk-cesis` README/index**

Add a bullet to the existing README or docs index:

```markdown
- FK Cēsis MMS deployment: `docs/fk-cesis-mms-deployment.md`
```

- [ ] **Step 3: Inspect diff**

Run in `fk-cesis` checkout:

```bash
git diff -- deploy/fk-cesis-mms docs/fk-cesis-mms-deployment.md README.md
```

Expected: new runtime docs/files, no secrets.

---

## Task 5: Verify app repo and infra repo together

**Files:**
- No new files expected.

- [ ] **Step 1: Run app repo static gates**

Run in `fk-cesis-mms`:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```

Expected: all pass.

- [ ] **Step 2: Run app repo compose config**

Run in `fk-cesis-mms`:

```bash
docker compose config
```

Expected: compose renders successfully.

- [ ] **Step 3: Build app image**

Run in `fk-cesis-mms`:

```bash
docker build -t fk-cesis-mms:runtime-split-smoke .
```

Expected: image builds successfully.

- [ ] **Step 4: Run local smoke**

Run in `fk-cesis-mms`:

```bash
WEB_HOST_PORT=18000 FK_CESIS_MMS_IMAGE=fk-cesis-mms IMAGE_TAG=runtime-split-smoke docker compose up -d
curl -fsS http://127.0.0.1:18000/healthz
docker compose logs --tail=100 web qcluster
docker compose down -v
```

Expected: `/healthz` succeeds; logs show web and qcluster boot; stack shuts down cleanly.

- [ ] **Step 5: Run infra repo validation**

Run in `fk-cesis` checkout:

```bash
python3 -m py_compile deploy/fk-cesis-mms/bin/fk-deploy-listener.py
bash -n deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh
docker compose --env-file deploy/fk-cesis-mms/.env.example -f deploy/fk-cesis-mms/compose.yaml config
```

Expected: all pass.

- [ ] **Step 6: Scan for accidental secrets**

Run in both repositories:

```bash
git diff --check
git status --short
git diff
```

Expected: no whitespace errors; changed files are intended; no real secrets appear in diffs.

- [ ] **Step 7: Produce diff links for review**

Run in `fk-cesis-mms`:

```bash
bunx critique --web "Deployment runtime split — app repo" \
  --filter "compose.yaml" \
  --filter "Dockerfile" \
  --filter ".woodpecker.yml" \
  --filter "README.md" \
  --filter "AGENTS.md" \
  --filter "docs/milestones.md" \
  --filter "docs/deployment.md" \
  --filter "docs/runtime-contract.md" \
  --filter "docs/local-docker-smoke.md" \
  --filter "docs/superpowers/specs/2026-06-27-deployment-runtime-split-design.md" \
  --filter "docs/superpowers/plans/2026-06-27-deployment-runtime-split.md"
```

Run in `fk-cesis`:

```bash
bunx critique --web "Deployment runtime split — infra repo" \
  --filter "deploy/fk-cesis-mms/compose.yaml" \
  --filter "deploy/fk-cesis-mms/.env.example" \
  --filter "deploy/fk-cesis-mms/bin/fk-deploy-listener.py" \
  --filter "deploy/fk-cesis-mms/bin/deploy-fk-cesis-mms.sh" \
  --filter "deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.service" \
  --filter "deploy/fk-cesis-mms/systemd/fk-cesis-mms-deploy-listener.env.example" \
  --filter "deploy/fk-cesis-mms/caddy/fk-cesis-mms.Caddyfile.example" \
  --filter "docs/fk-cesis-mms-deployment.md" \
  --filter "README.md"
```

Expected: two critique URLs for user review.

---

## Self-review

### Spec coverage

- App repo keeps image build and tag policy: covered by Tasks 1, 2, 5.
- `fk-cesis` owns runtime deploy: covered by Tasks 3, 4, 5.
- Keep local smoke: covered by Tasks 1, 2, 5.
- Hybrid tag model: documented in Tasks 1, 3, 4.
- No secrets committed: acceptance criteria and verification in Tasks 3, 4, 5.

### Placeholder scan

No `TBD`, `TODO`, `implement later`, or unspecified file path remains. The only dynamic value is the local `fk-cesis` checkout path, resolved by a concrete command in Task 3.

### Type and name consistency

- Image name is consistently `codeberg.org/linards-kalvans/fk-cesis-mms`.
- Runtime tree is consistently `deploy/fk-cesis-mms/`.
- Listener service name is consistently `fk-cesis-mms-deploy-listener`.
- Deploy script name is consistently `deploy-fk-cesis-mms.sh`.

---

## Execution options

After user approves this plan:

1. **Subagent-Driven (recommended)** — dispatch focused agents for app repo docs/config, infra repo runtime files, then review/verification.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Do not commit changes unless the user explicitly requests a commit.

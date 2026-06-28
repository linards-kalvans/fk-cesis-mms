# Runtime Contract — fk-cesis-mms

This repository builds the application image. The `fk-cesis` infrastructure repository owns deployed runtime configuration.

## Image

- Registry image: `codeberg.org/linards-kalvans/fk-cesis-mms`
- Dev tag: `dev`
- Production tag: `main`
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
- `DOCUMENT_UPLOAD_MAX_BYTES` optional, defaults to `8388608` (8 MiB); upper bound on identity-document upload size

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
- `EMAIL_USE_SSL` optional, defaults to `false`; enables implicit-TLS (port 465) when set
- `EMAIL_TIMEOUT` optional, defaults to `30` (seconds)
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

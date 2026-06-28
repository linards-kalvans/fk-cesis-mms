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
- This file is not the production runtime source-of-truth.

# Deployment — fk-cesis-mms

Runbook for the two-channel deploy (dev + prod).

## Branching + tagging model

| Branch / event                 | Image tags pushed by CI                                                 | Server that auto-pulls         |
|--------------------------------|-------------------------------------------------------------------------|---------------------------------|
| `dev` push                     | `:dev` (floating)                                                       | dev server (`IMAGE_TAG=dev`)    |
| `main` push (merge from `dev`) | `:main` (floating) **and** `:<major>.<minor>` (immutable)               | prod server (`IMAGE_TAG=main`)  |
| pull request                   | none — lint + test only                                                 | none                            |

- `<major>` comes from the top-level `VERSION` file in the repo.
- `<minor>` resets to 1 the instant `VERSION` is bumped (commit that touches
  `VERSION` is `<new-major>.1`), then auto-increments on every subsequent
  commit/merge to `main`.
- Version tags are **immutable** in the registry — every successful main
  build pins a recoverable point.

## Architecture

```
codeberg.org (git + container registry)
   │
   │  push to dev                            push to main
   ▼                                          ▼
Woodpecker CI                              Woodpecker CI
   │  build & push :dev                        │  read VERSION, count commits
   │                                           │  build & push :main + :<major>.<minor>
   │                                           │
   ▼                                          ▼
DEV_DEPLOY_WEBHOOK_URL                     PROD_DEPLOY_WEBHOOK_URL
   │                                           │
   ▼                                          ▼
 DEV host                                  PROD host
 Caddy (TLS, 443)                          Caddy (TLS, 443)
   ├─ /hooks/codeberg → 127.0.0.1:9000     ├─ /hooks/codeberg → 127.0.0.1:9000
   │     fk-deploy-listener (systemd)      │     fk-deploy-listener (systemd)
   │     IMAGE_TAG=dev                     │     IMAGE_TAG=main (or pinned X.Y)
   │           │                           │           │
   │           ▼                           │           ▼
   │     docker compose pull & up -d       │     docker compose pull & up -d
   │                                       │
   └─ / → 127.0.0.1:${WEB_HOST_PORT}       └─ / → 127.0.0.1:${WEB_HOST_PORT}
         web (gunicorn + whitenoise)             web (gunicorn + whitenoise)
```

- Each server is a separate host (or at minimum a separate compose stack
  with its own subdomain + listener port + secret).
- All containers + the listener on each host run **as the unprivileged
  user `fkmms`**. Root is used **only** during one-time provisioning and
  for Caddy's packaged unit (which binds 80/443 via `CAP_NET_BIND_SERVICE`).

## 0. Which channel does this host serve?

You provision **both servers the same way** — only two values in `.env`
differ between them. Decide before you start:

| .env line          | Dev server | Prod server          |
|--------------------|------------|----------------------|
| `IMAGE_TAG`        | `dev`      | `main` (or `X.Y`)    |
| `SITE_URL`         | dev subdomain | prod subdomain    |
| `DJANGO_ALLOWED_HOSTS` | dev subdomain | prod subdomain |

Everything else (Docker, listener systemd unit, Caddy config) is identical
across hosts.

## 1. One-time server provisioning (as root)

### 1.1 Install runtime prerequisites

```bash
apt-get update
apt-get install -y docker.io docker-compose-plugin caddy openssl python3
systemctl enable --now docker
systemctl enable --now caddy
```

### 1.2 Create the unprivileged service user

The container's in-image `app` user is UID 10001. Match the host user's UID
so the bind-mounted `data/` directories share ownership cleanly.

```bash
useradd --system --uid 10001 --create-home \
        --home-dir /opt/fk-cesis-mms \
        --shell /usr/sbin/nologin fkmms
usermod -aG docker fkmms

chown -R fkmms:fkmms /opt/fk-cesis-mms
chmod 750 /opt/fk-cesis-mms

install -o fkmms -g fkmms -m 0700 -d /opt/fk-cesis-mms/data/private-uploads
install -o fkmms -g fkmms -m 0750 -d /opt/fk-cesis-mms/data/uploads
install -o fkmms -g fkmms -m 0600 /dev/null /opt/fk-cesis-mms/.env
```

### 1.3 Drop in `compose.yaml` and `.env`

```bash
install -o fkmms -g fkmms -m 0640 \
  -T /path/to/checked-out-repo/compose.yaml \
  /opt/fk-cesis-mms/compose.yaml
```

Edit `/opt/fk-cesis-mms/.env` to set the values below. Generate the secrets
with `openssl rand -base64 48` and `python -c "from cryptography.fernet
import Fernet; print(Fernet.generate_key().decode())"`.

```ini
# Django
DJANGO_SECRET_KEY=<long random>
DJANGO_DEBUG=false
SITE_URL=https://<subdomain>.example.lv
DJANGO_ALLOWED_HOSTS=<subdomain>.example.lv

# Database (compose-internal Postgres)
DATABASE_URL=postgres://fkmms:<dbpw>@postgres:5432/fkmms
POSTGRES_DB=fkmms
POSTGRES_USER=fkmms
POSTGRES_PASSWORD=<dbpw>

# OCR — start with stub for first smoke; flip to tiny_idp once verified
OCR_PROVIDER_MODE=stub
TINY_IDP_API_URL=
TINY_IDP_API_KEY=
OCR_ENCRYPTION_KEY=<fernet-key>

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=<smtp host>
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=<smtp user>
EMAIL_HOST_PASSWORD=<smtp password>
DEFAULT_FROM_EMAIL=noreply@<domain>

# Which image tag this server tracks (staging now, prod later)
IMAGE_TAG=staging

# Host port the web container binds to on 127.0.0.1. Override if 8000
# is already in use on this host (Caddy upstream must match — see §3).
WEB_HOST_PORT=8000
```

### 1.4 Pull the staging image and start the stack

```bash
su -s /bin/bash fkmms -c '
  cd /opt/fk-cesis-mms
  docker login codeberg.org   # one-time; use a deploy token
  docker compose pull
  docker compose up -d
  docker compose ps
'
```

### 1.5 Create the admin user

```bash
su -s /bin/bash fkmms -c '
  cd /opt/fk-cesis-mms
  docker compose exec web python manage.py ensure_admin_user
'
```

(Requires `DJANGO_SUPERUSER_*` env vars in `.env`. Alternatively use
`createsuperuser` interactively.)

## 2. Deploy listener

### 2.1 The script — `/usr/local/bin/fk-deploy-listener.py`

Owned `root:fkmms`, mode `0750`.

```python
#!/usr/bin/env python3
"""Tiny HMAC-verified deploy webhook for fk-cesis-mms.

Listens on 127.0.0.1:9000 (loopback only — Caddy proxies the public route).
POST /hooks/codeberg with X-FK-Signature: sha256=<hmac-sha256(body, SECRET)>
runs /usr/local/bin/deploy-fk-cesis.sh and returns 202.
"""
from __future__ import annotations

import hmac
import hashlib
import os
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = os.environ["DEPLOY_WEBHOOK_SECRET"].encode()
DEPLOY_CMD = ["/usr/local/bin/deploy-fk-cesis.sh"]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/hooks/codeberg":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        sig_header = self.headers.get("X-FK-Signature", "")
        if not sig_header.startswith("sha256="):
            self._reject("missing signature")
            return
        expected = hmac.new(SECRET, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig_header.removeprefix("sha256=")):
            self._reject("bad signature")
            return
        self.send_response(202)
        self.end_headers()
        self.wfile.write(b"accepted\n")
        # Fire and forget. Log via journald.
        subprocess.Popen(DEPLOY_CMD, stdout=None, stderr=None, start_new_session=True)

    def _reject(self, reason: str) -> None:
        self.send_response(401)
        self.end_headers()
        self.wfile.write(reason.encode() + b"\n")

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[fk-deploy] {self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9000), Handler).serve_forever()
```

### 2.2 systemd unit — `/etc/systemd/system/fk-deploy-listener.service`

```ini
[Unit]
Description=fk-cesis-mms deploy webhook listener
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=fkmms
Group=fkmms
EnvironmentFile=/etc/fk-deploy-listener.env
ExecStart=/usr/bin/python3 /usr/local/bin/fk-deploy-listener.py
Restart=on-failure
RestartSec=5

# Hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/fk-cesis-mms
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
SystemCallArchitectures=native
LockPersonality=true

[Install]
WantedBy=multi-user.target
```

`/etc/fk-deploy-listener.env` (mode `0640`, group `fkmms`):

```ini
DEPLOY_WEBHOOK_SECRET=<long random; same value goes into Woodpecker secret>
```

Then:

```bash
systemctl daemon-reload
systemctl enable --now fk-deploy-listener
systemctl status fk-deploy-listener
```

### 2.3 Deploy script — `/usr/local/bin/deploy-fk-cesis.sh`

Owned `root:fkmms`, mode `0750`.

```bash
#!/usr/bin/env bash
set -euo pipefail
cd /opt/fk-cesis-mms
docker compose pull web qcluster
docker compose up -d --remove-orphans
docker image prune -f --filter "until=168h"
```

## 3. Caddyfile patch

Append to `/etc/caddy/Caddyfile`:

```caddy
<subdomain>.example.lv {
    encode zstd gzip

    handle_path /hooks/codeberg {
        reverse_proxy 127.0.0.1:9000
    }

    # Upstream port must match WEB_HOST_PORT in /opt/fk-cesis-mms/.env
    # (defaults to 8000). If you change WEB_HOST_PORT, update this line and
    # `systemctl reload caddy`.
    reverse_proxy 127.0.0.1:8000 {
        health_uri /healthz
        health_interval 30s
    }

    log {
        output file /var/log/caddy/fk-cesis-mms.log
        format console
    }
}
```

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

DNS + cert: create an A/AAAA record for `<subdomain>` pointing at the
server's public IP; Caddy auto-issues a Let's Encrypt cert on first hit.

## 4. Codeberg secrets (Woodpecker)

In repo settings on codeberg.org → Secrets:

| Secret                       | Value                                                                |
|------------------------------|----------------------------------------------------------------------|
| `CODEBERG_USER`              | bot account or your handle                                           |
| `CODEBERG_TOKEN`             | Codeberg Application Token with `packages:write`                     |
| `DEV_DEPLOY_WEBHOOK_URL`     | `https://<dev-subdomain>.example.lv/hooks/codeberg`                  |
| `DEV_DEPLOY_WEBHOOK_SECRET`  | long random; same value as the dev host's listener                   |
| `PROD_DEPLOY_WEBHOOK_URL`    | `https://<prod-subdomain>.example.lv/hooks/codeberg`  *(later)*      |
| `PROD_DEPLOY_WEBHOOK_SECRET` | long random; same value as the prod host's listener   *(later)*      |

The `PROD_*` secrets can be added later when the prod host exists. The
`notify-prod` CI step is marked `failure: ignore`, so a missing secret
won't fail the pipeline — the `:main` and `:<X.Y>` tags still publish.

## 5. Day-2 operations

### Tail logs

```bash
su -s /bin/bash fkmms -c 'cd /opt/fk-cesis-mms && docker compose logs -f web qcluster'
journalctl -u fk-deploy-listener -f
journalctl -u caddy -f
```

### Roll back to a previous image (prod only)

Every successful `main` build leaves an immutable `:<major>.<minor>` tag in
the registry. To pin prod to a previous known-good version:

```bash
# Edit /opt/fk-cesis-mms/.env: change IMAGE_TAG=main to e.g. IMAGE_TAG=0.42
su -s /bin/bash fkmms -c '
  cd /opt/fk-cesis-mms
  docker compose pull web qcluster
  docker compose up -d web qcluster
'
```

While `IMAGE_TAG` is pinned to a specific version, future webhook deploys
become no-ops (`docker compose pull` finds nothing new for that tag). To
resume auto-pulling latest, set `IMAGE_TAG=main` and run the pull again.

The dev server has no rollback need — it follows the floating `:dev` tag.
If you need to inspect a specific dev image, do it locally with
`docker pull codeberg.org/.../fk-cesis-mms:dev@sha256:<digest>`.

### Bump the major version

`<major>` is hand-controlled. To cut e.g. `1.x` from current `0.x`:

```bash
# On the dev branch, after the feature work that justifies the bump:
echo "1" > VERSION
git add VERSION && git commit -m "release: bump major to 1"
# Open PR dev -> main as usual. The merge commit on main becomes 1.1.
```

The minor counter resets implicitly because `<minor>` counts commits since
the SHA where `VERSION` was last touched. No state file to maintain.

### Database backup

```bash
su -s /bin/bash fkmms -c '
  cd /opt/fk-cesis-mms
  docker compose exec -T postgres \
    pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"
' > /opt/fk-cesis-mms/backups/$(date -Iseconds).sql
```

(Add the above as a `fkmms` cron job and ship the resulting files off-host
to whatever backup target you trust.)

### Rotate `OCR_ENCRYPTION_KEY`

Existing encrypted payloads cannot be decrypted with a new key. Rotate only
when the old key is compromised; plan a re-OCR of affected documents after
rotation, since the in-DB encrypted blobs become unreadable.

### Promote to production later

1. Provision a second host following sections 1–3 with a different subdomain.
2. Tag a known-good image: `docker tag .../fk-cesis-mms:main-<sha>
   .../fk-cesis-mms:prod` and push.
3. Set `IMAGE_TAG=prod` in the prod host's `.env`.
4. Either point the same Woodpecker `DEPLOY_WEBHOOK_URL` at the new host
   (auto-deploy prod on every main push — usually too aggressive), or give
   the prod host its own webhook secret and trigger promotion explicitly.

When swapping to a managed Postgres service, drop the `postgres` service
from `compose.yaml`, change `DATABASE_URL` in `.env`, and run a one-time
`pg_dump | psql` migration.

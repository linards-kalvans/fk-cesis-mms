# syntax=docker/dockerfile:1.7
#
# fk-cesis-mms — production image
# - Stage 1: install deps with uv into a frozen .venv
# - Stage 2: slim runtime, non-root, gunicorn + whitenoise
#
# Build:
#   docker build -t fk-cesis-mms:dev .
# Run (compose handles env_file + ports + volumes in compose.yaml):
#   docker run --rm -p 127.0.0.1:8000:8000 --env-file .env fk-cesis-mms:dev

ARG PYTHON_VERSION=3.12-slim-bookworm

# ----------------------------------------------------------------------------
# Stage 1 — build deps with uv
# ----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# uv ships as a tiny static binary; pin the major to keep builds reproducible.
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cache layer keyed on lockfile only).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Then copy the project and install it into the same env.
COPY . .
RUN uv sync --frozen --no-dev

# Collect static files inside the builder so the runtime layer ships the
# compressed + hashed manifest (no need for collectstatic at container start).
# Provide harmless build-time env values so settings.py can import cleanly.
ENV DJANGO_SECRET_KEY=build-time-not-secret \
    DJANGO_DEBUG=false \
    DATABASE_URL=sqlite:///tmp/build.sqlite3
RUN uv run python manage.py collectstatic --noinput --clear

# ----------------------------------------------------------------------------
# Stage 2 — runtime
# ----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE=fk_cesis_mms.settings

# curl is only here for the in-container healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root runtime user. UID 10001 must match the host `fkmms` user that owns
# the bind-mounted data directories (see docs/deployment.md).
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid ${APP_GID} app \
 && useradd --uid ${APP_UID} --gid ${APP_GID} --no-create-home \
            --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Bring over the venv and the app source (including collected staticfiles).
COPY --from=builder --chown=app:app /app /app

# Bind-mount targets — create them so first start doesn't trip on permissions.
RUN mkdir -p /app/uploads /app/private-uploads \
 && chown -R app:app /app/uploads /app/private-uploads \
 && chmod 700 /app/private-uploads

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

# compose.yaml overrides this for `web` (runs migrate first) and `qcluster`.
CMD ["gunicorn", "fk_cesis_mms.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]

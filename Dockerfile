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

# Reviewed multi-platform index; builder and runtime must use the same Python.
# Override only for a reviewed compatibility candidate, never with a floating tag.
ARG PYTHON_IMAGE=python:3.14

# ----------------------------------------------------------------------------
# Stage 1 — build deps with uv
# ----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# Python 3.14-aware builder tooling; not copied into the runtime image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

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
# Do not use `uv run` here: its implicit sync reinstalls the dev dependency group.
RUN .venv/bin/python manage.py collectstatic --noinput --clear

# ----------------------------------------------------------------------------
# Stage 2 — runtime
# ----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE=fk_cesis_mms.settings

# Health probes use Python, avoiding curl and its otherwise unused dependencies.
# Runtime never installs packages. Remove the base image's pip/ensurepip bundles,
# including their independently versioned vendored dependencies (not the venv).
RUN rm -rf /usr/local/lib/python*/ensurepip \
           /usr/local/lib/python*/site-packages/pip \
           /usr/local/lib/python*/site-packages/pip-*.dist-info \
           /usr/local/bin/pip*

# Non-root runtime user. UID 10001 should match the service user that owns
# bind-mounted data directories in the infra repo runtime.
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
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).close()"]

# compose.yaml overrides this for `web` (runs migrate first) and `qcluster`.
CMD ["gunicorn", "fk_cesis_mms.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]

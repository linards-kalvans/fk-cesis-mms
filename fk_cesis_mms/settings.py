"""
Django settings for fk_cesis_mms.

Task 1: minimal scaffold. Full settings will be fleshed out in later tasks.
"""

import os
from urllib.parse import urlparse

import dj_database_url
from dotenv import load_dotenv
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Auto-load .env from project root (one level above this file's parent).
load_dotenv(dotenv_path=BASE_DIR / ".env", override=False)

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-task1-placeholder-change-in-production-abc123",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes"}

# Derive ALLOWED_HOSTS from SITE_URL and a comma-separated env override.
SITE_URL = os.environ.get("SITE_URL", "http://localhost")
_parsed = urlparse(SITE_URL)
ALLOWED_HOSTS: list[str] = [_parsed.hostname] if _parsed.hostname else []
ALLOWED_HOSTS.extend(["localhost", "127.0.0.1", "testserver", "192.168.3.245"])
_extra_allowed = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
if _extra_allowed:
    ALLOWED_HOSTS.extend(
        host.strip() for host in _extra_allowed.split(",") if host.strip()
    )

INSTALLED_APPS = [
    "apps.core.apps.FkAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # FK Cēsis MMS domain apps
    "apps.core",
    "apps.accounts",
    "apps.registrations",
    "apps.members",
    "apps.agreements",
    "apps.billing",
    "apps.documents",
    "apps.integrations",
    "apps.addresses",
    "apps.analytics",
    # Background-job runner (P3.5)
    "django_q",
]

# VZD address autocomplete region/locality object codes, comma-separated.
ADDRESS_AUTOCOMPLETE_REGION_CODES = [
    code.strip()
    for code in os.environ.get("ADDRESS_AUTOCOMPLETE_REGION_CODES", "").split(",")
    if code.strip()
]

# VZD VARIS address import URLs and schedule defaults.
ADDRESS_IMPORT_AW_NOVADS_URL = os.environ.get("ADDRESS_IMPORT_AW_NOVADS_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/c62c60bb-58d4-4f26-82c0-5b630769f9d1/download/aw_novads.csv"
ADDRESS_IMPORT_AW_PAGASTS_URL = os.environ.get("ADDRESS_IMPORT_AW_PAGASTS_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/6ba8c905-27a1-443a-b9c6-256a0777425b/download/aw_pagasts.csv"
ADDRESS_IMPORT_AW_PILSETA_URL = os.environ.get("ADDRESS_IMPORT_AW_PILSETA_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/ee02baa4-2bc3-4f77-a6cb-5427a3e9befe/download/aw_pilseta.csv"
ADDRESS_IMPORT_AW_CIEMS_URL = os.environ.get("ADDRESS_IMPORT_AW_CIEMS_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/0d3810f4-1ac0-4fba-8b10-0188084a361b/download/aw_ciems.csv"
ADDRESS_IMPORT_AW_IELA_URL = os.environ.get("ADDRESS_IMPORT_AW_IELA_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/3c4ab802-76cf-433c-9c1c-89215e28d833/download/aw_iela.csv"
ADDRESS_IMPORT_AW_EKA_URL = os.environ.get("ADDRESS_IMPORT_AW_EKA_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/a510737a-18ce-400f-ad4b-04fce5228272/download/aw_eka.csv"
ADDRESS_IMPORT_AW_DZIV_URL = os.environ.get("ADDRESS_IMPORT_AW_DZIV_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/b83be373-f444-4f50-9b98-28741845325e/download/aw_dziv.csv"
ADDRESS_IMPORT_WEEKDAY = int(os.environ.get("ADDRESS_IMPORT_WEEKDAY", "6"))
ADDRESS_IMPORT_HOUR = int(os.environ.get("ADDRESS_IMPORT_HOUR", "1"))
ADDRESS_IMPORT_MAX_DROP_RATIO = float(os.environ.get("ADDRESS_IMPORT_MAX_DROP_RATIO", "0.50"))
ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS", "30"))

MIDDLEWARE = [
    "apps.core.middleware.LocalInsecureCookieMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fk_cesis_mms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "fk_cesis_mms.wsgi.application"

# Database — DATABASE_URL drives Postgres in production; SQLite is the local default.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    ),
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "static",
    ("style-guide", BASE_DIR / "style-guide"),
]
# Manifest storage requires `collectstatic` to have populated STATIC_ROOT.
# Enable it only when the manifest is present (i.e. in container builds).
# Local dev and the test suite fall back to Django's default storage.
_staticfiles_backend = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
    if (STATIC_ROOT / "staticfiles.json").exists()
    else "django.contrib.staticfiles.storage.StaticFilesStorage"
)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": _staticfiles_backend},
}

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() in {"1", "true", "yes"}
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@fkcesis.local")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "30"))
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "false").lower() in {"1", "true", "yes"}


MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "uploads"
PRIVATE_DOCUMENTS_ROOT = BASE_DIR / "private-uploads"

# Derive CSRF_TRUSTED_ORIGINS from SITE_URL.
# Tunnel URLs (kimaki.dev) are HTTPS — keep the scheme from SITE_URL.
CSRF_TRUSTED_ORIGINS: list[str] = [SITE_URL] if SITE_URL else []

# Tunnel/proxy HTTPS support.
# Trust the proxy's X-Forwarded-Proto so Django knows the original request was HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Trust the forwarded Host header (tunnel may rewrite it).
USE_X_FORWARDED_HOST = True
# Secure cookies when SITE_URL is https:// (tunnel/proxy deployments).
_SESSION_URL = urlparse(SITE_URL)
SESSION_COOKIE_SECURE = _SESSION_URL.scheme == "https"
CSRF_COOKIE_SECURE = _SESSION_URL.scheme == "https"
SESSION_COOKIE_SAMESITE = "None" if _SESSION_URL.scheme == "https" else "Lax"
CSRF_COOKIE_SAMESITE = "None" if _SESSION_URL.scheme == "https" else "Lax"

# Magic-link auth
MAGIC_LINK_TTL_MINUTES = 60
MAGIC_LINK_RATE_LIMIT_PER_MINUTE = 5

# One-time code auth (registration entry)
ONE_TIME_CODE_RATE_LIMIT_PER_MINUTE = 3
ONE_TIME_CODE_TTL_SECONDS = 300

# OCR integration — env vars loaded by load_dotenv(), exported here for
# apps.integrations.ocr to read via django.conf.settings.
OCR_PROVIDER_MODE = os.environ.get("OCR_PROVIDER_MODE") or "stub"
TINY_IDP_API_URL = os.environ.get("TINY_IDP_API_URL", "")
TINY_IDP_API_KEY = os.environ.get("TINY_IDP_API_KEY", "")
OCR_ENCRYPTION_KEY = os.environ.get("OCR_ENCRYPTION_KEY", "")

# Agreement-platform integration (P5 Slice D — DocuSeal self-hosted).
AGREEMENT_PROVIDER_MODE = os.environ.get("AGREEMENT_PROVIDER_MODE") or "stub"
DOCUSEAL_API_URL = os.environ.get("DOCUSEAL_API_URL", "")
DOCUSEAL_API_KEY = os.environ.get("DOCUSEAL_API_KEY", "")
DOCUSEAL_TEMPLATE_ID = os.environ.get("DOCUSEAL_TEMPLATE_ID", "")
DOCUSEAL_WEBHOOK_SECRET = os.environ.get("DOCUSEAL_WEBHOOK_SECRET", "")
# Agreement numbers sent to DocuSeal: {PREFIX}-{YEAR}-{SEQUENCE:03d}
AGREEMENT_NUMBER_PREFIX = os.environ.get("AGREEMENT_NUMBER_PREFIX") or "FKC"

# Invoicing integration (P6 Slice B — Invoice Ninja self-hosted).
INVOICE_PROVIDER_MODE = os.environ.get("INVOICE_PROVIDER_MODE") or "stub"
INVOICE_NINJA_API_URL = os.environ.get("INVOICE_NINJA_API_URL", "")
INVOICE_NINJA_API_KEY = os.environ.get("INVOICE_NINJA_API_KEY", "")
# Billing auto-send (P6 invoice issue/send policy). When False, the nightly
# send job is a no-op — deploy the machinery, verify on one parent, then flip on.
BILLING_AUTOSEND_ENABLED = os.environ.get("BILLING_AUTOSEND_ENABLED", "false").lower() in {"1", "true", "yes"}
# Hour (local time) for the nightly send sweep; offset from payment-sync (3).
BILLING_SEND_DUE_HOUR = int(os.environ.get("BILLING_SEND_DUE_HOUR", "4"))
INVOICE_NINJA_NUMBER_PREFIX = os.environ.get("INVOICE_NINJA_NUMBER_PREFIX") or "MMS"
# Localization / time zone. Datetimes are stored in UTC (USE_TZ); TIME_ZONE is
# the project's local zone used for `timezone.localtime()` and admin rendering.
# This also fixes the local hour interpreted by the nightly payment-sync schedule
# below (without it, Django's America/Chicago default would offset the run time).
TIME_ZONE = os.environ.get("TIME_ZONE") or "Europe/Riga"
USE_TZ = True

# Hour-of-day (local time, 0-23) for the nightly billing payment-sync sweep.
# Editable per-environment; the django-q2 Schedule row created by
# apps/billing/migrations/0005 reads this for its initial next_run.
BILLING_PAYMENT_SYNC_HOUR = int(os.environ.get("BILLING_PAYMENT_SYNC_HOUR", "3"))

# Audit log retention (P7). Nightly prune deletes events older than this many days.
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "730"))
# Local-time hour for the nightly audit prune (offset from billing 3/4).
AUDIT_PRUNE_HOUR = int(os.environ.get("AUDIT_PRUNE_HOUR", "2"))

# Analytics (P10). Disabled by default; enable browser/server channels separately.
ANALYTICS_PROVIDER = os.environ.get("ANALYTICS_PROVIDER") or "stub"
ANALYTICS_BROWSER_ENABLED = os.environ.get("ANALYTICS_BROWSER_ENABLED", "false").lower() in {"1", "true", "yes"}
ANALYTICS_SERVER_ENABLED = os.environ.get("ANALYTICS_SERVER_ENABLED", "false").lower() in {"1", "true", "yes"}
ANALYTICS_DOMAIN = os.environ.get("ANALYTICS_DOMAIN", "")
ANALYTICS_SITE_ID = os.environ.get("ANALYTICS_SITE_ID", "")
ANALYTICS_API_URL = os.environ.get("ANALYTICS_API_URL", "")
ANALYTICS_API_KEY = os.environ.get("ANALYTICS_API_KEY", "")
ANALYTICS_TIMEOUT_SECONDS = float(os.environ.get("ANALYTICS_TIMEOUT_SECONDS", "2"))

# Document upload constraints (used by the async upload endpoint, P3.5).
DOCUMENT_UPLOAD_MAX_BYTES = int(
    os.environ.get("DOCUMENT_UPLOAD_MAX_BYTES", str(8 * 1024 * 1024))  # 8 MiB
)
DOCUMENT_UPLOAD_ALLOWED_CONTENT_TYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
)

# Surface uncaught view exceptions to stderr so production deployments
# (DEBUG=False) don't silently swallow tracebacks. Without this, Django's
# default logging routes `django.request` errors to `mail_admins` only —
# meaning every 500 response renders an empty 145-byte page and the
# Python traceback never reaches docker logs / journalctl. We hit this
# during the 2026-05-31 LAN UAT and lost ~30 minutes to "no traceback
# anywhere" before realising production logging wasn't configured.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {name} {process:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.server": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Background-job runner (django-q2) — uses the Django DB as broker so we
# don't need Redis for this single-instance app. Worker starts with
# `uv run python manage.py qcluster`.
Q_CLUSTER = {
    "name": "fk_cesis_mms",
    "workers": 2,
    "timeout": 60,
    "retry": 90,
    "max_attempts": 2,
    "orm": "default",
    "sync": os.environ.get("Q_CLUSTER_SYNC", "").lower() in {"1", "true", "yes"},
}

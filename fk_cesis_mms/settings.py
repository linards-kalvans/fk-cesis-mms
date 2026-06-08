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
    "django.contrib.admin",
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
    # Background-job runner (P3.5)
    "django_q",
]

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

# Invoicing integration (P6 Slice B — Invoice Ninja self-hosted).
INVOICE_PROVIDER_MODE = os.environ.get("INVOICE_PROVIDER_MODE") or "stub"
INVOICE_NINJA_API_URL = os.environ.get("INVOICE_NINJA_API_URL", "")
INVOICE_NINJA_API_KEY = os.environ.get("INVOICE_NINJA_API_KEY", "")
INVOICE_NINJA_NUMBER_PREFIX = os.environ.get("INVOICE_NINJA_NUMBER_PREFIX") or "MMS"

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

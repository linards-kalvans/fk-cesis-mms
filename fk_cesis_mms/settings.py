"""
Django settings for fk_cesis_mms.

Task 1: minimal scaffold. Full settings will be fleshed out in later tasks.
"""

import os
from urllib.parse import urlparse

from dotenv import load_dotenv
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Auto-load .env from project root (one level above this file's parent).
load_dotenv(dotenv_path=BASE_DIR / ".env")

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-task1-placeholder-change-in-production-abc123",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Derive ALLOWED_HOSTS from SITE_URL.
SITE_URL = os.environ.get("SITE_URL", "http://localhost")
_parsed = urlparse(SITE_URL)
ALLOWED_HOSTS: list[str] = [_parsed.hostname] if _parsed.hostname else []
ALLOWED_HOSTS.extend(["localhost", "127.0.0.1", "testserver", "192.168.3.245"])

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
    "apps.billing",
    "apps.documents",
    "apps.integrations",
]

MIDDLEWARE = [
    "apps.core.middleware.LocalInsecureCookieMiddleware",
    "django.middleware.security.SecurityMiddleware",
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

# Database — PostgreSQL (psycopg) in production, SQLite for dev
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static", BASE_DIR / "style-guide"]

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

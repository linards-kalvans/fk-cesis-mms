"""Analytics configuration helpers (P10).

Reads env-driven settings via django.conf and answers two boolean questions
the rest of the analytics app asks on every call:

- `analytics_browser_configured()` — should the parent browser render the
  analytics script and event-tracker JS?
- `analytics_server_configured()` — should `track_event` actually send
  anything to the configured provider?

Both default to False so the app is silent until staff explicitly turn it on.
"""

from __future__ import annotations

from django.conf import settings

SUPPORTED_PROVIDERS = {"stub", "plausible", "umami"}


def analytics_provider() -> str:
    provider = str(getattr(settings, "ANALYTICS_PROVIDER", "stub") or "stub").lower()
    if provider not in SUPPORTED_PROVIDERS:
        return "stub"
    return provider


def analytics_domain() -> str:
    return str(getattr(settings, "ANALYTICS_DOMAIN", "") or "").strip()


def analytics_api_url() -> str:
    return str(getattr(settings, "ANALYTICS_API_URL", "") or "").rstrip("/")


def analytics_site_id() -> str:
    return str(getattr(settings, "ANALYTICS_SITE_ID", "") or "").strip()


def analytics_browser_configured() -> bool:
    if not bool(getattr(settings, "ANALYTICS_BROWSER_ENABLED", False)):
        return False
    provider = analytics_provider()
    if provider == "stub":
        return True
    if provider == "umami":
        return bool(analytics_site_id() and analytics_api_url())
    return bool(analytics_domain() and analytics_api_url())


def analytics_server_configured() -> bool:
    if not bool(getattr(settings, "ANALYTICS_SERVER_ENABLED", False)):
        return False
    provider = analytics_provider()
    if provider == "stub":
        return True
    if provider == "umami":
        return bool(analytics_site_id() and analytics_api_url())
    return bool(analytics_domain() and analytics_api_url())


def browser_template_context() -> dict[str, object]:
    return {
        "analytics_browser_enabled": analytics_browser_configured(),
        "analytics_provider": analytics_provider(),
        "analytics_domain": analytics_domain(),
        "analytics_api_url": analytics_api_url(),
        "analytics_site_id": analytics_site_id(),
    }

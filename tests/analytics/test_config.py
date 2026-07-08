"""Tests for analytics configuration helpers.

Red phase: apps.analytics does not exist yet.
"""

from django.test import override_settings


@override_settings(
    ANALYTICS_BROWSER_ENABLED=False,
    ANALYTICS_SERVER_ENABLED=False,
    ANALYTICS_PROVIDER="stub",
    ANALYTICS_DOMAIN="",
    ANALYTICS_API_URL="",
)
def test_analytics_disabled_by_default():
    from apps.analytics.config import (
        analytics_browser_configured,
        analytics_server_configured,
    )

    assert analytics_browser_configured() is False
    assert analytics_server_configured() is False


@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_browser_configured_when_enabled_with_provider_domain_api_url():
    from apps.analytics.config import analytics_browser_configured

    assert analytics_browser_configured() is True


@override_settings(
    ANALYTICS_SERVER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_server_configured_when_enabled_with_provider_domain_api_url():
    from apps.analytics.config import analytics_server_configured

    assert analytics_server_configured() is True


@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_browser_not_configured_when_domain_missing():
    from apps.analytics.config import analytics_browser_configured

    assert analytics_browser_configured() is False


@override_settings(
    ANALYTICS_SERVER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="",
)
def test_server_not_configured_when_api_url_missing():
    from apps.analytics.config import analytics_server_configured

    assert analytics_server_configured() is False


@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_SITE_ID="uuid-site",
    ANALYTICS_API_URL="https://umami.example.com",
)
def test_umami_browser_configured_when_enabled_with_site_id_and_api_url():
    from apps.analytics.config import analytics_browser_configured

    assert analytics_browser_configured() is True


@override_settings(
    ANALYTICS_SERVER_ENABLED=True,
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_SITE_ID="uuid-site",
    ANALYTICS_API_URL="https://umami.example.com",
)
def test_umami_server_configured_when_enabled_with_site_id_and_api_url():
    from apps.analytics.config import analytics_server_configured

    assert analytics_server_configured() is True


@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_SERVER_ENABLED=True,
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_SITE_ID="",
    ANALYTICS_API_URL="https://umami.example.com",
)
def test_umami_not_configured_when_site_id_missing():
    from apps.analytics.config import (
        analytics_browser_configured,
        analytics_server_configured,
    )

    assert analytics_browser_configured() is False
    assert analytics_server_configured() is False


@override_settings(ANALYTICS_PROVIDER="not-real")
def test_unknown_provider_falls_back_to_stub():
    from apps.analytics.config import analytics_provider

    assert analytics_provider() == "stub"

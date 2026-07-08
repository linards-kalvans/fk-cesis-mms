"""Tests for browser analytics template rendering.

Red phase: analytics partial and template tag do not exist yet.
"""

import pytest
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
@override_settings(ANALYTICS_BROWSER_ENABLED=False, ANALYTICS_PROVIDER="stub")
def test_parent_page_does_not_render_analytics_script_when_disabled(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"analytics_events.js" not in response.content
    assert b"data-analytics-browser" not in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_parent_page_renders_analytics_script_when_enabled(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"analytics_events.js" in response.content
    assert b"data-analytics-browser" in response.content
    assert b"mms.fkcesis.lv" in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_admin_index_never_renders_analytics_script(staff_client):
    response = staff_client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert b"analytics_events.js" not in response.content
    assert b"data-analytics-browser" not in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_parent_page_bootstraps_referral_code_when_session_has_one(client):
    session = client.session
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"fkAnalyticsBaseProps" in response.content
    # The sanitized value is JS-escaped (escapejs encodes the dash), so the
    # JS string literal encodes it as coach\u002Da — assert against the
    # assignment so the contract is "we bootstrap a referral_code prop".
    assert b'fkAnalyticsBaseProps.referral_code = "coach' in response.content
    assert b"parent@example.com" not in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_parent_page_omits_bootstrap_when_no_session_referral(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"fkAnalyticsBaseProps" not in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="plausible",
    ANALYTICS_DOMAIN="mms.fkcesis.lv",
    ANALYTICS_API_URL="https://plausible.io",
)
def test_parent_page_omits_bootstrap_for_invalid_session_referral(client):
    session = client.session
    session["registration_referral_code"] = "parent@example.com"
    session.save()

    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"fkAnalyticsBaseProps" not in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_SITE_ID="uuid-site",
    ANALYTICS_API_URL="https://umami.example.com",
)
def test_parent_page_renders_umami_script_when_enabled(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b"analytics_events.js" in response.content
    assert b"data-analytics-browser" in response.content
    assert b'src="https://umami.example.com/script.js"' in response.content
    assert b'data-website-id="uuid-site"' in response.content
    assert b"window.umami.track" in response.content


@pytest.mark.django_db
@override_settings(
    ANALYTICS_BROWSER_ENABLED=True,
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_SITE_ID="uuid-site",
    ANALYTICS_API_URL="https://umami.example.com",
)
def test_admin_index_never_renders_umami_analytics_script(staff_client):
    response = staff_client.get(reverse("admin:index"))

    assert response.status_code == 200
    assert b"analytics_events.js" not in response.content
    assert b"data-analytics-browser" not in response.content
    assert b"umami.example.com" not in response.content

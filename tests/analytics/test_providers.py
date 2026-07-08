"""Tests for analytics provider HTTP payloads."""

from unittest.mock import patch

from django.test import RequestFactory, override_settings


@override_settings(
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_API_URL="https://umami.example.com",
    ANALYTICS_SITE_ID="uuid-site",
    ANALYTICS_TIMEOUT_SECONDS=2,
)
def test_umami_provider_sends_server_event_payload():
    from apps.analytics.providers import send_event

    request = RequestFactory().get("/register/?ref=coach-a", HTTP_USER_AGENT="pytest-agent")

    with patch("apps.analytics.providers.requests.post") as post:
        send_event(
            "registration_start",
            {"page_area": "registration", "referral_code": "coach-a"},
            request=request,
        )

    post.assert_called_once()
    url = post.call_args.args[0]
    kwargs = post.call_args.kwargs
    assert url == "https://umami.example.com/api/send"
    assert kwargs["json"] == {
        "type": "event",
        "payload": {
            "website": "uuid-site",
            "hostname": "testserver",
            "language": "lv-LV",
            "url": "/register/",
            "name": "registration_start",
            "data": {"page_area": "registration", "referral_code": "coach-a"},
        },
    }
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["User-Agent"] == "pytest-agent"
    assert kwargs["timeout"] == 2


@override_settings(
    ANALYTICS_PROVIDER="umami",
    ANALYTICS_API_URL="https://umami.example.com",
    ANALYTICS_SITE_ID="",
)
def test_umami_provider_noops_when_site_id_missing():
    from apps.analytics.providers import send_event

    with patch("apps.analytics.providers.requests.post") as post:
        send_event("registration_start", {}, request=RequestFactory().get("/register/"))

    post.assert_not_called()

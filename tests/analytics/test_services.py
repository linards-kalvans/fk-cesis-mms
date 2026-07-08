"""Tests for analytics track_event service and milestone helpers.

Red phase: apps.analytics.services and apps.analytics.providers do not exist yet.
"""

from unittest.mock import Mock

from django.test import RequestFactory, override_settings

from apps.analytics import providers
from apps.analytics.services import (
    track_application_submitted,
    track_email_verified,
    track_event,
    track_registration_start,
)


@override_settings(ANALYTICS_SERVER_ENABLED=False, ANALYTICS_PROVIDER="stub")
def test_track_event_disabled_sends_nothing(monkeypatch):
    send = Mock()
    monkeypatch.setattr(providers, "send_event", send)

    track_event("registration_start", {"page_area": "registration"})

    send.assert_not_called()


@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_track_event_sanitizes_props_before_provider_send(monkeypatch):
    send = Mock()
    monkeypatch.setattr(providers, "send_event", send)

    track_event(
        "registration_start",
        {"page_area": "registration", "email": "parent@example.com"},
    )

    send.assert_called_once()
    call_args = send.call_args
    assert call_args.args[0] == "registration_start"
    assert call_args.args[1] == {"page_area": "registration"}


@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_track_event_swallows_provider_failure(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("analytics down")

    monkeypatch.setattr(providers, "send_event", fail)

    # Must not raise.
    track_event("registration_start", {"page_area": "registration"})


@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_milestone_helpers_emit_fixed_event_names_with_referral_code(monkeypatch):
    send = Mock()
    monkeypatch.setattr(providers, "send_event", send)
    request = RequestFactory().get("/register/?ref=coach-a")

    track_registration_start(request, referral_code="coach-a")
    track_email_verified(request, referral_code="coach-a")
    track_application_submitted(
        request, referral_code="coach-a", application_status="submitted"
    )

    event_names = [call.args[0] for call in send.call_args_list]
    assert event_names == [
        "registration_start",
        "email_verified",
        "application_submitted",
    ]
    # First call carries referral_code.
    assert send.call_args_list[0].args[1]["referral_code"] == "coach-a"

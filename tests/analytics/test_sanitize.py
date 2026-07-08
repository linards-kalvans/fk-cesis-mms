"""Tests for analytics referral-code and event-property sanitization.

Red phase: apps.analytics.sanitize does not exist yet.
"""

from apps.analytics.sanitize import sanitize_event_props, sanitize_referral_code


def test_sanitize_referral_code_normalizes_valid_code():
    assert sanitize_referral_code(" Coach-A_42 ") == "coach-a_42"


def test_sanitize_referral_code_rejects_unsafe_characters():
    assert sanitize_referral_code("coach@example.com") == ""
    assert sanitize_referral_code("../secret") == ""
    assert sanitize_referral_code("Jānis") == ""
    assert sanitize_referral_code("hello world") == ""


def test_sanitize_referral_code_caps_length_at_64():
    assert sanitize_referral_code("a" * 100) == "a" * 64


def test_sanitize_event_props_keeps_only_allowlisted_keys():
    props = sanitize_event_props(
        {
            "page_area": "portal",
            "event_source": "hero",
            "application_status": "draft",
            "referral_code": "coach-a",
            "error_kind": "empty_state",
            "email": "parent@example.com",
            "guardian_id": 123,
        }
    )
    assert props == {
        "page_area": "portal",
        "event_source": "hero",
        "application_status": "draft",
        "referral_code": "coach-a",
        "error_kind": "empty_state",
    }


def test_sanitize_event_props_drops_unsafe_referral_code():
    assert sanitize_event_props({"referral_code": "BAD CODE!"}) == {}


def test_sanitize_event_props_handles_none_input():
    assert sanitize_event_props(None) == {}
    assert sanitize_event_props({}) == {}

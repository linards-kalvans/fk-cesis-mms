"""Tests for server-side analytics milestone hooks in existing views.

Red phase: views do not call analytics milestone helpers yet.
"""

from unittest.mock import Mock

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.services import issue_one_time_code
from apps.analytics import services as analytics_services
from apps.registrations.models import RegistrationApplication


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_email_verified_milestone_emitted_with_referral_code(client, monkeypatch):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_email_verified", send)
    code = issue_one_time_code("parent@example.com")

    session = client.session
    session["pending_verification_email"] = "parent@example.com"
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = client.post(
        reverse("accounts:verify-one-time-code"), {"code": code}
    )

    assert response.status_code == 302
    send.assert_called_once()
    assert send.call_args.kwargs["referral_code"] == "coach-a"


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_registration_start_milestone_emitted_with_referral_code(
    verified_client, monkeypatch, kit_sizes
):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_registration_start", send)

    session = verified_client.session
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    send.assert_called_once()
    assert send.call_args.kwargs["referral_code"] == "coach-a"


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_application_submitted_milestone_emitted_with_status_and_referral(
    verified_client, draft_with_documents, submit_payload, monkeypatch
):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_application_submitted", send)
    draft_with_documents.referral_code = "coach-a"
    draft_with_documents.save(update_fields=["referral_code", "updated_at"])

    response = verified_client.post(
        reverse("registrations:application-workspace", args=[draft_with_documents.pk]),
        {**submit_payload, "submit_action": "submit"},
    )

    assert response.status_code == 302
    draft_with_documents.refresh_from_db()
    assert draft_with_documents.status == RegistrationApplication.Status.SUBMITTED
    send.assert_called_once()
    assert send.call_args.kwargs["referral_code"] == "coach-a"
    assert send.call_args.kwargs["application_status"] == "submitted"


@pytest.mark.django_db
@override_settings(ANALYTICS_SERVER_ENABLED=True, ANALYTICS_PROVIDER="stub")
def test_invalid_submit_does_not_emit_application_submitted(
    verified_client, draft_with_documents, monkeypatch
):
    send = Mock()
    monkeypatch.setattr(analytics_services, "track_application_submitted", send)

    # POST with empty payload — form invalid, no submit.
    response = verified_client.post(
        reverse("registrations:application-workspace", args=[draft_with_documents.pk]),
        {"submit_action": "submit"},
    )

    send.assert_not_called()

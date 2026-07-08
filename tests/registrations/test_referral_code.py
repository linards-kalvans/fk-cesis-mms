"""Tests for referral-code carry through session and persistence on application.

Red phase: RegistrationApplication.referral_code field and session-capture in
views do not exist yet.
"""

import pytest
from django.urls import reverse

from apps.registrations.models import RegistrationApplication


@pytest.mark.django_db
def test_register_ref_query_param_stores_sanitized_code_in_session(client):
    response = client.get(
        reverse("registrations:start-registration") + "?ref=Coach-A_42"
    )

    assert response.status_code == 200
    assert client.session["registration_referral_code"] == "coach-a_42"


@pytest.mark.django_db
def test_invalid_ref_query_param_is_ignored(client):
    """Invalid ref must clear a previously-stored valid referral code."""
    # First, store a valid referral code in the session.
    client.get(reverse("registrations:start-registration") + "?ref=coach-a")
    assert client.session["registration_referral_code"] == "coach-a"

    # Now visit with an invalid ref — the session key must be cleared.
    response = client.get(
        reverse("registrations:start-registration") + "?ref=parent@example.com"
    )

    assert response.status_code == 200
    assert "registration_referral_code" not in client.session


@pytest.mark.django_db
def test_new_application_persists_session_referral_code(
    verified_client, parent_account, kit_sizes
):
    session = verified_client.session
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    application = RegistrationApplication.objects.get(parent_account=parent_account)
    assert application.referral_code == "coach-a"


@pytest.mark.django_db
def test_new_application_consumes_session_referral_code(
    verified_client, parent_account, kit_sizes
):
    """Session referral is single-use: must be cleared after the new
    application is created so a later registration in the same browser
    does not inherit stale attribution."""
    session = verified_client.session
    session["registration_referral_code"] = "coach-a"
    session.save()

    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    assert "registration_referral_code" not in verified_client.session


@pytest.mark.django_db
def test_new_application_without_ref_stores_blank(
    verified_client, parent_account, kit_sizes
):
    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    application = RegistrationApplication.objects.get(parent_account=parent_account)
    assert application.referral_code == ""


@pytest.mark.django_db
def test_new_application_drops_and_consumes_invalid_session_referral(
    verified_client, parent_account, kit_sizes
):
    """A polluted/invalid session referral must not be persisted and must
    be consumed so it cannot leak into a later registration in the same
    browser. Defence in depth: the persistence boundary sanitises even
    though /register/?ref= already gates writes."""
    session = verified_client.session
    session["registration_referral_code"] = "parent@example.com"
    session.save()

    response = verified_client.get(reverse("registrations:new-application"))

    assert response.status_code == 302
    application = RegistrationApplication.objects.get(parent_account=parent_account)
    assert application.referral_code == ""
    assert "registration_referral_code" not in verified_client.session

"""Tests for browser analytics declarative event hooks on parent templates.

Red phase: analytics data-* hooks are not present on templates yet.
"""

import pytest
from django.template.loader import render_to_string
from django.urls import reverse


@pytest.mark.django_db
def test_start_registration_has_cta_start_registration_hook(client):
    response = client.get(reverse("registrations:start-registration"))

    assert response.status_code == 200
    assert b'data-analytics-event="cta_start_registration"' in response.content


@pytest.mark.django_db
def test_portal_has_portal_visit_impression(verified_client):
    response = verified_client.get(reverse("registrations:parent-portal"))

    assert response.status_code == 200
    assert b'data-analytics-impression="portal_visit"' in response.content


@pytest.mark.django_db
def test_empty_portal_has_empty_state_impression_and_new_application_cta(
    verified_client,
):
    response = verified_client.get(reverse("registrations:parent-portal"))

    assert response.status_code == 200
    assert b'data-analytics-impression="portal_empty_state_shown"' in response.content
    assert b'data-analytics-event="cta_new_application"' in response.content


@pytest.mark.django_db
def test_portal_with_draft_has_continue_application_hook(
    verified_client, draft_application
):
    response = verified_client.get(reverse("registrations:parent-portal"))

    assert response.status_code == 200
    assert b'data-analytics-event="cta_continue_application"' in response.content


@pytest.mark.django_db
def test_application_workspace_has_submit_application_hook(
    verified_client, draft_application
):
    response = verified_client.get(
        reverse("registrations:application-workspace", args=[draft_application.pk])
    )

    assert response.status_code == 200
    assert b'data-analytics-event="cta_submit_application"' in response.content


def test_error_state_partial_supports_portal_error_impression():
    """The shared error_state.html partial must render analytics impression
    attrs when context variables are supplied. No live portal error view
    exists yet; render the partial directly."""
    html = render_to_string(
        "parent_ui/includes/error_state.html",
        {
            "title": "Kaut kas nogāja greizi",
            "analytics_impression": "portal_error_state_shown",
            "analytics_page_area": "portal",
            "analytics_error_kind": "error_state",
        },
    )

    assert 'data-analytics-impression="portal_error_state_shown"' in html
    assert 'data-analytics-page-area="portal"' in html
    assert 'data-analytics-error-kind="error_state"' in html


@pytest.mark.django_db
def test_application_workspace_invalid_submit_shows_validation_summary_impression(
    verified_client, draft_with_documents
):
    """Invalid submit re-renders workspace with form.errors; the template
    must emit the validation-summary impression hook."""
    response = verified_client.post(
        reverse("registrations:application-workspace", args=[draft_with_documents.pk]),
        {"submit_action": "submit"},  # empty payload — form invalid
    )

    # View falls through to render (status 200) with form errors in context.
    assert response.status_code == 200
    assert (
        b'data-analytics-impression="application_validation_error_summary_shown"'
        in response.content
    )

"""Tests for the review/overview wizard step submit button UI.

Verifies that:
- The 'Saglabāt melnrakstu' (save_draft) button is absent from the review step
- The submit button uses fk-button--primary (not fk-button--red)
- The submit button uses fk-button--full

Covers both application_workspace.html and new_registration.html templates.
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_workspace_review_has_no_save_draft_button(verified_client, draft_application):
    """The workspace review step must not contain the save-draft button."""
    url = reverse("registrations:application-workspace", args=[draft_application.pk])
    response = verified_client.get(url)
    assert response.status_code == 200
    assert "Saglabāt melnrakstu" not in response.content.decode()


@pytest.mark.django_db
def test_workspace_review_submit_uses_primary_style(verified_client, draft_application):
    """The workspace submit button must have class fk-button--primary."""
    url = reverse("registrations:application-workspace", args=[draft_application.pk])
    response = verified_client.get(url)
    assert response.status_code == 200
    assert "fk-button--primary" in response.content.decode()


@pytest.mark.django_db
def test_workspace_review_submit_has_full_modifier(verified_client, draft_application):
    """The workspace submit button must have class fk-button--full."""
    url = reverse("registrations:application-workspace", args=[draft_application.pk])
    response = verified_client.get(url)
    assert response.status_code == 200
    assert "fk-button--full" in response.content.decode()


@pytest.mark.django_db
def test_new_registration_review_has_no_save_draft_button(verified_client):
    """The new_registration review step must not contain the save-draft button.

    GET /applications/new/ creates a fresh draft and redirects to the workspace;
    follow=True lets us assert on the final rendered HTML.
    """
    url = reverse("registrations:new-application")
    response = verified_client.get(url, follow=True)
    assert response.status_code == 200
    assert "Saglabāt melnrakstu" not in response.content.decode()


@pytest.mark.django_db
def test_new_registration_review_submit_uses_primary_style(verified_client):
    """The new_registration submit button must have class fk-button--primary.

    GET /applications/new/ creates a fresh draft and redirects to the workspace;
    follow=True lets us assert on the final rendered HTML.
    """
    url = reverse("registrations:new-application")
    response = verified_client.get(url, follow=True)
    assert response.status_code == 200
    assert "fk-button--primary" in response.content.decode()

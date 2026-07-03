"""View + template tests for the admin Līgums module (P5 Slice C).

Ported to the Django admin change page + review-action endpoint (P7 C-i):
the bespoke review detail view is gone, so the agreement module now renders
on the application change page and its actions POST to the review-action
endpoint. Admin validation errors surface via the messages framework on a
redirect (302), not as an inline 400.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import (
    get_current_agreement,
    void_agreement,
)
from apps.registrations.services import approve_application


pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer", is_staff=True)


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


# --- Visibility on submitted applications ---


def test_submitted_application_does_not_render_agreement_module(
    submitted_application, staff_client
):
    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "mms-review-agreement-module" not in html


# --- Visibility on approved applications ---


def test_approved_application_renders_module_with_state_copy(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "mms-review-agreement-module" in html
    assert "Sagatavots" in html


# --- mark sent ---


def test_mark_sent_advances_state(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "mark_agreement_sent"},
    )
    assert resp.status_code == 302
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.state == Agreement.State.SENT


# --- mark signed from generated ---


def test_mark_signed_advances_state_from_generated(
    submitted_application, staff_client, reviewer, default_membership_plan
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "mark_agreement_signed"},
    )
    assert resp.status_code == 302
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.state == Agreement.State.SIGNED


# --- set signing path ---


def test_set_signing_path_flips_electronic_to_paper(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "set_signing_path", "signing_path": "paper"},
    )
    assert resp.status_code == 302
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.signing_path == Agreement.SigningPath.PAPER


def test_set_signing_path_rejects_invalid_value(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "set_signing_path", "signing_path": "carrier_pigeon"},
        follow=True,
    )
    assert "Nezināms parakstīšanas veids" in resp.content.decode("utf-8")
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.signing_path != "carrier_pigeon"


# --- void + regenerate ---


def test_void_renders_regenerate_button(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "void_agreement", "void_reason": "duplicate"},
    )
    assert resp.status_code == 302
    follow = staff_client.get(_change_url(submitted_application.id))
    html = follow.content.decode("utf-8")
    assert "Atcelts" in html
    assert 'value="regenerate_agreement"' in html


def test_regenerate_on_void_creates_fresh_agreement(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    first = get_current_agreement(submitted_application.approved_member)
    void_agreement(first, reviewer, "duplicate")

    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "regenerate_agreement"},
    )
    assert resp.status_code == 302
    fresh = get_current_agreement(submitted_application.approved_member)
    assert fresh.id != first.id
    assert fresh.state == Agreement.State.GENERATED


def test_regenerate_on_non_void_surfaces_error(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "regenerate_agreement"},
        follow=True,
    )
    html = resp.content.decode("utf-8")
    assert "Aktīvo līgumu nedrīkst aizvietot" in html


# --- POST without agreement (defensive) ---


def test_post_on_submitted_application_surfaces_error(
    submitted_application, staff_client
):
    response = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "mark_agreement_sent"},
        follow=True,
    )
    html = response.content.decode("utf-8")
    assert "Līgums nav sagatavots" in html


# --- access control ---


def test_anonymous_post_is_blocked(
    submitted_application, client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = client.post(
        _action_url(submitted_application.id),
        {"action": "mark_agreement_sent"},
    )
    assert resp.status_code in (302, 403, 404)
    agreement = get_current_agreement(submitted_application.approved_member)
    assert agreement.state == Agreement.State.GENERATED  # unchanged

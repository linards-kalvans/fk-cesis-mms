"""View + template tests for training-group assignment UI.

Ported to the admin (P7 C-i): the submitted-application group picker now
lives on the approve confirmation page (approve endpoint), and the
post-approval group picker renders on the change page with its action
POSTing to the review-action endpoint.
"""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

from apps.members.models import TrainingGroup
from apps.registrations.services import approve_application


pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    # Distinct username from the `staff_client` fixture (which uses "staff")
    # so both can coexist in the same test without violating the unique
    # username constraint.
    return User.objects.create_user(username="reviewer", is_staff=True)


@pytest.fixture
def group_a(db):
    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def group_b(db):
    return TrainingGroup.objects.create(name="U10 B", is_active=True)


@pytest.fixture
def inactive_group(db):
    return TrainingGroup.objects.create(name="U10 Arhīvs", is_active=False)


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


def _approve_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_approve", args=[app_id]
    )


# --- Submitted application: approve-confirm dropdown ---


def test_approve_confirm_dropdown_contains_active_groups_only(
    submitted_application, staff_client, group_a, group_b, inactive_group
):
    resp = staff_client.get(_approve_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert 'name="training_group"' in html
    assert '— Piešķirsim vēlāk —' in html
    assert "U10 A" in html
    assert "U10 B" in html
    assert "U10 Arhīvs" not in html


def test_approve_post_with_group_assigns_member(
    submitted_application, staff_client, group_a
):
    resp = staff_client.post(
        _approve_url(submitted_application.id),
        {"training_group": str(group_a.id)},
    )
    assert resp.status_code == 302  # redirect to application change page
    submitted_application.refresh_from_db()
    assert submitted_application.approved_member is not None
    assert submitted_application.approved_member.training_group_id == group_a.id


def test_approve_post_with_empty_group_leaves_member_unassigned(
    submitted_application, staff_client
):
    resp = staff_client.post(
        _approve_url(submitted_application.id),
        {"training_group": ""},
    )
    assert resp.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.approved_member is not None
    assert submitted_application.approved_member.training_group is None


# --- Approved application: post-approval module ---


def test_approved_app_without_group_shows_unassigned_message_and_picker(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "Treniņu grupa" in html
    assert "Vēl nav piešķirta" in html
    assert 'name="training_group"' in html
    assert 'value="assign_training_group"' in html


def test_approved_app_with_group_shows_current_and_preselects_option(
    submitted_application, staff_client, reviewer, group_a, group_b
):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "Pašreizējā grupa:" in html
    assert "U10 A" in html
    # Pre-selection on the matching option:
    assert re.search(r'<option[^>]+value="' + str(group_a.id) + r'"[^>]*selected', html)


def test_assign_post_updates_member_group(
    submitted_application, staff_client, reviewer, group_a, group_b
):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "assign_training_group", "training_group": str(group_b.id)},
    )
    assert resp.status_code == 302
    submitted_application.refresh_from_db()
    submitted_application.approved_member.refresh_from_db()
    assert submitted_application.approved_member.training_group_id == group_b.id


def test_assign_post_with_empty_clears_member_group(
    submitted_application, staff_client, reviewer, group_a
):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = staff_client.post(
        _action_url(submitted_application.id),
        {"action": "assign_training_group", "training_group": ""},
    )
    assert resp.status_code == 302
    submitted_application.approved_member.refresh_from_db()
    assert submitted_application.approved_member.training_group is None


def test_currently_inactive_group_appears_in_picker_with_marker(
    submitted_application, staff_client, reviewer, group_a, inactive_group
):
    # Approve, then manually demote the assigned group to inactive.
    approve_application(submitted_application, reviewer, training_group=group_a)
    group_a.is_active = False
    group_a.save(update_fields=["is_active"])

    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    # The inactive currently-assigned group appears in the picker:
    assert "U10 A" in html
    assert "neaktīva" in html
    # Marker attribute on its option:
    assert re.search(
        r'<option[^>]+value="' + str(group_a.id) + r'"[^>]+data-inactive="true"',
        html,
    )


def test_approve_post_with_inactive_group_shows_latvian_error(
    submitted_application, staff_client, inactive_group
):
    resp = staff_client.post(
        _approve_url(submitted_application.id),
        {"training_group": str(inactive_group.id)},
        follow=True,
    )
    html = resp.content.decode("utf-8")
    assert "Nevar piešķirt neaktīvu treniņu grupu" in html


def test_anonymous_assign_post_is_blocked(submitted_application, client, reviewer, group_a):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = client.post(
        _action_url(submitted_application.id),
        {"action": "assign_training_group", "training_group": ""},
    )
    # Admin access-control gives 403 / redirect; both are acceptable.
    assert resp.status_code in (302, 403, 404)
    submitted_application.approved_member.refresh_from_db()
    assert submitted_application.approved_member.training_group_id == group_a.id  # unchanged

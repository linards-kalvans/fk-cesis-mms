"""Parent-facing surfaces show agreement status copy (P5 Slice C)."""

from __future__ import annotations

import pytest

from apps.agreements.models import Agreement
from apps.agreements.services import (
    mark_agreement_sent,
    mark_agreement_signed,
    set_signing_path,
    void_agreement,
)
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


def _portal_url():
    from django.urls import reverse

    return reverse("registrations:parent-portal")


def _workspace_url(app_id):
    from django.urls import reverse

    return reverse("registrations:application-workspace", args=[app_id])


# --- Portal ---


def test_portal_shows_generated_copy_for_approved_app(
    submitted_application, verified_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = verified_client.get(_portal_url())
    html = resp.content.decode("utf-8")
    assert "Līgums sagatavots, drīzumā saņemsiet to parakstīšanai." in html


def test_portal_shows_sent_electronic_copy(
    submitted_application, verified_client, reviewer
):
    approve_application(submitted_application, reviewer)
    agreement = submitted_application.approved_member.agreements.get(is_current=True)
    set_signing_path(agreement, Agreement.SigningPath.ELECTRONIC, reviewer)
    mark_agreement_sent(agreement, reviewer)
    resp = verified_client.get(_portal_url())
    html = resp.content.decode("utf-8")
    assert "Līgums nosūtīts uz e-pastu parakstīšanai." in html


def test_portal_shows_sent_paper_copy(
    submitted_application, verified_client, reviewer
):
    approve_application(submitted_application, reviewer)
    agreement = submitted_application.approved_member.agreements.get(is_current=True)
    set_signing_path(agreement, Agreement.SigningPath.PAPER, reviewer)
    mark_agreement_sent(agreement, reviewer)
    resp = verified_client.get(_portal_url())
    html = resp.content.decode("utf-8")
    assert "Klubs sazināsies ar Jums par līguma parakstīšanu." in html


def test_portal_shows_signed_copy(
    submitted_application, verified_client, reviewer, default_membership_plan
):
    approve_application(submitted_application, reviewer)
    agreement = submitted_application.approved_member.agreements.get(is_current=True)
    mark_agreement_signed(agreement, reviewer)
    resp = verified_client.get(_portal_url())
    html = resp.content.decode("utf-8")
    assert "Līgums parakstīts" in html


def test_portal_shows_void_copy(
    submitted_application, verified_client, reviewer
):
    approve_application(submitted_application, reviewer)
    agreement = submitted_application.approved_member.agreements.get(is_current=True)
    void_agreement(agreement, reviewer, "duplicate")
    resp = verified_client.get(_portal_url())
    html = resp.content.decode("utf-8")
    assert "Līgums atcelts." in html


def test_portal_pre_approval_application_shows_no_agreement_line(
    submitted_application, verified_client
):
    resp = verified_client.get(_portal_url())
    html = resp.content.decode("utf-8")
    assert "fk-app-agreement-status" not in html


# --- Workspace ---


def test_workspace_post_approval_shows_status_copy(
    submitted_application, verified_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = verified_client.get(_workspace_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "Līgums sagatavots, drīzumā saņemsiet to parakstīšanai." in html

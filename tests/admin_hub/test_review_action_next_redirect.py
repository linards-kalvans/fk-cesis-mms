"""review_action_view must honour a validated `next` for the actions the
Hub's risky-actions tray drives (request_fix, reject) plus the agreement/
billing actions Tasks 6-7 will drive from the Hub (set_signing_path,
void_agreement, regenerate_agreement, create_next_season_billing).

Every action's existing no-`next` destination must be unchanged - staff use
these flows in Django admin today. `reject` is the one action whose success
path falls back to the changelist rather than the change page, so it gets
its own dedicated "no next" assertion distinct from the others.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import (
    get_current_agreement,
    set_billing_setup,
)
from apps.agreements.services import void_agreement as void_agreement_service
from apps.billing.models import MembershipPlan
from apps.registrations.services import approve_application

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]

HUB_URL = "/hub/pieteikumi/"


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _changelist_url():
    return reverse("admin:registrations_registrationapplication_changelist")


@pytest.fixture
def signed_active_application(submitted_application, reviewer):
    """An approved application whose current agreement is SIGNED with an
    explicit billing plan + first billing month, and an ACTIVE member - the
    minimum `_signed_active_agreement` guard needs for next-season billing."""
    app = approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(app.approved_member)
    plan = MembershipPlan.objects.create(
        name="Review Action Current Season Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    set_billing_setup(agreement, plan, first_billing_month="2026-09", actor=reviewer)
    agreement.state = Agreement.State.SIGNED
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "signed_at"])
    return app


@pytest.fixture
def next_season_plan(db):
    return MembershipPlan.objects.create(
        name="Review Action Next Season Plan",
        season="2027/2028",
        annual_amount=Decimal("320.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )


# ---------------------------------------------------------------------------
# request_fix
# ---------------------------------------------------------------------------


def test_request_fix_returns_to_a_safe_next(staff_client, submitted_application):
    resp = staff_client.post(
        f"{_action_url(submitted_application.pk)}?next={HUB_URL}",
        {"action": "request_fix", "review_message": "trūkst dokumenta"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_request_fix_without_next_still_lands_on_the_change_page(
    staff_client, submitted_application
):
    resp = staff_client.post(
        _action_url(submitted_application.pk),
        {"action": "request_fix", "review_message": "trūkst dokumenta"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == _change_url(submitted_application.pk)


# ---------------------------------------------------------------------------
# reject - the one action whose no-`next` fallback is the changelist, not
# the change page.
# ---------------------------------------------------------------------------


def test_reject_returns_to_a_safe_next(staff_client, submitted_application):
    resp = staff_client.post(
        f"{_action_url(submitted_application.pk)}?next={HUB_URL}",
        {"action": "reject", "review_message": "trūkst dokumenta"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_reject_ignores_an_offsite_next(staff_client, submitted_application):
    resp = staff_client.post(
        f"{_action_url(submitted_application.pk)}?next=https://evil.example.com/",
        {"action": "reject", "review_message": "trūkst dokumenta"},
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp["Location"]


def test_reject_without_next_still_lands_on_the_changelist(
    staff_client, submitted_application
):
    """A blind swap to `_after_review_redirect` would have silently changed
    this to the change page - `reject` must keep its own changelist
    fallback when no `next` is supplied."""
    resp = staff_client.post(
        _action_url(submitted_application.pk),
        {"action": "reject", "review_message": "trūkst dokumenta"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == _changelist_url()


# ---------------------------------------------------------------------------
# set_signing_path
# ---------------------------------------------------------------------------


def test_set_signing_path_returns_to_a_safe_next(staff_client, approved_application):
    resp = staff_client.post(
        f"{_action_url(approved_application.pk)}?next={HUB_URL}",
        {"action": "set_signing_path", "signing_path": "electronic"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_set_signing_path_without_next_still_lands_on_the_change_page(
    staff_client, approved_application
):
    resp = staff_client.post(
        _action_url(approved_application.pk),
        {"action": "set_signing_path", "signing_path": "electronic"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == _change_url(approved_application.pk)


# ---------------------------------------------------------------------------
# void_agreement
# ---------------------------------------------------------------------------


def test_void_agreement_returns_to_a_safe_next(staff_client, approved_application):
    resp = staff_client.post(
        f"{_action_url(approved_application.pk)}?next={HUB_URL}",
        {"action": "void_agreement", "void_reason": "Novecojis"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_void_agreement_without_next_still_lands_on_the_change_page(
    staff_client, approved_application
):
    resp = staff_client.post(
        _action_url(approved_application.pk),
        {"action": "void_agreement", "void_reason": "Novecojis"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == _change_url(approved_application.pk)


# ---------------------------------------------------------------------------
# regenerate_agreement - requires the current agreement to already be VOID
# (the service refuses to replace anything else), so each test voids it
# directly through the service first.
# ---------------------------------------------------------------------------


def test_regenerate_agreement_returns_to_a_safe_next(
    staff_client, approved_application, reviewer
):
    agreement = get_current_agreement(approved_application.approved_member)
    void_agreement_service(agreement, reviewer, "Aizstāts")
    resp = staff_client.post(
        f"{_action_url(approved_application.pk)}?next={HUB_URL}",
        {"action": "regenerate_agreement"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_regenerate_agreement_without_next_still_lands_on_the_change_page(
    staff_client, approved_application, reviewer
):
    agreement = get_current_agreement(approved_application.approved_member)
    void_agreement_service(agreement, reviewer, "Aizstāts")
    resp = staff_client.post(
        _action_url(approved_application.pk),
        {"action": "regenerate_agreement"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == _change_url(approved_application.pk)


# ---------------------------------------------------------------------------
# create_next_season_billing
# ---------------------------------------------------------------------------


def test_create_next_season_billing_returns_to_a_safe_next(
    staff_client, signed_active_application, next_season_plan
):
    resp = staff_client.post(
        f"{_action_url(signed_active_application.pk)}?next={HUB_URL}",
        {
            "action": "create_next_season_billing",
            "billing_plan": next_season_plan.pk,
            "first_billing_month": "2027-09",
        },
    )
    assert resp.status_code == 302
    assert resp["Location"] == HUB_URL


def test_create_next_season_billing_without_next_still_lands_on_the_change_page(
    staff_client, signed_active_application, next_season_plan
):
    resp = staff_client.post(
        _action_url(signed_active_application.pk),
        {
            "action": "create_next_season_billing",
            "billing_plan": next_season_plan.pk,
            "first_billing_month": "2027-09",
        },
    )
    assert resp.status_code == 302
    assert resp["Location"] == _change_url(signed_active_application.pk)

"""P9: Admin agreement billing setup — registration admin renders billing
plan picker, set_billing_setup POST action, and signing-block when plan
missing."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member
from apps.core.models import AuditEvent
from apps.registrations.services import approve_application

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer_bsetup", is_staff=True)


def _make_plan(**overrides):
    from apps.billing.models import MembershipPlan

    defaults = dict(
        name="Admin Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
    )
    defaults.update(overrides)
    plan = MembershipPlan(**defaults)
    plan.is_default = defaults.pop("is_default", False)
    plan.billing_start_cutoff_day = defaults.pop("billing_start_cutoff_day", 20)
    plan.save()
    return plan


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _review_action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


# ── D1: Admin renders billing plan picker ────────────────────────────────


class TestAdminRendersBillingPlanPicker:
    def test_agreement_module_shows_plan_picker(self, staff_client, submitted_application, reviewer):
        """The agreement module on the admin change page renders a billing
        plan picker (select with name='billing_plan') and the current
        first_billing_month field."""
        plan = _make_plan(is_default=True)
        app = approve_application(submitted_application, reviewer)
        agreement = create_agreement_for_member(
            app.approved_member, Agreement.SigningPath.PAPER
        )

        response = staff_client.get(_change_url(app.pk))
        assert response.status_code == 200
        content = response.content.decode()
        # Assert the billing plan picker is present.
        assert 'name="billing_plan"' in content
        assert plan.name in content


# ── D2: set_billing_setup POST changes agreement + audit ─────────────────


class TestSetBillingSetupAction:
    def test_post_updates_agreement_and_audits(self, staff_client, submitted_application, reviewer):
        """POST to the billing-setup endpoint updates agreement.billing_plan
        and agreement.first_billing_month, and emits BILLING_PLAN_ASSIGNED."""
        plan = _make_plan()
        app = approve_application(submitted_application, reviewer)
        agreement = create_agreement_for_member(
            app.approved_member, Agreement.SigningPath.PAPER
        )

        url = _review_action_url(app.pk)
        response = staff_client.post(
            url,
            {
                "action": "set_billing_setup",
                "billing_plan": plan.pk,
                "first_billing_month": "2026-09",
            },
        )
        # Review-action POSTs redirect (302) on success.
        assert response.status_code == 302

        agreement.refresh_from_db()
        assert agreement.billing_plan_id == plan.pk
        assert agreement.first_billing_month == "2026-09"

        audit = AuditEvent.objects.filter(
            action=str(AuditEvent.Action.BILLING_PLAN_ASSIGNED)
        ).first()
        assert audit is not None


# ── D3: Signing without billing plan → no mutation ──────────────────────


class TestSigningBlockedInAdmin:
    def test_signing_without_plan_keeps_generated(self, staff_client, submitted_application, reviewer):
        """Attempting to mark agreement signed via admin action when
        billing_plan is missing leaves state at generated."""
        app = approve_application(submitted_application, reviewer)
        agreement = create_agreement_for_member(
            app.approved_member, Agreement.SigningPath.PAPER
        )
        # Ensure no billing plan.
        agreement.billing_plan = None
        agreement.first_billing_month = ""
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        url = _review_action_url(app.pk)
        response = staff_client.post(
            url,
            {"action": "mark_agreement_signed"},
        )
        # Review-action POSTs redirect (302) even on validation error
        # (the admin shows a message and redirects back to the change page).
        assert response.status_code == 302

        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.GENERATED


# ── D4: set_billing_setup refuses empty plan (no service call) ─────────


class TestSetBillingSetupEmptyPlanGuard:
    def test_post_with_empty_plan_does_not_clear_existing(
        self, staff_client, submitted_application, reviewer
    ):
        """POSTing set_billing_setup with an empty ``billing_plan`` field
        must not reach the service: the existing plan stays intact and the
        admin surfaces a distinct Latvian 'select a plan' error (not the
        generic first-month error from the service)."""
        plan = _make_plan(is_default=True)
        app = approve_application(submitted_application, reviewer)
        agreement = create_agreement_for_member(
            app.approved_member, Agreement.SigningPath.PAPER
        )
        original_plan_id = agreement.billing_plan_id
        original_month = agreement.first_billing_month

        url = _review_action_url(app.pk)
        response = staff_client.post(
            url,
            {
                "action": "set_billing_setup",
                "billing_plan": "",
                "first_billing_month": "2026-09",
            },
            follow=True,
        )
        assert response.status_code == 200
        assert "Lūdzu izvēlieties norēķinu plānu" in response.content.decode()

        agreement.refresh_from_db()
        assert agreement.billing_plan_id == original_plan_id
        assert agreement.first_billing_month == original_month

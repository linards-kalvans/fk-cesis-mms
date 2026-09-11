"""Admin signed-application billing actions (P-next season renewal + current
recreate).

A signed application must offer an individual next-season billing action
(selects an active plan for a different season than the signed agreement's
billing-plan season + a first billing month, creating one DRAFT BillingRecord
under the same signed agreement), plus a staff-confirmed current-season
recreate. Bulk renewal is out of scope.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member, set_billing_setup
from apps.billing.models import BillingRecord, MembershipPlan
from apps.core.models import AuditEvent
from apps.registrations.services import approve_application

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer_billing_actions", is_staff=True)


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


@pytest.fixture
def signed_app(submitted_application, reviewer, db):
    """An approved application whose current agreement is SIGNED with an
    explicit billing plan (season 2026/2027) + first billing month."""
    from django.utils import timezone

    app = approve_application(submitted_application, reviewer)
    agreement = create_agreement_for_member(
        app.approved_member, Agreement.SigningPath.PAPER
    )
    plan = MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    set_billing_setup(
        agreement,
        plan,
        first_billing_month="2026-09",
        actor=reviewer,
    )
    agreement.state = Agreement.State.SIGNED
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "signed_at"])
    app.signed_agreement = agreement
    app.current_plan = plan
    return app


@pytest.fixture
def next_season_plan(db):
    """An active plan for a season different from the signed agreement's."""
    return MembershipPlan.objects.create(
        name="Sezona 2027/2028",
        season="2027/2028",
        annual_amount=Decimal("320.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )


def _current_season_record(app):
    return BillingRecord.objects.filter(
        member=app.approved_member, season=app.current_plan.season
    ).first()


# ── T1: signed admin context excludes current plan season ───────────────


class TestSignedAdminContext:
    def test_signed_context_shows_next_season_plans_excludes_current(
        self, staff_client, signed_app, next_season_plan
    ):
        """The signed application's change page offers next-season plans but
        not the current agreement's plan season."""
        import re

        resp = staff_client.get(_change_url(signed_app.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        # Next-season plan rendered as a renewal option.
        assert next_season_plan.name in content
        assert f'value="{next_season_plan.pk}"' in content
        # The current-season plan must NOT appear as an option in the
        # next-season picker. Scope the assertion to the picker itself: the
        # change page legitimately carries other `value="<pk>"` attributes
        # (e.g. the parent-account FK select on the edit form), so a whole-
        # page scan would false-positive when the current plan's pk equals
        # another row's pk.
        picker = re.search(
            r'<select[^>]*id="next_season_billing_plan"[^>]*>.*?</select>',
            content,
            re.S,
        )
        assert picker is not None
        assert f'value="{next_season_plan.pk}"' in picker.group(0)
        assert f'value="{signed_app.current_plan.pk}"' not in picker.group(0)


# ── T2: POST creates next-season draft linked to current agreement ──────


class TestCreateNextSeasonBilling:
    def test_post_creates_draft_linked_to_current_agreement(
        self, staff_client, signed_app, next_season_plan
    ):
        url = _action_url(signed_app.pk)
        resp = staff_client.post(
            url,
            {
                "action": "create_next_season_billing",
                "billing_plan": next_season_plan.pk,
                "first_billing_month": "2027-09",
            },
        )
        assert resp.status_code == 302

        record = BillingRecord.objects.filter(
            member=signed_app.approved_member, season=next_season_plan.season
        ).first()
        assert record is not None
        assert record.status == BillingRecord.Status.DRAFT
        assert record.agreement_id == signed_app.signed_agreement.pk
        assert record.plan_id == next_season_plan.pk
        assert record.first_billing_month == "2027-09"

        # Agreement plan/state untouched.
        signed_app.signed_agreement.refresh_from_db()
        assert signed_app.signed_agreement.state == Agreement.State.SIGNED
        assert (
            signed_app.signed_agreement.billing_plan_id
            == signed_app.current_plan.pk
        )

    def test_duplicate_request_keeps_one_row(
        self, staff_client, signed_app, next_season_plan
    ):
        url = _action_url(signed_app.pk)
        payload = {
            "action": "create_next_season_billing",
            "billing_plan": next_season_plan.pk,
            "first_billing_month": "2027-09",
        }
        staff_client.post(url, payload)
        staff_client.post(url, payload)
        assert (
            BillingRecord.objects.filter(
                member=signed_app.approved_member, season=next_season_plan.season
            ).count()
            == 1
        )


# ── T3: invalid next-season plan requests do not write ──────────────────


class TestNextSeasonRejectedPlans:
    def test_current_season_plan_request_does_not_write(
        self, staff_client, signed_app
    ):
        """Posting the CURRENT agreement's plan season (same season) to the
        next-season action must be safely rejected without creating a record."""
        url = _action_url(signed_app.pk)
        resp = staff_client.post(
            url,
            {
                "action": "create_next_season_billing",
                "billing_plan": signed_app.current_plan.pk,
                "first_billing_month": "2026-09",
            },
            follow=True,
        )
        assert resp.status_code == 200
        assert _current_season_record(signed_app) is None
        assert BillingRecord.objects.filter(
            member=signed_app.approved_member, season=signed_app.current_plan.season
        ).count() == 0

    def test_inactive_plan_request_does_not_write(
        self, staff_client, signed_app
    ):
        from apps.billing.models import MembershipPlan

        inactive = MembershipPlan.objects.create(
            name="Neaktīva nākamā sezona",
            season="2028/2029",
            annual_amount=Decimal("340.00"),
            is_active=False,
        )
        url = _action_url(signed_app.pk)
        staff_client.post(
            url,
            {
                "action": "create_next_season_billing",
                "billing_plan": inactive.pk,
                "first_billing_month": "2028-09",
            },
        )
        assert BillingRecord.objects.filter(
            member=signed_app.approved_member, season=inactive.season
        ).count() == 0

    def test_malformed_plan_request_does_not_write(
        self, staff_client, signed_app
    ):
        url = _action_url(signed_app.pk)
        staff_client.post(
            url,
            {
                "action": "create_next_season_billing",
                "billing_plan": "not-a-number",
                "first_billing_month": "2027-09",
            },
        )
        assert BillingRecord.objects.filter(
            member=signed_app.approved_member
        ).count() == 0

    def test_missing_month_request_does_not_write(
        self, staff_client, signed_app, next_season_plan
    ):
        url = _action_url(signed_app.pk)
        staff_client.post(
            url,
            {
                "action": "create_next_season_billing",
                "billing_plan": next_season_plan.pk,
                "first_billing_month": "",
            },
        )
        assert BillingRecord.objects.filter(
            member=signed_app.approved_member, season=next_season_plan.season
        ).count() == 0


# ── T4: recreate checkbox required + success path ───────────────────────


class TestRecreateControls:
    def test_recreate_disclosure_renders_when_record_missing(
        self, staff_client, signed_app
    ):
        """Signed active application with a missing current-season record
        renders the recreate disclosure + the required Invoice-Ninja
        confirmation checkbox."""
        resp = staff_client.get(_change_url(signed_app.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Atjaunot trūkstošu norēķinu ierakstu" in content
        assert 'name="external_invoice_confirmed_absent"' in content
        assert "Invoice Ninja" in content

    def test_recreate_disclosure_hidden_when_record_exists(
        self, staff_client, signed_app
    ):
        """Once a current-season record exists, the recreate controls vanish."""
        from apps.billing.services import create_draft_billing_for_member

        create_draft_billing_for_member(
            signed_app.approved_member, signed_app.signed_agreement
        )
        assert _current_season_record(signed_app) is not None

        resp = staff_client.get(_change_url(signed_app.pk))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Atjaunot trūkstošu norēķinu ierakstu" not in content
        assert 'name="external_invoice_confirmed_absent"' not in content


class TestRecreateCurrentBilling:
    def test_recreate_refused_without_confirmation(
        self, staff_client, signed_app
    ):
        url = _action_url(signed_app.pk)
        staff_client.post(
            url,
            {"action": "recreate_current_billing"},
        )
        assert _current_season_record(signed_app) is None

    def test_recreate_success_creates_current_season_draft(
        self, staff_client, signed_app
    ):
        url = _action_url(signed_app.pk)
        resp = staff_client.post(
            url,
            {
                "action": "recreate_current_billing",
                "external_invoice_confirmed_absent": "1",
            },
        )
        assert resp.status_code == 302

        record = _current_season_record(signed_app)
        assert record is not None
        assert record.status == BillingRecord.Status.DRAFT
        assert record.agreement_id == signed_app.signed_agreement.pk
        assert record.plan_id == signed_app.current_plan.pk
        assert record.first_billing_month == signed_app.signed_agreement.first_billing_month

        event = AuditEvent.objects.filter(action="billing_record_recreated").first()
        assert event is not None
        assert event.metadata == {
            "plan_id": signed_app.current_plan.pk,
            "season": signed_app.current_plan.season,
        }


# ── T5: unsigned / discontinued applications cannot invoke ──────────────


class TestUnsignedOrDiscontinued:
    def test_unsigned_application_does_not_render_next_season_controls(
        self, staff_client, submitted_application, reviewer
    ):
        """An approved-but-not-signed application shows no next-season renewal
        controls and the action is refused."""
        app = approve_application(submitted_application, reviewer)
        create_agreement_for_member(app.approved_member, Agreement.SigningPath.PAPER)

        resp = staff_client.get(_change_url(app.pk))
        assert resp.status_code == 200
        assert "create_next_season_billing" not in resp.content.decode()

        # Direct POST is refused.
        url = _action_url(app.pk)
        staff_client.post(
            url,
            {"action": "create_next_season_billing", "billing_plan": "999"},
        )
        assert BillingRecord.objects.filter(member=app.approved_member).count() == 0

    def test_discontinued_application_cannot_invoke_next_season(
        self, staff_client, signed_app
    ):
        from apps.agreements.services import discontinue_agreement

        discontinue_agreement(
            signed_app.signed_agreement, reviewer, "2026-09-01", "nav turpinājuma", []
        )
        url = _action_url(signed_app.pk)
        staff_client.post(
            url,
            {
                "action": "create_next_season_billing",
                "billing_plan": "999",
            },
        )
        # No record for any season beyond what existed.
        assert BillingRecord.objects.filter(member=signed_app.approved_member).count() == 0

"""P9: Member admin renewal action — creates missing draft billing records
for selected members, skips existing same-season records and discontinued
members, emits BILLING_RECORD_RENEWED audit."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.billing.models import BillingRecord, MembershipPlan
from apps.core.models import AuditEvent
from apps.members.models import Member

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _make_plan(*, season="2027/2028", **overrides):
    defaults = dict(
        name=f"Renewal-{season}",
        season=season,
        annual_amount=Decimal("300.00"),
        is_active=True,
    )
    defaults.update(overrides)
    plan = MembershipPlan(**defaults)
    plan.save()
    return plan


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    return make_guardian(full_name="Renewal Guardian", email="renewal@example.test")


@pytest.fixture
def active_member(db, guardian):
    return Member.objects.create(full_name="Active Child", guardian=guardian)


@pytest.fixture
def discontinued_member(db, guardian):
    return Member.objects.create(
        full_name="Discontinued Child",
        guardian=guardian,
        status=Member.Status.DISCONTINUED,
    )


# ── E1: Renewal action shows confirmation page ─────────────────────────


class TestRenewalConfirmationPage:
    def test_first_post_shows_confirmation_with_plans(
        self, staff_client, active_member
    ):
        """The renewal action's first POST shows a confirmation page with
        active plans listed."""
        plan = _make_plan()
        changelist_url = reverse("admin:members_member_changelist")
        response = staff_client.post(
            changelist_url,
            {
                "action": "renew_billing",
                "_selected_action": [str(active_member.pk)],
            },
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert plan.name in content


# ── E2: Confirm creates draft record + audit ────────────────────────────


class TestRenewalConfirmCreatesRecord:
    def test_confirm_creates_draft_and_audits(
        self, staff_client, active_member
    ):
        """Confirm POST creates a missing draft BillingRecord with the
        selected plan/month and emits BILLING_RECORD_RENEWED."""
        plan = _make_plan()
        changelist_url = reverse("admin:members_member_changelist")

        response = staff_client.post(
            changelist_url,
            {
                "action": "renew_billing",
                "_selected_action": [str(active_member.pk)],
                "apply": "1",
                "billing_plan": plan.pk,
                "first_billing_month": "2027-09",
            },
        )
        # Should redirect or stay on page (not 500).
        assert response.status_code in (200, 302)

        record = BillingRecord.objects.filter(member=active_member).first()
        assert record is not None
        assert record.plan_id == plan.pk
        assert record.season == plan.season
        assert record.first_billing_month == "2027-09"
        assert record.status == BillingRecord.Status.DRAFT

        audit = AuditEvent.objects.filter(
            action=str(AuditEvent.Action.BILLING_RECORD_RENEWED)
        ).first()
        assert audit is not None


# ── E3: Existing same-season record skipped ─────────────────────────────


class TestRenewalSkipsExistingRecord:
    def test_existing_same_season_not_duplicated(
        self, staff_client, active_member
    ):
        """When a BillingRecord for the target season already exists,
        renewal skips it (no duplicate, no audit event for skip)."""
        plan = _make_plan()
        # Pre-existing record for the same season.
        BillingRecord.objects.create(
            member=active_member,
            plan=plan,
            season=plan.season,
            base_amount=plan.annual_amount,
            final_amount=plan.annual_amount,
        )
        changelist_url = reverse("admin:members_member_changelist")

        staff_client.post(
            changelist_url,
            {
                "action": "renew_billing",
                "_selected_action": [str(active_member.pk)],
                "apply": "1",
                "billing_plan": plan.pk,
                "first_billing_month": "2027-09",
            },
        )

        # Exactly one record for this member+season.
        assert (
            BillingRecord.objects.filter(
                member=active_member, season=plan.season
            ).count()
            == 1
        )
        # No RENEWED audit event (skipped).
        assert not AuditEvent.objects.filter(
            action=str(AuditEvent.Action.BILLING_RECORD_RENEWED)
        ).exists()


# ── E4: Discontinued member skipped ─────────────────────────────────────


class TestRenewalSkipsDiscontinuedMember:
    def test_discontinued_member_no_record_created(
        self, staff_client, discontinued_member, guardian
    ):
        """Renewal skips discontinued members — no record created.
        Verify by creating a record for an active member in the same request."""
        from apps.members.models import Member

        # Create an active member to verify the action was recognized.
        active_member = Member.objects.create(
            full_name="Active Sibling", guardian=guardian
        )
        plan = _make_plan()
        changelist_url = reverse("admin:members_member_changelist")

        response = staff_client.post(
            changelist_url,
            {
                "action": "renew_billing",
                "_selected_action": [
                    str(discontinued_member.pk),
                    str(active_member.pk),
                ],
                "apply": "1",
                "billing_plan": plan.pk,
                "first_billing_month": "2027-09",
            },
        )

        # The action must be recognized (not just a redirect to changelist).
        # If the action doesn't exist, response is 302 with no processing.
        # If the action exists, it processes the active member.
        assert response.status_code in (200, 302)

        # Active member should have a record (action was recognized).
        assert BillingRecord.objects.filter(member=active_member).exists()
        # Discontinued member should NOT have a record (skipped).
        assert not BillingRecord.objects.filter(
            member=discontinued_member
        ).exists()

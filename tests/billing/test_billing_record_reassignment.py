"""P9: BillingRecord draft reassignment — service blocks confirmed/synced
records, admin renders confirmation, POST updates through service."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.billing.models import BillingInvoice, BillingRecord, MembershipPlan
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def _make_plan(*, season="2026/2027", name="Reassign-Plan", **overrides):
    defaults = dict(
        name=name,
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

    return make_guardian(full_name="Reassign Guardian", email="reassign@example.test")


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(full_name="Reassign Child", guardian=guardian)


@pytest.fixture
def draft_record(db, member):
    plan = _make_plan()
    return BillingRecord.objects.create(
        member=member,
        plan=plan,
        season=plan.season,
        base_amount=plan.annual_amount,
        final_amount=plan.annual_amount,
        status=BillingRecord.Status.DRAFT,
    )


@pytest.fixture
def confirmed_record(db, member):
    plan = _make_plan(name="Confirmed-Plan")
    return BillingRecord.objects.create(
        member=member,
        plan=plan,
        season=plan.season,
        base_amount=plan.annual_amount,
        final_amount=plan.annual_amount,
        status=BillingRecord.Status.CONFIRMED,
    )


# ── F1: Service updates draft record ────────────────────────────────────


class TestReassignDraftBillingRecord:
    def test_updates_plan_season_and_amounts(self, draft_record):
        """reassign_draft_billing_record updates plan, season,
        first_billing_month, and recomputes amounts. Emits
        BILLING_RECORD_REASSIGNED."""
        from apps.billing.services import reassign_draft_billing_record

        new_plan = _make_plan(
            season="2027/2028",
            name="New-Plan",
            annual_amount=Decimal("400.00"),
        )

        reassign_draft_billing_record(
            draft_record,
            new_plan,
            first_billing_month="2027-09",
            actor=None,
        )

        draft_record.refresh_from_db()
        assert draft_record.plan_id == new_plan.pk
        assert draft_record.season == "2027/2028"
        assert draft_record.first_billing_month == "2027-09"
        assert draft_record.base_amount == Decimal("400.00")

        audit = AuditEvent.objects.filter(
            action=str(AuditEvent.Action.BILLING_RECORD_REASSIGNED)
        ).first()
        assert audit is not None


# ── F2: Service blocks confirmed record ─────────────────────────────────


class TestReassignBlocksConfirmed:
    def test_raises_on_confirmed(self, confirmed_record):
        """reassign_draft_billing_record raises ValueError on a confirmed
        record."""
        from apps.billing.services import reassign_draft_billing_record

        new_plan = _make_plan(season="2027/2028", name="New-Plan-2")

        with pytest.raises(ValueError, match="confirmed|apstiprin"):
            reassign_draft_billing_record(
                confirmed_record,
                new_plan,
                first_billing_month="2027-09",
                actor=None,
            )


# ── F3: Service blocks record with external_invoice_id ──────────────────


class TestReassignBlocksSyncedInvoices:
    def test_raises_when_invoice_has_external_id(self, draft_record):
        """reassign_draft_billing_record raises ValueError when any
        BillingInvoice has an external_invoice_id (pushed to IN)."""
        from apps.billing.services import reassign_draft_billing_record

        BillingInvoice.objects.create(
            billing_record=draft_record,
            sequence=1,
            due_date=datetime.date(2026, 9, 20),
            amount=Decimal("30.00"),
            external_invoice_id="ext-123",
        )

        new_plan = _make_plan(season="2027/2028", name="New-Plan-3")

        with pytest.raises(ValueError, match="invoice|rēķin"):
            reassign_draft_billing_record(
                draft_record,
                new_plan,
                first_billing_month="2027-09",
                actor=None,
            )


# ── F4: Service blocks record with sent_at invoice ─────────────────────


class TestReassignBlocksSentInvoices:
    def test_raises_when_invoice_has_sent_at(self, draft_record):
        """reassign_draft_billing_record raises ValueError when any
        BillingInvoice has sent_at set (emailed to parent)."""
        from apps.billing.services import reassign_draft_billing_record
        from django.utils import timezone

        BillingInvoice.objects.create(
            billing_record=draft_record,
            sequence=1,
            due_date=datetime.date(2026, 9, 20),
            amount=Decimal("30.00"),
            sent_at=timezone.now(),
        )

        new_plan = _make_plan(season="2027/2028", name="New-Plan-4")

        with pytest.raises(ValueError, match="sent|nosūt"):
            reassign_draft_billing_record(
                draft_record,
                new_plan,
                first_billing_month="2027-09",
                actor=None,
            )


# ── F5: Admin reassign confirmation page renders ────────────────────────


class TestAdminReassignConfirmationPage:
    def test_reassign_page_renders_for_draft(self, staff_client, draft_record):
        """The admin reassign confirmation page renders for a draft record."""
        new_plan = _make_plan(season="2027/2028", name="Admin-Plan")
        url = reverse("admin:billing_billingrecord_reassign", args=[draft_record.pk])
        response = staff_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        assert new_plan.name in content


# ── F6: Admin reassign POST updates record ──────────────────────────────


class TestAdminReassignPost:
    def test_post_updates_record(self, staff_client, draft_record):
        """POST to the admin reassign endpoint updates the record through
        the service."""
        new_plan = _make_plan(season="2027/2028", name="Admin-Plan-2")
        url = reverse("admin:billing_billingrecord_reassign", args=[draft_record.pk])
        response = staff_client.post(
            url,
            {
                "billing_plan": new_plan.pk,
                "first_billing_month": "2027-09",
            },
        )
        assert response.status_code in (200, 302)

        draft_record.refresh_from_db()
        assert draft_record.plan_id == new_plan.pk
        assert draft_record.season == "2027/2028"


# ── F7: Reassign refuses empty plan with distinct Latvian error ─────────


class TestAdminReassignEmptyPlanGuard:
    def test_post_with_empty_plan_does_not_reassign(
        self, staff_client, draft_record
    ):
        """POSTing reassign with an empty ``billing_plan`` field shows the
        distinct 'select a plan' error and leaves the record unchanged
        (the service is not called, so a missing first-month never gets
        surfaced as a misleading 'first billing month' error)."""
        url = reverse("admin:billing_billingrecord_reassign", args=[draft_record.pk])
        original_plan_id = draft_record.plan_id
        response = staff_client.post(
            url,
            {"billing_plan": "", "first_billing_month": ""},
            follow=True,
        )
        assert response.status_code == 200
        assert "Lūdzu izvēlieties norēķinu plānu" in response.content.decode()
        # The misleading first-month message must not appear.
        assert "Pirmajam mēnesim" not in response.content.decode()

        draft_record.refresh_from_db()
        assert draft_record.plan_id == original_plan_id

"""BillingRecord current-season recreation from a signed agreement.

Covers ``recreate_missing_billing_record`` — a current-season billing record
that is already missing may be recreated from its signed agreement only after
staff explicitly confirms no matching Invoice Ninja invoice exists. There is
NO Invoice Ninja lookup (nothing to mock here).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.billing.models import BillingRecord
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    return make_guardian(full_name="Recreate Guardian", email="recreate@example.test")


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(full_name="Recreate Child", guardian=guardian)


@pytest.fixture
def signed_agreement(db, member):
    """A signed agreement with an explicit billing plan + first month."""
    from apps.agreements.models import Agreement
    from apps.billing.models import MembershipPlan

    plan = MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    return Agreement.objects.create(
        member=member,
        state=Agreement.State.SIGNED,
        generated_at="2026-05-01T00:00:00Z",
        signed_at="2026-05-02T00:00:00Z",
        billing_plan=plan,
        first_billing_month="2026-09",
    )


def _recreate(member, agreement, *, confirmed=False, actor=None):
    from apps.billing.services import recreate_missing_billing_record

    return recreate_missing_billing_record(
        member,
        agreement,
        external_invoice_confirmed_absent=confirmed,
        actor=actor,
    )


# ── R1: confirmation required ────────────────────────────────────────────


class TestConfirmationRequired:
    def test_refused_without_confirmation(self, member, signed_agreement):
        """Without ``external_invoice_confirmed_absent=True`` the recreate is
        refused and no BillingRecord is created."""
        with pytest.raises(ValueError):
            _recreate(member, signed_agreement, confirmed=False)
        assert BillingRecord.objects.filter(member=member).count() == 0

    def test_no_audit_without_confirmation(self, member, signed_agreement):
        with pytest.raises(ValueError):
            _recreate(member, signed_agreement, confirmed=False)
        assert not AuditEvent.objects.filter(
            action="billing_record_recreated"
        ).exists()


# ── R2: successful current-season creation tied to signed agreement ─────


class TestSuccessfulCreate:
    def test_creates_draft_under_signed_agreement(self, member, signed_agreement):
        """Confirmed recreate creates a DRAFT BillingRecord for the agreement's
        original plan season, linked to the same agreement, and does not change
        the agreement's plan/state."""
        agreement = signed_agreement
        record = _recreate(member, agreement, confirmed=True)

        assert isinstance(record, BillingRecord)
        assert record.member_id == member.pk
        assert record.agreement_id == agreement.pk
        assert record.status == BillingRecord.Status.DRAFT
        assert record.plan_id == agreement.billing_plan_id
        assert record.season == agreement.billing_plan.season
        assert record.first_billing_month == agreement.first_billing_month

        agreement.refresh_from_db()
        assert agreement.state == "signed"
        assert agreement.billing_plan_id == record.plan_id

    def test_emits_redacted_recreate_audit(self, member, signed_agreement):
        """A real recreate emits exactly one AuditEvent action
        ``billing_record_recreated`` with only plan_id + season metadata."""
        _recreate(member, signed_agreement, confirmed=True, actor=None)

        events = AuditEvent.objects.filter(action="billing_record_recreated")
        assert events.count() == 1
        event = events.first()
        assert event.action == "billing_record_recreated"
        assert event.metadata == {
            "plan_id": signed_agreement.billing_plan_id,
            "season": signed_agreement.billing_plan.season,
        }
        # Redaction: no member id / personal data / free-text in metadata.
        assert set(event.metadata) == {"plan_id", "season"}
        assert "first_billing_month" not in event.metadata
        assert "member" not in str(event.metadata).lower()

    def test_does_not_change_historical_records_or_invoices(
        self, member, signed_agreement
    ):
        """Recreate adds a fresh draft without touching historical billing
        records or their invoices."""
        from apps.billing.models import BillingInvoice

        historical = BillingRecord.objects.create(
            member=member,
            plan=signed_agreement.billing_plan,
            agreement=signed_agreement,
            season="2025/2026",
            base_amount=Decimal("250.00"),
            final_amount=Decimal("250.00"),
            status=BillingRecord.Status.CONFIRMED,
        )
        invoice = BillingInvoice.objects.create(
            billing_record=historical,
            sequence=1,
            due_date="2025-09-20",
            amount=Decimal("250.00"),
        )

        record = _recreate(member, signed_agreement, confirmed=True)
        assert record.pk != historical.pk

        historical.refresh_from_db()
        invoice.refresh_from_db()
        assert historical.status == BillingRecord.Status.CONFIRMED
        assert invoice.pk is not None
        assert BillingRecord.objects.filter(
            member=member, season=signed_agreement.billing_plan.season
        ).count() == 1


# ── R3: duplicate current-season rejection ───────────────────────────────


class TestDuplicateRejected:
    def test_refused_when_current_season_record_exists(
        self, member, signed_agreement
    ):
        """Recreate is refused when a record for the current plan season
        already exists."""
        BillingRecord.objects.create(
            member=member,
            plan=signed_agreement.billing_plan,
            agreement=signed_agreement,
            season=signed_agreement.billing_plan.season,
            base_amount=Decimal("300.00"),
            final_amount=Decimal("300.00"),
            status=BillingRecord.Status.DRAFT,
        )
        with pytest.raises(ValueError):
            _recreate(member, signed_agreement, confirmed=True)
        assert BillingRecord.objects.filter(
            member=member, season=signed_agreement.billing_plan.season
        ).count() == 1
        assert not AuditEvent.objects.filter(
            action="billing_record_recreated"
        ).exists()


# ── R4: missing plan and non-signed rejection ────────────────────────────


class TestMissingPlanAndNonSigned:
    def test_refused_on_non_signed_agreement(self, member, signed_agreement):
        from apps.agreements.models import Agreement

        signed_agreement.state = Agreement.State.GENERATED
        signed_agreement.save(update_fields=["state"])
        with pytest.raises(ValueError):
            _recreate(member, signed_agreement, confirmed=True)
        assert BillingRecord.objects.filter(member=member).count() == 0

    def test_refused_when_agreement_has_no_billing_plan(
        self, member, signed_agreement
    ):
        signed_agreement.billing_plan = None
        signed_agreement.first_billing_month = ""
        signed_agreement.save(update_fields=["billing_plan", "first_billing_month"])
        with pytest.raises(ValueError):
            _recreate(member, signed_agreement, confirmed=True)
        assert BillingRecord.objects.filter(member=member).count() == 0

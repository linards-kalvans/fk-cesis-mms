"""P9: Agreement billing_plan / first_billing_month integration with
create_agreement_for_member, mark_agreement_signed, and
create_draft_billing_for_member."""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _make_plan(*, is_active=True, is_default=False, **overrides):
    from apps.billing.models import MembershipPlan

    defaults = dict(
        name=f"Plan-{is_default}-{is_active}",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=is_active,
    )
    defaults.update(overrides)
    plan = MembershipPlan(**defaults)
    plan.is_default = is_default
    plan.billing_start_cutoff_day = overrides.get("billing_start_cutoff_day", 20)
    plan.save()
    return plan


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    return make_guardian(full_name="Anna Bērziņa", email="anna@example.test")


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(full_name="Jānis Bērziņš", guardian=guardian)


# ── B1: create_agreement_for_member preselects default billing plan ──────


class TestCreateAgreementPreselectsBillingPlan:
    def test_preselects_default_plan_and_derived_month(self, member):
        """When a default active plan exists, the new agreement gets
        billing_plan set and first_billing_month derived from cutoff."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import create_agreement_for_member

        plan = _make_plan(is_default=True, is_active=True)
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        assert agreement.billing_plan_id == plan.pk
        assert agreement.first_billing_month  # non-blank YYYY-MM string

    def test_no_default_leaves_billing_plan_empty(self, member):
        """Without a default plan, billing_plan is None and
        first_billing_month is blank."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import create_agreement_for_member

        _make_plan(is_default=False, is_active=True)
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        assert agreement.billing_plan_id is None
        assert not agreement.first_billing_month


# ── B2: mark_agreement_signed blocks without billing_plan ────────────────


class TestSigningBlockedWithoutBillingPlan:
    def test_raises_and_does_not_change_state(self, member):
        """mark_agreement_signed raises ValueError when billing_plan is
        missing. State stays generated. No BillingRecord created."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import (
            create_agreement_for_member,
            mark_agreement_signed,
        )
        from apps.billing.models import BillingRecord

        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        # Force billing_plan to None (no default plan existed).
        agreement.billing_plan = None
        agreement.first_billing_month = ""
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        with pytest.raises(ValueError, match="billing"):
            mark_agreement_signed(agreement, actor=None)

        agreement.refresh_from_db()
        assert agreement.state == Agreement.State.GENERATED
        assert BillingRecord.objects.filter(member=member).count() == 0


# ── B3: create_draft_billing_for_member uses agreement billing_plan ──────


class TestCreateDraftUsesAgreementBillingPlan:
    def test_uses_agreement_plan_and_first_month(self, member):
        """create_draft_billing_for_member must use agreement.billing_plan
        and agreement.first_billing_month, not just any active plan."""
        from apps.agreements.models import Agreement
        from apps.agreements.services import create_agreement_for_member
        from apps.billing.services import create_draft_billing_for_member

        chosen_plan = _make_plan(
            is_default=False, is_active=True, season="2026/2027"
        )
        other_plan = _make_plan(
            is_default=False, is_active=True, season="2027/2028", name="Other"
        )
        agreement = create_agreement_for_member(
            member, signing_path=Agreement.SigningPath.PAPER
        )
        agreement.billing_plan = chosen_plan
        agreement.first_billing_month = "2026-09"
        agreement.save(update_fields=["billing_plan", "first_billing_month"])

        record = create_draft_billing_for_member(member, agreement)
        assert record is not None
        assert record.plan_id == chosen_plan.pk
        assert record.plan_id != other_plan.pk
        assert record.season == chosen_plan.season
        assert record.first_billing_month == "2026-09"


# ── B4: set_billing_setup blocks on post-signing states ────────────────


class TestSetBillingSetupBlocksPostSigning:
    def test_raises_on_superseded(self, member):
        """set_billing_setup raises ValueError on a SUPERSEDED agreement
        (billing is already realised against the locked record)."""
        from django.utils import timezone

        from apps.agreements.models import Agreement
        from apps.agreements.services import set_billing_setup

        agreement = Agreement.objects.create(
            member=member,
            state=Agreement.State.SUPERSEDED,
            generated_at=timezone.now(),
            billing_plan=None,
            first_billing_month="",
        )
        plan = _make_plan(is_default=True, is_active=True)
        with pytest.raises(ValueError, match="billing|parakst"):
            set_billing_setup(
                agreement, plan, first_billing_month="2026-09", actor=None
            )

    def test_raises_on_discontinued(self, member):
        """set_billing_setup raises ValueError on a DISCONTINUED agreement."""
        from django.utils import timezone

        from apps.agreements.models import Agreement
        from apps.agreements.services import set_billing_setup

        agreement = Agreement.objects.create(
            member=member,
            state=Agreement.State.DISCONTINUED,
            generated_at=timezone.now(),
            billing_plan=None,
            first_billing_month="",
        )
        plan = _make_plan(is_default=True, is_active=True)
        with pytest.raises(ValueError, match="billing|parakst"):
            set_billing_setup(
                agreement, plan, first_billing_month="2026-09", actor=None
            )

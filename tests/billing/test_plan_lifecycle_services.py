"""P9: MembershipPlan default marker, billing_start_cutoff_day, and
derive_first_billing_month / get_default_billing_plan services."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def _make_plan(*, is_active=True, is_default=False, cutoff_day=20, name=None, **overrides):
    """Helper for creating valid MembershipPlan rows. Does NOT call
    full_clean() — callers that need validation testing build the model
    directly and call full_clean() inside their own pytest.raises block."""
    from apps.billing.models import MembershipPlan

    plan_name = name or f"Plan-{is_default}-{is_active}"
    defaults = dict(
        name=plan_name,
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=is_active,
    )
    defaults.update(overrides)
    plan = MembershipPlan(**defaults)
    # Set P9 fields — these don't exist yet (RED phase).
    plan.is_default = is_default
    plan.billing_start_cutoff_day = cutoff_day
    plan.save()
    return plan


# ── A1: default plan must be active ──────────────────────────────────────


class TestDefaultPlanMustBeActive:
    def test_inactive_default_rejected(self):
        """A MembershipPlan with is_default=True and is_active=False must
        fail validation (Latvian message fragment acceptable)."""
        from django.core.exceptions import ValidationError
        from apps.billing.models import MembershipPlan

        # Build the invalid plan directly — do NOT save it first.
        plan = MembershipPlan(
            name="Invalid-Default",
            season="2026/2027",
            annual_amount=Decimal("300.00"),
            is_active=False,
        )
        plan.is_default = True
        plan.billing_start_cutoff_day = 20

        with pytest.raises(ValidationError) as exc_info:
            plan.full_clean()
        errors = exc_info.value.message_dict
        # At least one field must mention the default-active constraint.
        all_messages = " ".join(
            msg for msgs in errors.values() for msg in msgs
        )
        assert "noklusējuma" in all_messages.lower() or "aktīv" in all_messages.lower() or "default" in all_messages.lower()


# ── A2: only one default plan ────────────────────────────────────────────


class TestOnlyOneDefaultPlan:
    def test_second_default_rejected_at_db_level(self):
        """Creating a second default plan must violate a DB constraint."""
        from django.db import IntegrityError
        from apps.billing.models import MembershipPlan

        # First default plan — should succeed.
        _make_plan(is_default=True, name="Default-1")

        # Second default plan — must raise IntegrityError.
        with pytest.raises(IntegrityError):
            plan2 = MembershipPlan(
                name="Default-2",
                season="2026/2027",
                annual_amount=Decimal("300.00"),
                is_active=True,
            )
            plan2.is_default = True
            plan2.billing_start_cutoff_day = 20
            plan2.save()


# ── A3: get_default_billing_plan ─────────────────────────────────────────


class TestGetDefaultBillingPlan:
    def test_returns_active_default(self):
        from apps.billing.services import get_default_billing_plan

        default = _make_plan(is_default=True, is_active=True, name="Default-Active")
        _make_plan(is_default=False, is_active=True, name="Other-Active")
        result = get_default_billing_plan()
        assert result is not None
        assert result.pk == default.pk

    def test_returns_none_when_no_default(self):
        from apps.billing.services import get_default_billing_plan

        _make_plan(is_default=False, is_active=True)
        assert get_default_billing_plan() is None


# ── A4: derive_first_billing_month — on cutoff day → current month ──────


class TestDeriveFirstBillingMonth:
    def test_on_cutoff_day_returns_current_month(self):
        """today.day <= cutoff → current YYYY-MM."""
        from apps.billing.services import derive_first_billing_month

        plan = _make_plan(cutoff_day=15)
        today = datetime.date(2026, 6, 15)
        result = derive_first_billing_month(plan, today=today)
        assert result == "2026-06"

    def test_after_cutoff_day_returns_next_month(self):
        """today.day > cutoff → next YYYY-MM."""
        from apps.billing.services import derive_first_billing_month

        plan = _make_plan(cutoff_day=15)
        today = datetime.date(2026, 6, 16)
        result = derive_first_billing_month(plan, today=today)
        assert result == "2026-07"

    def test_after_cutoff_day_wraps_year(self):
        """December after cutoff → January next year."""
        from apps.billing.services import derive_first_billing_month

        plan = _make_plan(cutoff_day=15)
        today = datetime.date(2026, 12, 20)
        result = derive_first_billing_month(plan, today=today)
        assert result == "2027-01"

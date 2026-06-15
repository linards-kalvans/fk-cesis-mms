"""Shared fixtures for tests/integrations/."""

from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture
def active_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        sibling_discount_percent=Decimal("50.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    g = make_guardian(full_name="Anna Bērziņa", email="anna@example.com")
    g.email = "anna@example.com"
    g.save(update_fields=["email"])
    return g


@pytest.fixture
def agreement_guardian(db):
    from tests.support import make_guardian

    g = make_guardian(
        full_name="Anna Bērziņa",
        personal_id="111111-11111",
        email="anna@example.test",
        phone="+37120000000",
        address="Rīgas iela 1, Cēsis",
    )
    g.email = "anna@example.test"
    g.phone = "+37120000000"
    g.save(update_fields=["email", "phone"])
    return g


@pytest.fixture
def agreement_member(db, agreement_guardian):
    from apps.members.models import Member

    return Member.objects.create(
        full_name="Jānis Bērziņš",
        personal_id="151210-22222",
        birth_date="2015-12-10",
        guardian=agreement_guardian,
        training_group=None,
    )

"""Shared fixtures for tests/agreements/."""

from __future__ import annotations

import pytest


@pytest.fixture
def actor(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


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


@pytest.fixture
def default_plan(db):
    """An active default MembershipPlan — P9 preselects it on agreement
    creation so ``mark_agreement_signed`` has a ``billing_plan`` to validate."""
    from decimal import Decimal

    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="Test Default Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
        is_default=True,
    )

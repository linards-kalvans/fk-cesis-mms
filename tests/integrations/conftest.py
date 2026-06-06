"""Shared fixtures for tests/integrations/."""

from __future__ import annotations

import pytest


@pytest.fixture
def agreement_guardian(db):
    from apps.members.models import Guardian

    return Guardian.objects.create(
        full_name="Anna Bērziņa",
        personal_id="111111-11111",
        email="anna@example.test",
        phone="+37120000000",
        address="Rīgas iela 1, Cēsis",
    )


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

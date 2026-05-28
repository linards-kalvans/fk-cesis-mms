"""Shared fixtures for tests/members/.

Model imports are deferred into fixture bodies because pytest collects
conftests before pytest_configure runs django.setup() (see
tests/registrations/conftest.py for the same pattern).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def guardian(db):
    from apps.members.models import Guardian

    return Guardian.objects.create(
        full_name="Anna Bērziņa",
        personal_id="111111-11111",
        email="anna@example.test",
        phone="+37120000000",
        address="Rīgas iela 1, Cēsis",
    )


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(
        full_name="Jānis Bērziņš",
        personal_id="151210-22222",
        birth_date="2015-12-10",
        guardian=guardian,
        training_group=None,
    )


@pytest.fixture
def training_group_a(db):
    from apps.members.models import TrainingGroup

    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def training_group_b(db):
    from apps.members.models import TrainingGroup

    return TrainingGroup.objects.create(name="U10 B", is_active=True)


@pytest.fixture
def inactive_training_group(db):
    from apps.members.models import TrainingGroup

    return TrainingGroup.objects.create(name="U10 Arhīvs", is_active=False)

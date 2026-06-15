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

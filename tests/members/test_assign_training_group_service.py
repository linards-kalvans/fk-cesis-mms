"""Tests for apps.members.services.assign_training_group."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from apps.members.services import assign_training_group


pytestmark = pytest.mark.django_db


@pytest.fixture
def actor(db):
    return User.objects.create_user(username="staff", is_staff=True)


def test_assign_group_to_member_with_no_group(member, training_group_a, actor):
    result = assign_training_group(member, training_group_a, actor)
    member.refresh_from_db()
    assert member.training_group_id == training_group_a.id
    assert result.pk == member.pk


def test_reassign_from_one_group_to_another(member, training_group_a, training_group_b, actor):
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])
    assign_training_group(member, training_group_b, actor)
    member.refresh_from_db()
    assert member.training_group_id == training_group_b.id


def test_clear_assignment_with_none(member, training_group_a, actor):
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])
    assign_training_group(member, None, actor)
    member.refresh_from_db()
    assert member.training_group is None


def test_idempotent_when_already_assigned_to_same_group(member, training_group_a, actor):
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])
    # Returning early is the only observable guarantee — we assert that no
    # extra UPDATE happens by capturing the queries.
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        assign_training_group(member, training_group_a, actor)
    update_queries = [q for q in ctx.captured_queries if "UPDATE" in q["sql"].upper()]
    assert update_queries == []


def test_idempotent_when_clearing_already_clear_member(member, actor):
    assert member.training_group is None
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        assign_training_group(member, None, actor)
    update_queries = [q for q in ctx.captured_queries if "UPDATE" in q["sql"].upper()]
    assert update_queries == []


def test_inactive_group_allowed_at_service_layer(member, inactive_training_group, actor):
    """Service layer is permissive — picker filtering is the view's job."""
    assign_training_group(member, inactive_training_group, actor)
    member.refresh_from_db()
    assert member.training_group_id == inactive_training_group.id

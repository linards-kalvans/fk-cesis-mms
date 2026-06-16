"""Merging training groups from the admin emits an AuditEvent."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditEvent
from apps.members.models import Member, TrainingGroup
from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_merge_emits_audit_event():
    g = make_guardian(full_name="V")
    target = TrainingGroup.objects.create(name="U10 A")
    dup = TrainingGroup.objects.create(name="U10 A dublikāts")
    Member.objects.create(full_name="A", guardian=g, training_group=dup)
    c = _staff_client()
    c.post(reverse("admin:members_traininggroup_changelist"), {
        "action": "merge_training_groups",
        "_selected_action": [str(target.pk), str(dup.pk)],
        "target": str(target.pk),
        "apply": "1",
    })
    e = AuditEvent.objects.get(action=AuditEvent.Action.TRAINING_GROUPS_MERGED)
    assert e.target_type == "traininggroup"
    assert e.target_id == str(target.pk)
    assert e.actor is not None and e.actor.username == "staff"
    assert e.metadata["merged_group_ids"] == [dup.pk]
    assert e.metadata["merged_names"] == ["U10 A dublikāts"]
    assert e.metadata["members_reparented"] == 1


def test_single_group_merge_emits_no_audit():
    a = TrainingGroup.objects.create(name="U10 A")
    c = _staff_client()
    c.post(reverse("admin:members_traininggroup_changelist"), {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk)],
    }, follow=True)
    assert not AuditEvent.objects.filter(
        action=AuditEvent.Action.TRAINING_GROUPS_MERGED
    ).exists()

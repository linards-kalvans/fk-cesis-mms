"""assign_training_group emits AuditEvents."""

import pytest
from django.contrib.auth.models import User

from apps.core.models import AuditEvent
from apps.members.models import Guardian, Member, TrainingGroup
from apps.members.services import assign_training_group

pytestmark = pytest.mark.django_db


def test_assign_and_clear_emit_events():
    actor = User.objects.create_user(username="staff", email="s@example.com")
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    grp = TrainingGroup.objects.create(name="U-12", is_active=True)

    assign_training_group(m, grp, actor)
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.TRAINING_GROUP_ASSIGNED, target_id=str(m.pk)
    ).exists()

    assign_training_group(m, None, actor)
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.TRAINING_GROUP_CLEARED, target_id=str(m.pk)
    ).exists()

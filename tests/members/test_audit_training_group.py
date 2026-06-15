"""assign_training_group emits AuditEvents."""

import pytest
from django.contrib.auth.models import User

from apps.core.models import AuditEvent
from apps.members.models import Member, TrainingGroup

from tests.support import make_guardian
from apps.members.services import assign_training_group

pytestmark = pytest.mark.django_db


def test_assign_and_clear_emit_events():
    actor = User.objects.create_user(username="staff", email="s@example.com")
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    grp = TrainingGroup.objects.create(name="U-12", is_active=True)

    assign_training_group(m, grp, actor)
    assigned = AuditEvent.objects.get(
        action=AuditEvent.Action.TRAINING_GROUP_ASSIGNED, target_id=str(m.pk)
    )
    assert assigned.actor == actor
    assert assigned.metadata == {"group": "U-12"}

    assign_training_group(m, None, actor)
    cleared = AuditEvent.objects.get(
        action=AuditEvent.Action.TRAINING_GROUP_CLEARED, target_id=str(m.pk)
    )
    assert cleared.actor == actor

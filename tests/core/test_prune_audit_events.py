"""prune_audit_events deletes events older than AUDIT_RETENTION_DAYS."""

import datetime

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.core.tasks import prune_audit_events

pytestmark = pytest.mark.django_db


def _event_aged(days: int) -> AuditEvent:
    e: AuditEvent = AuditEvent.objects.create(action=AuditEvent.Action.DOCUMENT_DOWNLOADED)
    # created_at is auto_now_add; rewrite it directly for the test.
    AuditEvent.objects.filter(pk=e.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=days)
    )
    return e


@override_settings(AUDIT_RETENTION_DAYS=30)
def test_deletes_old_keeps_recent():
    old = _event_aged(31)
    recent = _event_aged(5)
    deleted = prune_audit_events()
    assert deleted == 1
    assert not AuditEvent.objects.filter(pk=old.pk).exists()
    assert AuditEvent.objects.filter(pk=recent.pk).exists()


@override_settings(AUDIT_RETENTION_DAYS=30)
def test_keeps_event_just_inside_retention():
    # Aged one day under retention -> deterministically newer than the cutoff
    # (cutoff = now - 30d, computed slightly later) -> kept.
    e = _event_aged(29)
    prune_audit_events()
    assert AuditEvent.objects.filter(pk=e.pk).exists()


@override_settings(AUDIT_RETENTION_DAYS=30)
def test_prunes_event_at_retention_age():
    # Aged exactly retention days -> created_at (T0-30d) < cutoff (T1-30d) since
    # T1 > T0 -> pruned. Documents the strict-less-than boundary.
    e = _event_aged(30)
    prune_audit_events()
    assert not AuditEvent.objects.filter(pk=e.pk).exists()

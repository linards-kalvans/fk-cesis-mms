"""Scheduled background tasks for apps.core."""

import datetime
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def prune_audit_events() -> int:
    """Delete AuditEvent rows older than AUDIT_RETENTION_DAYS. Returns the count."""
    from apps.core.models import AuditEvent

    days = int(getattr(settings, "AUDIT_RETENTION_DAYS", 730))
    cutoff = timezone.now() - datetime.timedelta(days=days)
    deleted, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
    logger.info("prune_audit_events: deleted %s events older than %s days", deleted, days)
    return int(deleted)

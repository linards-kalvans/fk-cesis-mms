"""Audit helpers for FK Cēsis MMS.

record_audit_event is the single write path for the AuditEvent log. It is
fail-safe: any error while recording is swallowed and logged, never raised
into the audited business action.
"""

from __future__ import annotations

import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


def _client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return cast(str, xff.split(",")[0].strip())
    return cast("str | None", request.META.get("REMOTE_ADDR") or None)


def _user_agent(request) -> str:
    return str(request.META.get("HTTP_USER_AGENT", ""))[:400]


def _label_for(user) -> str:
    return getattr(user, "email", "") or getattr(user, "get_username", lambda: "")() or ""


def record_audit_event(
    *,
    action: str,
    actor=None,
    actor_label: str = "",
    target: Any = None,
    target_type: str = "",
    target_id: str = "",
    target_repr: str = "",
    metadata: dict | None = None,
    request=None,
):
    """Write one AuditEvent. Returns the row, or None if recording failed.

    Never raises — auditing must not break or roll back the audited action.
    """
    try:
        from apps.core.models import AuditEvent

        if request is not None and actor is None:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                actor = user

        if not actor_label and actor is not None:
            actor_label = _label_for(actor)

        if target is not None:
            if not target_type:
                target_type = target._meta.model_name
            if not target_id:
                target_id = str(getattr(target, "pk", "") or "")
            if not target_repr:
                target_repr = str(target)[:255]

        ip = _client_ip(request) if request is not None else None
        ua = _user_agent(request) if request is not None else ""

        return AuditEvent.objects.create(
            action=str(action),
            actor=actor,
            actor_label=actor_label[:255],
            target_type=target_type[:64],
            target_id=target_id[:64],
            target_repr=target_repr[:255],
            metadata=metadata or {},
            ip_address=ip,
            user_agent=ua,
        )
    except Exception:  # noqa: BLE001 — auditing must never break the audited action
        logger.warning("record_audit_event failed for action=%s", action, exc_info=True)
        return None

"""Service functions for the members domain."""

from __future__ import annotations

from django.conf import settings

from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent
from apps.members.models import Guardian, Member, TrainingGroup


def assign_training_group(
    member: Member,
    group: TrainingGroup | None,
    actor: settings.AUTH_USER_MODEL,
) -> Member:
    """Set or clear a member's training group. Idempotent.

    Service layer is intentionally permissive: it does not reject inactive
    groups. The view layer's picker filters for active groups; this service
    accepts whatever it is given so administrators can deliberately keep an
    inactive (legacy) assignment in place.
    """
    current_id = member.training_group_id
    new_id = group.id if group is not None else None
    if current_id == new_id:
        return member
    member.training_group = group
    member.save(update_fields=["training_group"])
    record_audit_event(
        action=str(
            AuditEvent.Action.TRAINING_GROUP_ASSIGNED
            if group is not None
            else AuditEvent.Action.TRAINING_GROUP_CLEARED
        ),
        actor=actor,
        target=member,
        metadata={"group": group.name if group is not None else None},
    )
    return member


def resolve_guardian_for_account(account) -> Guardian:
    """Return the canonical Guardian for a verified ParentAccount, creating it
    if absent. One verified email maps to exactly one Guardian, forever.

    Called when a registration is initiated so every application carries its
    parent's canonical guardian. The email is mirrored from the account on
    create (the Invoice Ninja client contact reads Guardian.email).
    """
    guardian: Guardian
    guardian, _created = Guardian.objects.get_or_create(
        parent_account=account,
        defaults={"email": account.email},
    )
    return guardian

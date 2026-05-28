"""Service functions for the members domain."""

from __future__ import annotations

from django.conf import settings

from apps.members.models import Member, TrainingGroup


def assign_training_group(
    member: Member,
    group: TrainingGroup | None,
    actor: settings.AUTH_USER_MODEL,  # noqa: ARG001 — plumbed for future P7 audit hook
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
    return member

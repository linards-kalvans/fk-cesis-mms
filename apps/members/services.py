"""Service functions for the members domain."""

from __future__ import annotations

from django.conf import settings
from django.db import transaction

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
    parent's canonical guardian. Email/phone are read through the linked
    account via the Guardian.email/phone proxies (the Invoice Ninja client
    contact reads Guardian.email).
    """
    guardian: Guardian
    guardian, _created = Guardian.objects.get_or_create(parent_account=account)
    return guardian


def _pick_survivor(guardians, member_model):
    """Choose the canonical guardian from a group sharing one parent account.

    Prefer the guardian with a non-empty external_client_id; else the one with
    the most members; else the lowest pk.
    """
    with_external = [g for g in guardians if (g.external_client_id or "").strip()]
    if with_external:
        return min(with_external, key=lambda g: g.pk)

    def member_count(g):
        return member_model.objects.filter(guardian=g).count()

    return max(guardians, key=lambda g: (member_count(g), -g.pk))


def consolidate_guardians(
    guardian_model=None,
    account_model=None,
    member_model=None,
    application_model=None,
):
    """Link orphan guardians to parent accounts, backfill, and merge duplicates.

    Idempotent. The injected ``*_model`` params let the data migration pass
    historical models via ``apps.get_model``; defaults bind the live models.
    Only basic manager methods (filter/create/update/delete/count) and field
    access are used so the function works on historical models too.
    """
    if guardian_model is None:
        guardian_model = Guardian
    if account_model is None:
        from apps.accounts.models import ParentAccount

        account_model = ParentAccount
    if member_model is None:
        member_model = Member
    if application_model is None:
        from apps.registrations.models import RegistrationApplication

        application_model = RegistrationApplication

    with transaction.atomic():
        # Step 1 — resolve every orphan guardian to a parent account, creating
        # the account when none exists. Because parent_account is a unique
        # OneToOne, guardians resolving to the same account must be merged here
        # before assignment so the constraint is never violated.
        orphans = list(
            guardian_model.objects.filter(parent_account__isnull=True)
        )
        # Group orphans by the account they resolve to.
        by_account: dict[int, list] = {}
        for guardian in orphans:
            email = (guardian.email or "").strip().lower()
            account = None
            if email:
                account = account_model.objects.filter(email__iexact=email).first()
            if account is None:
                account = account_model.objects.create(
                    email=email or f"guardian-{guardian.pk}@placeholder.invalid",
                    phone=guardian.phone or "",
                )
            by_account.setdefault(account.pk, []).append(guardian)

        for account_id, group in by_account.items():
            account = account_model.objects.get(pk=account_id)
            # An existing (non-orphan) guardian may already own this account.
            existing = guardian_model.objects.filter(
                parent_account_id=account_id
            ).first()
            if existing is not None:
                group = group + [existing]
            survivor = _pick_survivor(group, member_model)
            for loser in group:
                if loser.pk == survivor.pk:
                    continue
                _merge_into(loser, survivor, member_model, application_model)
            survivor.parent_account = account
            survivor.save(update_fields=["parent_account"])

        # Step 2 — backfill account phone from the guardian when empty.
        for guardian in guardian_model.objects.filter(
            parent_account__isnull=False
        ).select_related("parent_account"):
            account = guardian.parent_account
            if not (account.phone or "").strip() and (guardian.phone or "").strip():
                account.phone = guardian.phone
                account.save(update_fields=["phone", "updated_at"])


def _merge_into(loser, survivor, member_model, application_model):
    """Reassign a loser guardian's members/applications to the survivor, copy
    its external_client_id if the survivor lacks one, then delete the loser.
    """
    member_model.objects.filter(guardian=loser).update(guardian=survivor)
    application_model.objects.filter(guardian=loser).update(guardian=survivor)
    if not (survivor.external_client_id or "").strip() and (
        loser.external_client_id or ""
    ).strip():
        survivor.external_client_id = loser.external_client_id
        survivor.save(update_fields=["external_client_id"])
    loser.delete()

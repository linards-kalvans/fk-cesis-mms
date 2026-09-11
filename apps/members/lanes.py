"""Per-object lane status derivation, shared by the Family Hub and Admin Hub.

Extracted from ``family_hub.py`` so that page assembly (there) and status
derivation (here) are separate concerns and both staff surfaces read one
implementation. Adding a new lane state means editing this file only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.billing.messages import PAYMENT_STATUS_LABELS
from apps.billing.models import BillingRecord
from apps.registrations.models import RegistrationApplication

if TYPE_CHECKING:
    from apps.agreements.models import Agreement
    from apps.members.models import Member


_URGENCY_INFORMATIONAL = 0
_URGENCY_BILLING_PAYMENT_SYNC = 10
_URGENCY_BILLING_PUSH = 30
_URGENCY_BILLING_DRAFT = 40
_URGENCY_AGREEMENT_NEEDS_ACTION = 50
_URGENCY_APPLICATION_SUBMITTED = 80


@dataclass(frozen=True)
class FamilyLaneStatus:
    """A normalized status row for a single family/child lane.

    ``level`` is one of ok / fail / pending / muted (compatible with
    ``apps.core.admin_badges.status_badge``). ``urgency`` orders lanes in the
    action queue: higher = more urgent.
    """

    key: str
    label: str
    badge: str
    level: str
    icon: str
    next_action: str
    urgency: int


def application_lane(application: RegistrationApplication) -> FamilyLaneStatus:
    """Lane status for a registration application."""
    if application.status == RegistrationApplication.Status.SUBMITTED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums gaida apstiprinājumu",
            badge="Iesniegts",
            level="pending",
            icon="📝",
            next_action="Apstiprināt",
            urgency=_URGENCY_APPLICATION_SUBMITTED,
        )
    if application.status == RegistrationApplication.Status.FIX_REQUESTED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums jālabo",
            badge="Jālabo",
            level="fail",
            icon="✏",
            next_action="Skatīt",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if application.status == RegistrationApplication.Status.REJECTED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums noraidīts",
            badge="Noraidīts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if application.status == RegistrationApplication.Status.APPROVED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums apstiprināts",
            badge="Apstiprināts",
            level="ok",
            icon="✓",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    return FamilyLaneStatus(
        key="application",
        label="Melnraksts",
        badge="Melnraksts",
        level="muted",
        icon="📄",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def agreement_lane(agreement: "Agreement | None") -> FamilyLaneStatus:
    """Lane status for the member's current agreement (None = none)."""
    if agreement is None:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums nav izveidots",
            badge="—",
            level="muted",
            icon="—",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.external_state == "failed" or agreement.external_error_code:
        return FamilyLaneStatus(
            key="agreement",
            label="Līguma izsūtīšana neizdevās",
            badge="Kļūda",
            level="fail",
            icon="⚠",
            next_action="Mēģināt vēlreiz",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if agreement.state == agreement.State.GENERATED:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums sagatavots",
            badge="Sagatavots",
            level="pending",
            icon="📄",
            next_action="Atzīmēt nosūtītu",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if agreement.state == agreement.State.SENT:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums nosūtīts parakstīšanai",
            badge="Nosūtīts",
            level="pending",
            icon="✉",
            next_action="Atzīmēt parakstītu",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if agreement.state == agreement.State.SIGNED:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums parakstīts",
            badge="Parakstīts",
            level="ok",
            icon="✓",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.state == agreement.State.VOID:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums atcelts",
            badge="Atcelts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.state == agreement.State.DISCONTINUED:
        return FamilyLaneStatus(
            key="agreement",
            label="Dalība pārtraukta",
            badge="Pārtraukts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.state == agreement.State.SUPERSEDED:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums aizvietots",
            badge="Aizvietots",
            level="muted",
            icon="—",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    return FamilyLaneStatus(
        key="agreement",
        label=str(agreement.get_state_display()),
        badge=str(agreement.get_state_display()),
        level="muted",
        icon="—",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def membership_lane(member: "Member | None") -> FamilyLaneStatus:
    """Lane status for a member's participation state."""
    if member is None:
        return FamilyLaneStatus(
            key="membership",
            label="Biedrs nav izveidots",
            badge="—",
            level="muted",
            icon="—",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if member.status == member.Status.DISCONTINUED:
        return FamilyLaneStatus(
            key="membership",
            label="Dalība pārtraukta",
            badge="Pārtraukts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if member.training_group_id is None:
        return FamilyLaneStatus(
            key="membership",
            label="Biedrs aktīvs (grupa nav piešķirta)",
            badge="Bez grupas",
            level="pending",
            icon="👥",
            next_action="Piešķirt grupu",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    return FamilyLaneStatus(
        key="membership",
        label="Biedrs aktīvs",
        badge="Aktīvs",
        level="ok",
        icon="✓",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def billing_lane(record: BillingRecord) -> FamilyLaneStatus:
    """Lane status for a billing record."""
    if record.external_error_code:
        return FamilyLaneStatus(
            key="billing",
            label="Rēķinu izsūtīšana neizdevās",
            badge="Kļūda",
            level="fail",
            icon="⚠",
            next_action="Mēģināt vēlreiz",
            urgency=_URGENCY_BILLING_PUSH,
        )
    if record.status == BillingRecord.Status.DRAFT:
        return FamilyLaneStatus(
            key="billing",
            label="Norēķini sagatavoti (jāapstiprina)",
            badge="Melnraksts",
            level="pending",
            icon="💳",
            next_action="Apstiprināt",
            urgency=_URGENCY_BILLING_DRAFT,
        )
    if record.status == BillingRecord.Status.CONFIRMED and record.external_status != "synced":
        return FamilyLaneStatus(
            key="billing",
            label="Norēķini gaida izsūtīšanu",
            badge="Gaida izsūtīšanu",
            level="pending",
            icon="📨",
            next_action="Izrakstīt rēķinus",
            urgency=_URGENCY_BILLING_PUSH,
        )
    if record.external_status == "synced":
        if record.payment_status in {"unpaid", "partial", "paid"}:
            return FamilyLaneStatus(
                key="billing",
                label=f"Rēķini izsūtīti ({PAYMENT_STATUS_LABELS.get(record.payment_status, '—')})",
                badge="Sinhronizēts",
                level="ok",
                icon="✓",
                next_action="Pārbaudīt maksājumus",
                urgency=_URGENCY_BILLING_PAYMENT_SYNC,
            )
        return FamilyLaneStatus(
            key="billing",
            label="Rēķini izsūtīti",
            badge="Sinhronizēts",
            level="ok",
            icon="✓",
            next_action="Pārbaudīt maksājumus",
            urgency=_URGENCY_BILLING_PAYMENT_SYNC,
        )
    return FamilyLaneStatus(
        key="billing",
        label=str(record.get_status_display()),
        badge=str(record.get_status_display()),
        level="muted",
        icon="—",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def canonical_kit_size_label(obj) -> str:
    """Return the single canonical "Formas izmērs" label or '—'.

    Reads ``member_kit_size_shirt`` from a RegistrationApplication-like object.
    The legacy ``kit_size_shirt`` member fallback is gone: ``Member`` has no
    such field, and the canonical value lives on the source application.
    """
    option = getattr(obj, "member_kit_size_shirt", None)
    if option is None:
        return "—"
    return str(getattr(option, "label", "—") or "—")

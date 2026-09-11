"""Column definitions + row builders for the Members export.

P7 (kept): ``member_columns`` / ``member_row`` for the static admin changelist
action. P17 (added): a typed ``ColumnSpec`` registry that powers the
``MemberExportTemplate`` admin surface and in-memory CSV/XLSX rendering.

Readers in the registry must be pure — they read attributes off the passed
``Member`` instance (and its prefetched relations / helpers) and never issue
DB queries. Agreement readers use ``member._current_export_agreements`` (a
list prefetched by the export queryset, ``is_current=True`` only).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

from apps.agreements.models import Agreement
from apps.members.models import Member

# ---------------------------------------------------------------------------
# P7 — static changelist action exports (unchanged)
# ---------------------------------------------------------------------------

MEMBER_SAFE_COLUMNS = ["ID", "Vārds uzvārds", "Dzimšanas datums", "Vecāks", "Treniņu grupa"]
MEMBER_SENSITIVE_EXTRA = ["Personas kods", "Vecāka e-pasts", "Vecāka tālrunis", "Vecāka adrese"]


def member_columns(*, sensitive: bool) -> list[str]:
    return MEMBER_SAFE_COLUMNS + MEMBER_SENSITIVE_EXTRA if sensitive else list(MEMBER_SAFE_COLUMNS)


def member_row(member: Member, *, sensitive: bool) -> list:
    g = member.guardian  # non-null FK
    row: list = [
        member.pk,
        member.full_name,
        member.birth_date,
        g.display_name,
        member.training_group.name if member.training_group_id else "",
    ]
    if sensitive:
        row += [member.personal_id, g.email, g.phone, g.address]
    return row


# ---------------------------------------------------------------------------
# P17 — column registry for MemberExportTemplate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnSpec:
    """A typed column declaration for member export templates."""

    key: str
    label: str
    reader: Callable[[Member], object]
    sensitive: bool


# ---------------------------------------------------------------------------
# Readers — pure, attribute access only, no queries.
# ---------------------------------------------------------------------------


def _member_full_name(member: Member) -> str:
    return member.full_name or ""


def _member_personal_id(member: Member) -> str:
    return member.personal_id or ""


def _member_birth_date(member: Member):
    """Return the member's birth date as a ``datetime.date``.

    The instance attribute can be a string (pre-save) or a ``date`` (post-save);
    the public reader contract is always ``date``.
    """
    value = member.birth_date
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            return None
    return value


def _guardian_name(member: Member) -> str:
    if not getattr(member, "guardian_id", None):
        return ""
    g = member.guardian
    return g.display_name if g is not None else ""


def _guardian_email(member: Member) -> str:
    if not getattr(member, "guardian_id", None):
        return ""
    g = member.guardian
    return g.email if g is not None else ""


def _guardian_phone(member: Member) -> str:
    if not getattr(member, "guardian_id", None):
        return ""
    g = member.guardian
    return g.phone if g is not None else ""


def _guardian_address(member: Member) -> str:
    if not getattr(member, "guardian_id", None):
        return ""
    g = member.guardian
    return g.address if g is not None else ""


# Agreement state display values are derived from apps.agreements.models.Agreement.State.
def _agreement_state(member: Member):
    agreements = getattr(member, "_current_export_agreements", None)
    if not agreements:
        return "—"
    raw_state = agreements[0].state
    try:
        return Agreement.State(raw_state).label
    except ValueError:
        return raw_state or "—"


def _agreement_signed_at(member: Member):
    agreements = getattr(member, "_current_export_agreements", None)
    if not agreements:
        return None
    return agreements[0].signed_at


_PLACEHOLDER = "—"


def _training_group_name(member: Member) -> str:
    grp = member.training_group
    return grp.name if grp is not None else _PLACEHOLDER


# Ordered registry — insertion order is the public key list.
COLUMN_REGISTRY: dict[str, ColumnSpec] = {
    "member_full_name": ColumnSpec(
        key="member_full_name",
        label="Biedra vārds, uzvārds",
        reader=_member_full_name,
        sensitive=False,
    ),
    "member_personal_id": ColumnSpec(
        key="member_personal_id",
        label="Biedra personas kods",
        reader=_member_personal_id,
        sensitive=True,
    ),
    "member_birth_date": ColumnSpec(
        key="member_birth_date",
        label="Biedra dzimšanas datums",
        reader=_member_birth_date,
        sensitive=False,
    ),
    "guardian_name": ColumnSpec(
        key="guardian_name",
        label="Vecāka vārds, uzvārds",
        reader=_guardian_name,
        sensitive=False,
    ),
    "guardian_email": ColumnSpec(
        key="guardian_email",
        label="Vecāka e-pasts",
        reader=_guardian_email,
        sensitive=True,
    ),
    "guardian_phone": ColumnSpec(
        key="guardian_phone",
        label="Vecāka tālrunis",
        reader=_guardian_phone,
        sensitive=True,
    ),
    "guardian_address": ColumnSpec(
        key="guardian_address",
        label="Vecāka adrese",
        reader=_guardian_address,
        sensitive=True,
    ),
    "agreement_state": ColumnSpec(
        key="agreement_state",
        label="Līguma statuss",
        reader=_agreement_state,
        sensitive=False,
    ),
    "agreement_signed_at": ColumnSpec(
        key="agreement_signed_at",
        label="Līguma parakstīšanas datums",
        reader=_agreement_signed_at,
        sensitive=False,
    ),
    "training_group_name": ColumnSpec(
        key="training_group_name",
        label="Treniņu grupa",
        reader=_training_group_name,
        sensitive=False,
    ),
}


SENSITIVE_KEYS: frozenset[str] = frozenset(
    key for key, spec in COLUMN_REGISTRY.items() if spec.sensitive
)


VALID_AGREEMENT_STATES: tuple[str, ...] = tuple(
    value for value, _label in Agreement.State.choices
)


# ---------------------------------------------------------------------------
# Validation helpers — used by model.clean() and by the admin form. Imported
# lazily by the model to avoid a models ↔ exports circular import.
# ---------------------------------------------------------------------------


def validate_column_keys(column_keys) -> list[str]:
    """Return the cleaned column key list or raise ``ValidationError``."""
    from django.core.exceptions import ValidationError

    if not isinstance(column_keys, (list, tuple)):
        raise ValidationError(
            {"column_keys": "Kolonnu sarakstam jābūt sarakstam."}
        )
    cleaned: list[str] = []
    for key in column_keys:
        if not isinstance(key, str):
            raise ValidationError(
                {"column_keys": "Kolonnu atslēgai jābūt tekstam."}
            )
        if key not in COLUMN_REGISTRY:
            raise ValidationError(
                {"column_keys": f"Nezināma kolonna: {key!r}."}
            )
        cleaned.append(key)
    if not cleaned:
        raise ValidationError(
            {"column_keys": "Jāizvēlas vismaz viena kolonna."}
        )
    if len(set(cleaned)) != len(cleaned):
        raise ValidationError(
            {"column_keys": "Kolonnas nedrīkst atkārtoties."}
        )
    return cleaned


def validate_agreement_status_filters(states) -> list[str]:
    """Return the cleaned agreement-state list or raise ``ValidationError``."""
    from django.core.exceptions import ValidationError

    if states in (None, ""):
        return []
    if not isinstance(states, (list, tuple)):
        raise ValidationError(
            {"agreement_status_filters": "Statussarakstam jābūt sarakstam."}
        )
    cleaned: list[str] = []
    for state in states:
        if not isinstance(state, str):
            raise ValidationError(
                {"agreement_status_filters": "Statusam jābūt tekstam."}
            )
        if state not in VALID_AGREEMENT_STATES:
            raise ValidationError(
                {"agreement_status_filters": f"Nederīgs statuss: {state!r}."}
            )
        cleaned.append(state)
    if len(set(cleaned)) != len(cleaned):
        raise ValidationError(
            {"agreement_status_filters": "Statusi nedrīkst atkārtoties."}
        )
    return cleaned

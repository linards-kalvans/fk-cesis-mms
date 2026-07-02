"""Latvian copy helpers for parent-facing agreement status rendering."""

from __future__ import annotations

from apps.agreements.models import Agreement
from apps.members.models import Member


def agreement_status_copy(agreement: Agreement | None) -> str | None:
    """Return the Latvian status line for the given agreement, or None when
    nothing should be rendered (no agreement at all)."""
    if agreement is None:
        return None
    state = agreement.state
    if state == Agreement.State.GENERATED:
        return "Līgums sagatavots, drīzumā saņemsiet to parakstīšanai."
    if state == Agreement.State.SENT:
        if agreement.signing_path == Agreement.SigningPath.ELECTRONIC:
            return "Līgums nosūtīts uz e-pastu parakstīšanai."
        return "Klubs sazināsies ar Jums par līguma parakstīšanu."
    if state == Agreement.State.SIGNED:
        return "Līgums parakstīts ✓"
    if state == Agreement.State.VOID:
        return "Līgums atcelts."
    return None


def lifecycle_status_copy(agreement: Agreement | None, member: Member | None) -> str:
    """Current agreement/member lifecycle status shown in the parent portal."""
    if member is not None and member.status == Member.Status.DISCONTINUED:
        return "Dalība pārtraukta."
    if agreement is None:
        return "Līgums vēl nav sagatavots."
    if agreement.state == Agreement.State.SUPERSEDED:
        return "Līgums aizvietots ar jaunu versiju."
    if agreement.state == Agreement.State.DISCONTINUED:
        return "Līgums pārtraukts."
    return str(agreement.get_state_display())


def lifecycle_history_items(agreement: Agreement | None) -> list[dict[str, str]]:
    """Parent-visible agreement lifecycle history list."""
    if agreement is None:
        return []
    return [
        {
            "date": event.created_at.strftime("%d.%m.%Y"),
            "label": event.get_event_type_display(),
            "note": event.note,
        }
        for event in agreement.lifecycle_events.order_by("created_at")
    ]

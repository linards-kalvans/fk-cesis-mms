"""Latvian copy helpers for parent-facing agreement status rendering."""

from __future__ import annotations

from apps.agreements.models import Agreement


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

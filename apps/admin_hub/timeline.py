"""Agreement history for the agreement page's "Vēsture" sidecar.

The agreement page's actions (mark sent, set signing path, regenerate, void,
mark signed) never write an ``AgreementLifecycleEvent`` row — that model is
only populated by ``record_minor_amendment``, ``start_material_amendment``
and ``discontinue_agreement`` (none of which this page drives). Deriving the
timeline from real ``AgreementLifecycleEvent`` rows alone would therefore
read "Nav notikumu" through the entire generate -> send -> sign flow.

``build_agreement_timeline`` instead derives most of its entries from the
agreement's own lifecycle timestamps, which *are* persisted and already
displayed in this page's "Līguma dati" sidecar, and merges in any
``AgreementLifecycleEvent`` rows on top. It invents nothing: a null
timestamp yields no entry, never a synthesised date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.agreements.models import Agreement


@dataclass(frozen=True)
class TimelineEntry:
    """One row in the agreement history timeline."""

    when: datetime
    label: str
    detail: str = ""


def build_agreement_timeline(agreement: "Agreement") -> list[TimelineEntry]:
    """Agreement history from persisted state: the agreement's own lifecycle
    timestamps merged with any ``AgreementLifecycleEvent`` rows, newest
    first.

    Entries are built in a fixed, deterministic order — the four lifecycle
    timestamps (oldest stage first), then lifecycle-event rows ordered by
    ``(created_at, pk)`` — before the final sort. ``list.sort`` is stable
    and ``reverse=True`` preserves (rather than reverses) the relative order
    of equal keys, so two entries with an identical timestamp always come
    out in that same fixed order, never arbitrarily.
    """
    from apps.agreements.models import Agreement

    # django-stubs types a bare class-attribute access like
    # ``Agreement.State.GENERATED`` as a plain ``tuple[str, str]``, which has
    # no ``.label`` — a verified mypy-only quirk (this repo's
    # ``apps/members/exports.py`` already works around the same stub
    # limitation the same way: constructing through the enum rather than
    # reading a class attribute recovers the real, ``.label``-bearing type).
    def _label(value: str) -> str:
        return str(Agreement.State(value).label)

    entries: list[TimelineEntry] = []

    if agreement.generated_at is not None:
        entries.append(
            TimelineEntry(
                when=agreement.generated_at,
                label=_label(str(Agreement.State.GENERATED)),
            )
        )
    if agreement.sent_at is not None:
        entries.append(
            TimelineEntry(
                when=agreement.sent_at, label=_label(str(Agreement.State.SENT))
            )
        )
    if agreement.signed_at is not None:
        entries.append(
            TimelineEntry(
                when=agreement.signed_at, label=_label(str(Agreement.State.SIGNED))
            )
        )
    if agreement.voided_at is not None:
        entries.append(
            TimelineEntry(
                when=agreement.voided_at,
                label=_label(str(Agreement.State.VOID)),
                detail=agreement.void_reason,
            )
        )

    for event in agreement.lifecycle_events.order_by("created_at", "pk"):
        entries.append(
            TimelineEntry(
                when=event.created_at,
                label=event.get_event_type_display(),
                detail=event.actor_label,
            )
        )

    entries.sort(key=lambda entry: entry.when, reverse=True)
    return entries

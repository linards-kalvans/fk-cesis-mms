"""Latvian copy helpers for parent-facing agreement status rendering.

Also owns the shared admin document-link presentation items used by the
Family hub and the Registration admin change page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable, TypedDict

from apps.agreements.models import Agreement
from apps.members.models import Member

if TYPE_CHECKING:
    pass


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


# ---------------------------------------------------------------------------
# Admin document-link presentation
# ---------------------------------------------------------------------------


class AgreementDocumentLink(TypedDict):
    """One row in the admin "agreement documents" list.

    ``download_url`` is a **fully built** same-origin URL — the partial that
    renders this list is URL-agnostic, so each surface owns its URL builder
    (Family hub → guardian-scoped proxy; Registration admin → application +
    agreement-scoped proxy; Agreement admin → inline iframe / download on
    its own row). The DocuSeal document URL itself is never stored in
    ``download_url`` and never appears in the rendered HTML.
    """

    agreement: Agreement
    state_label: str
    signing_path_label: str
    download_url: str


def build_agreement_document_links(
    agreements: Iterable[Agreement],
    *,
    url_builder: Callable[[Agreement], str],
) -> list[dict[str, object]]:
    """Return one ``AgreementDocumentLink`` per agreement, in input order.

    The helper intentionally does NOT filter by ``external_id`` — callers
    own the external-id check (the admin surfaces hide the link, the
    per-row display is still meaningful, and unit-tests can pass a blank
    row to assert the no-filter contract). Labels come from
    ``agreement.get_state_display()`` and ``agreement.get_signing_path_display()``
    so the partial renders the same Latvian copy as the rest of the admin
    shell.

    The return type is ``list[dict[str, object]]`` rather than the
    ``AgreementDocumentLink`` TypedDict so callers (and mypy) can mix the
    rows into other dict-typed contexts without ceremony; the TypedDict
    remains a documentation aid for the four keys rendered by the
    shared partial.
    """
    return [
        {
            "agreement": agreement,
            "state_label": str(agreement.get_state_display()),
            "signing_path_label": str(agreement.get_signing_path_display()),
            "download_url": url_builder(agreement),
        }
        for agreement in agreements
    ]

"""Pure presentation helpers for parent-facing application workspace.

Task 3 scope only — no business logic, no admin UX, no OCR provider work.
"""

from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

# Canonical Latvian display labels for document kinds, shown on the
# parent workspace. Admin surfaces continue to use Document.Kind's
# get_kind_display() which carries the underlying enum labels.
DOCUMENT_KIND_LABELS: dict[str, str] = {
    "guardian_identity": "Vecāka personu apliecinošs dokuments",
    "member_identity": "Bērna personu apliecinošs dokuments",
    "member_portrait": "Bērna foto",
}

# Canonical mapping: kind key → form field id anchor.
DOCUMENT_FIELD_ID_MAP = {
    "guardian_identity": "id_guardian_identity_document",
    "member_identity": "id_member_identity_document",
    "member_portrait": "id_member_portrait_document",
}

# Source-label mapping used by workspace template.
SOURCE_LABEL_MAP = {
    "ocr_guardian_identity": "Aizpildīts no dokumenta",
    "ocr_member_identity": "Aizpildīts no dokumenta",
    "manual_only": "Ievadījāt jūs",
    "derived_system_filled": "Aizpildīts no pārbaudīta konta",
    "review_hint_extracted": "Lūdzu, pārbaudiet",
}


_FIELD_TO_KIND: dict[str, str] = {
    "guardian_identity_document": "guardian_identity",
    "member_identity_document": "member_identity",
    "member_portrait_document": "member_portrait",
}

# Canonical mapping: kind key → form field name (inverse of _FIELD_TO_KIND).
# Used by the workspace view to build ``document_bound_fields`` so the
# document_card partial can render the canonical file input via the
# RegistrationApplicationForm BoundField.
FIELD_NAME_BY_KIND: dict[str, str] = {kind: field for field, kind in _FIELD_TO_KIND.items()}

FIELD_KIND_LABELS: dict[str, str] = {
    field: Document.Kind(kind).label for field, kind in _FIELD_TO_KIND.items()
}


def documents_by_field_name(application: RegistrationApplication) -> dict:
    """Return {form_field_name: Document | None} for active documents."""
    kind_map = active_documents_by_kind(application)
    return {field: kind_map.get(kind) for field, kind in _FIELD_TO_KIND.items()}


def workspace_mode(application: RegistrationApplication, account) -> str:
    """Return 'editable' or 'read_only' based on ownership + status."""
    return "editable" if application.is_editable_by(account) else "read_only"


def active_documents_by_kind(application: RegistrationApplication) -> dict:
    """Return {kind: Document | None} for active (non-deleted) documents."""
    docs: dict[str, Document | None] = {kind: None for kind in Document.Kind.values}
    for document in application.documents.filter(deleted_at__isnull=True).order_by("-created_at"):
        if docs.get(document.kind) is None:
            docs[document.kind] = document
    return docs


def source_label(source_value: str | None) -> str | None:
    """Map a field_sources value to a human-readable label."""
    if source_value is None:
        return None
    return SOURCE_LABEL_MAP.get(source_value)


def classify_field_action(current_value: str | None, ocr_value: str | None) -> str:
    """Decide what OCR should do with a field that has *current_value*.

    Mirror of static/js/async_upload.js::classifyFieldAction so server-side
    rendering and client-side rendering stay in sync.

    Returns one of:
      - "prefill": fill the field (current is empty/whitespace, OCR has a value)
      - "suggest": surface a chip beside the field for the user to accept
      - "noop":    do nothing (no OCR value, or values already match)
    """
    cur = (current_value or "").strip()
    ocr = (ocr_value or "").strip()
    if not ocr:
        return "noop"
    if not cur:
        return "prefill"
    if cur.casefold() == ocr.casefold():
        return "noop"
    return "suggest"


# Latvian labels for OCR-extracted field keys. Keys match the raw key
# names emitted by apps/integrations/tasks.py when building the
# encrypted summary; values are the human-readable Latvian labels shown
# in the parent workspace's "OCR kopsavilkums" section.
OCR_FIELD_LABELS: dict[str, str] = {
    "first_name": "Vārds",
    "last_name": "Uzvārds",
    "personal_id": "Personas kods",
    "document_number": "Dokumenta numurs",
    "issuer": "Izsniedzējs",
    "issuance_date": "Izsniegšanas datums",
    "expiry_date": "Derīguma termiņš",
}


def parse_ocr_summary(summary: str | None) -> list[tuple[str, str]]:
    """Convert a multi-line ``key: value`` OCR summary string into
    ``[(label, value), …]`` tuples for template rendering.

    Unknown keys fall back to a title-cased version of the raw key so the
    workspace never renders the underscored identifier directly. Empty or
    whitespace-only input returns an empty list.
    """
    if not summary:
        return []
    pairs: list[tuple[str, str]] = []
    for line in summary.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        label = OCR_FIELD_LABELS.get(key, key.replace("_", " ").title())
        pairs.append((label, value))
    return pairs

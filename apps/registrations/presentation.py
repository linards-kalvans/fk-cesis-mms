"""Pure presentation helpers for parent-facing application workspace.

Task 3 scope only — no business logic, no admin UX, no OCR provider work.
"""

from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

# Canonical mapping: underscored kind key → human-readable display label.
# Used by document_card.html for empty-state labels.
DOCUMENT_KIND_LABELS: dict[str, str] = {
    kind.value: kind.label for kind in list(Document.Kind)
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

"""tiny-IDP adapter — normalizes provider response to OCRExtractionResult.

This module is a thin adapter between the tiny-IDP JSON response format
and our normalized OCRExtractionResult schema.
"""

from __future__ import annotations

from typing import Any

from apps.integrations.ocr import OCRExtractionResult


# Mapping from provider entity fields to normalized keys
_PERSON_FIELD_MAP = {
    "first_name": "first_name",
    "last_name": "last_name",
    "personal_id": "personal_id",
}

# Mapping from provider document fields to normalized keys
_DOCUMENT_FIELD_MAP = {
    "document_number": "document_number",
    "issuer": "issuer",
    "issuance_date": "issuance_date",
    "expiry_date": "expiry_date",
}


def normalize_tiny_idp_response(
    kind: str,
    payload: dict[str, Any],
) -> OCRExtractionResult:
    """Normalize a tiny-IDP JSON response into OCRExtractionResult.

    Args:
        kind: Document kind (e.g. "guardian_identity", "member_identity").
        payload: Raw JSON response from tiny-IDP provider.

    Returns:
        OCRExtractionResult with normalized fields.
    """
    subject = kind.split("_")[0]

    # Extract person fields
    person_fields: dict[str, str] = {}
    entities = payload.get("entities", [])
    for entity in entities:
        if entity.get("type") == "person":
            raw_fields = entity.get("fields", {})
            for provider_key, normalized_key in _PERSON_FIELD_MAP.items():
                value = raw_fields.get(provider_key)
                if value is not None:
                    person_fields[normalized_key] = str(value)

    # Extract document metadata
    document_metadata: dict[str, str] = {}
    doc_info = payload.get("document", {})
    for provider_key, normalized_key in _DOCUMENT_FIELD_MAP.items():
        value = doc_info.get(provider_key)
        if value is not None:
            document_metadata[normalized_key] = str(value)

    # Confidence — pass through as-is
    confidence = payload.get("confidence", {})

    # Flags — pass through as-is
    flags = payload.get("flags", [])

    # Raw reference
    raw_reference = {
        "provider": "tiny_idp",
        "provider_version": payload.get("model_version", ""),
    }

    return OCRExtractionResult(
        subject=subject,
        person_fields=person_fields,
        document_metadata=document_metadata,
        confidence=confidence,
        flags=flags,
        raw_reference=raw_reference,
    )

"""OCR provider abstraction — stub + orchestrator.

Provides:
- OCRProviderMode (string enum)
- OCRExtractionResult (dataclass, normalized schema)
- extract_document_data(kind, file_name, content, content_type)
- safe_extract_document_data(...) — exception-safe wrapper
- Stub provider implementation
"""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class OCRProviderMode(str, enum.Enum):
    STUB = "stub"
    TINY_IDP = "tiny_idp"

OCR_KIND_GUARDIAN_IDENTITY = "guardian_identity"
OCR_KIND_MEMBER_IDENTITY = "member_identity"

# Document kinds that should be processed by OCR.
# member_portrait is intentionally excluded.
OCR_SUPPORTED_KINDS = {OCR_KIND_GUARDIAN_IDENTITY, OCR_KIND_MEMBER_IDENTITY}


@dataclass
class OCRExtractionResult:
    """Normalized extraction result — same shape regardless of provider."""

    subject: str  # "guardian" | "member"
    person_fields: dict[str, str] = field(default_factory=dict)
    document_metadata: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    flags: list[dict[str, Any]] = field(default_factory=list)
    raw_reference: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stub provider
# ---------------------------------------------------------------------------

_STUB_GUARDIAN_NAMES = [
    ("Anna", "Bērziņa"),
    ("Māra", "Kļava"),
    ("Ieva", "Zariņa"),
    ("Līga", "Ozoliņa"),
    ("Dace", "Vīksna"),
]

_STUB_MEMBER_NAMES = [
    ("Jānis", "Kalējs"),
    ("Lukas", "Bērziņš"),
    ("Artūrs", "Ozols"),
    ("Emīls", "Kalniņš"),
    ("Toms", "Vītoliņš"),
]


def _stub_person(kind: str) -> tuple[str, str]:
    """Return deterministic stub person name based on kind."""
    if kind == OCR_KIND_GUARDIAN_IDENTITY:
        return _STUB_GUARDIAN_NAMES[0]
    return _STUB_MEMBER_NAMES[0]


def _stub_doc_number(kind: str, file_name: str) -> str:
    """Deterministic document number from kind + filename hash."""
    h = hashlib.sha256(f"{kind}:{file_name}".encode()).hexdigest()[:8].upper()
    if kind == OCR_KIND_GUARDIAN_IDENTITY:
        return f"AB{h[:6]}"
    return f"CD{h[:6]}"


def _stub_personal_id(kind: str) -> str:
    """Deterministic Latvian personal ID."""
    if kind == OCR_KIND_GUARDIAN_IDENTITY:
        return "010101-10001"
    return "010125-10001"


def _stub_extraction(kind: str, file_name: str) -> OCRExtractionResult:
    """Build a deterministic stub extraction result."""
    first_name, last_name = _stub_person(kind)
    doc_number = _stub_doc_number(kind, file_name)

    return OCRExtractionResult(
        subject=kind.split("_")[0],
        person_fields={
            "first_name": first_name,
            "last_name": last_name,
            "personal_id": _stub_personal_id(kind),
        },
        document_metadata={
            "document_number": doc_number,
            "issuer": "MLP",
            "issuance_date": "2020-01-01",
            "expiry_date": "2030-01-01",
        },
        confidence={
            "first_name": 0.98,
            "last_name": 0.97,
            "personal_id": 0.99,
            "document_number": 0.95,
        },
        flags=[],
        raw_reference={"provider": "stub"},
    )


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------


def _extract_with_stub(
    kind: str,
    file_name: str,
    content: bytes,
    content_type: str,
) -> OCRExtractionResult:
    """Stub provider — returns deterministic extraction."""
    del content, content_type  # stub ignores content
    return _stub_extraction(kind, file_name)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_document_data(
    *,
    kind: str,
    file_name: str,
    content: bytes,
    content_type: str,
) -> OCRExtractionResult:
    """Dispatch extraction to the configured provider.

    Returns an OCRExtractionResult with normalized fields.
    Raises on unknown provider mode.
    """
    mode: str = getattr(settings, "OCR_PROVIDER_MODE", "stub")
    if mode == "stub":
        return _extract_with_stub(kind, file_name, content, content_type)
    elif mode == "tiny_idp":
        raise NotImplementedError("tiny_idp provider not yet implemented")
    else:
        raise ValueError(f"unknown OCR provider mode: {mode}")


def safe_extract_document_data(
    *,
    kind: str,
    file_name: str,
    content: bytes,
    content_type: str,
) -> tuple[OCRExtractionResult | None, str | None]:
    """Safe wrapper: returns (result, None) on success or (None, error_code) on failure."""
    try:
        result = extract_document_data(
            kind=kind,
            file_name=file_name,
            content=content,
            content_type=content_type,
        )
        return result, None
    except Exception:
        return None, "provider_unavailable"

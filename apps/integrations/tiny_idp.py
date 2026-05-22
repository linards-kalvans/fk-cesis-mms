"""tiny-IDP provider runtime — config validation, HTTP transport, normalization.

Exception hierarchy:

    TinyIdpError (base)
    ├── ProviderMisconfigurationError
    ├── AuthError
    ├── RateLimitError
    ├── RequestTimeoutError
    ├── ProviderUnavailableError
    └── InvalidResponseError

Public API:
    - normalize_tiny_idp_response(kind, payload) — adapter (unchanged)
    - validate_tiny_idp_config() — raises on missing config
    - extract_document(kind, file_name, content, content_type) — HTTP transport
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from django.conf import settings

from apps.integrations.ocr import OCRExtractionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TinyIdpError(Exception):
    """Base exception for all tiny-IDP provider errors."""


class ProviderMisconfigurationError(TinyIdpError):
    """Required tiny-IDP configuration is missing or invalid."""


class AuthError(TinyIdpError):
    """Authentication failed (401/403)."""


class RateLimitError(TinyIdpError):
    """Rate limit exceeded (429)."""


class RequestTimeoutError(TinyIdpError):
    """Request timed out."""


class ProviderUnavailableError(TinyIdpError):
    """Provider is unreachable (connection refused, DNS failure, etc.)."""


class InvalidResponseError(TinyIdpError):
    """Provider returned an unparseable / invalid response."""


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def validate_tiny_idp_config() -> None:
    """Validate that canonical tiny-IDP config is present.

    Raises:
        ProviderMisconfigurationError: If TINY_IDP_API_URL or
            TINY_IDP_API_KEY is missing/None.
    """
    api_url = getattr(settings, "TINY_IDP_API_URL", None)
    api_key = getattr(settings, "TINY_IDP_API_KEY", None)

    if not api_url:
        raise ProviderMisconfigurationError(
            "TINY_IDP_API_URL is not configured"
        )
    if not api_key:
        raise ProviderMisconfigurationError(
            "TINY_IDP_API_KEY is not configured"
        )


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


def post_document(
    *,
    file_name: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """Post a document to tiny-IDP and return the raw JSON payload.

    HTTP-only entrypoint: does not normalize. Intended for callers that need
    direct access to provider output (e.g. the live-validation harness).

    Raises:
        ProviderMisconfigurationError: If config is missing.
        AuthError: If HTTP 401/403.
        RateLimitError: If HTTP 429.
        RequestTimeoutError: On connection timeout.
        ProviderUnavailableError: On connection refused / network errors.
        InvalidResponseError: On malformed / non-JSON response.
    """
    validate_tiny_idp_config()

    api_url = settings.TINY_IDP_API_URL  # type: ignore[attr-defined]
    api_key = settings.TINY_IDP_API_KEY  # type: ignore[attr-defined]

    files = {"file": (file_name, content, content_type)}
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(api_url, files=files, headers=headers)
    except OSError as exc:
        msg = str(exc).lower()
        if "timeout" in msg or "timed out" in msg:
            raise RequestTimeoutError(str(exc)) from exc
        raise ProviderUnavailableError(str(exc)) from exc

    try:
        resp.raise_for_status()
    except Exception as exc:
        status = getattr(resp, "status_code", None)
        if status in (401, 403):
            raise AuthError(f"Authentication failed: {exc}") from exc
        if status == 429:
            raise RateLimitError(f"Rate limited: {exc}") from exc
        raise ProviderUnavailableError(
            f"Provider error {status}: {exc}"
        ) from exc

    try:
        payload: dict[str, Any] = resp.json()
    except ValueError as exc:
        raise InvalidResponseError(
            f"Malformed JSON response: {exc}"
        ) from exc

    return payload


def extract_document(
    *,
    kind: str,
    file_name: str,
    content: bytes,
    content_type: str,
) -> OCRExtractionResult:
    """Post a document to tiny-IDP and return the normalized extraction result.

    Thin wrapper over `post_document` + `normalize_tiny_idp_response`.

    Raises:
        See `post_document` for the full exception list.
    """
    payload = post_document(
        file_name=file_name,
        content=content,
        content_type=content_type,
    )
    return normalize_tiny_idp_response(kind, payload)


# ---------------------------------------------------------------------------
# Normalizer (unchanged)
# ---------------------------------------------------------------------------

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

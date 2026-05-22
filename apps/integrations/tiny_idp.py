"""tiny-IDP provider runtime — config validation, HTTP transport, normalization.

Targets the real generic-id-document extractor at api.tiny-idp.com:

    POST {TINY_IDP_API_URL}
        headers: {"x-api-key": <api_key>}
        files:   {"files": (file_name, content, content_type)}

    Success response:
        {"success": true, "data": {...}, "balance": float, "cost": float}
    Failure response:
        {"success": false, "cost": 0}

Exception hierarchy:

    TinyIdpError (base)
    ├── ProviderMisconfigurationError
    ├── AuthError
    ├── RateLimitError
    ├── RequestTimeoutError
    ├── ProviderUnavailableError
    └── InvalidResponseError

Public API:
    - normalize_tiny_idp_response(kind, payload) — adapter
    - validate_tiny_idp_config() — raises on missing config
    - post_document(...) — HTTP transport, returns raw payload
    - extract_document(kind, file_name, content, content_type) — transport + normalize
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

    files = {"files": (file_name, content, content_type)}
    headers = {"x-api-key": api_key}

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
        See `post_document` for the full exception list, plus
        InvalidResponseError from the normalizer for success=false or
        missing data field.
    """
    payload = post_document(
        file_name=file_name,
        content=content,
        content_type=content_type,
    )
    return normalize_tiny_idp_response(kind, payload)


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

# Mapping from provider person-field keys (under data.) to normalized keys.
_PERSON_FIELD_MAP = {
    "given_names": "first_name",
    "first_surname": "last_name",
    "personal_number": "personal_id",
    "date_of_birth": "date_of_birth",
}

# Mapping from provider document-field keys (under data.) to normalized keys.
_DOCUMENT_FIELD_MAP = {
    "document_number": "document_number",
    "issuing_authority": "issuer",
    "issuing_date": "issuance_date",
    "expiry_date": "expiry_date",
}

# Provider key → verified-flag key, used to derive confidence.
# Only fields the provider reports a *_verified bool for are included.
_VERIFIED_FLAG_MAP = {
    "given_names": "given_names_verified",
    "first_surname": "first_surname_verified",
    "personal_number": "personal_number_verified",
    "date_of_birth": "date_of_birth_verified",
    "document_number": "document_number_verified",
    "issuing_date": "issuing_date_verified",
    "expiry_date": "expiry_date_verified",
    # issuing_authority has no *_verified flag in the real spec.
}


def normalize_tiny_idp_response(
    kind: str,
    payload: dict[str, Any],
) -> OCRExtractionResult:
    """Normalize a tiny-IDP JSON response into OCRExtractionResult.

    Args:
        kind: Document kind (e.g. "guardian_identity", "member_identity").
        payload: Raw JSON response from tiny-IDP provider (real shape).

    Returns:
        OCRExtractionResult with normalized fields.

    Raises:
        InvalidResponseError: If payload signals success=false or omits the
            "data" field.
    """
    if payload.get("success") is False:
        raise InvalidResponseError("tiny-IDP returned success=false")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise InvalidResponseError("tiny-IDP missing data field")

    subject = kind.split("_")[0]

    # Extract person fields — skip empty strings ("not extracted").
    person_fields: dict[str, str] = {}
    for provider_key, normalized_key in _PERSON_FIELD_MAP.items():
        value = data.get(provider_key)
        if isinstance(value, str) and value != "":
            person_fields[normalized_key] = value

    # Extract document metadata — skip empty strings.
    document_metadata: dict[str, str] = {}
    for provider_key, normalized_key in _DOCUMENT_FIELD_MAP.items():
        value = data.get(provider_key)
        if isinstance(value, str) and value != "":
            document_metadata[normalized_key] = value

    # Confidence — derive from *_verified flags. Only emit confidence for
    # fields whose value is present (non-empty), and that we actually map.
    confidence: dict[str, float] = {}
    combined_map = {**_PERSON_FIELD_MAP, **_DOCUMENT_FIELD_MAP}
    for provider_key, normalized_key in combined_map.items():
        flag_key = _VERIFIED_FLAG_MAP.get(provider_key)
        if flag_key is None:
            continue
        value = data.get(provider_key)
        if not isinstance(value, str) or value == "":
            continue
        verified = bool(data.get(flag_key))
        confidence[normalized_key] = 1.0 if verified else 0.0

    # No analogue for flags in real API.
    flags: list[dict[str, Any]] = []

    raw_reference = {
        "provider": "tiny_idp",
        "provider_version": "",
    }

    return OCRExtractionResult(
        subject=subject,
        person_fields=person_fields,
        document_metadata=document_metadata,
        confidence=confidence,
        flags=flags,
        raw_reference=raw_reference,
    )

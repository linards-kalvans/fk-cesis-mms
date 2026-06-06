"""Latvian copy for DocuSeal integration error codes (P5 Slice D)."""

from __future__ import annotations

_GENERIC = "Radās kļūda saziņā ar DocuSeal. Mēģiniet vēlreiz."

_MESSAGES: dict[str, str] = {
    "auth_failed": "DocuSeal autentifikācija neizdevās. Pārbaudiet API atslēgu.",
    "misconfigured": "DocuSeal konfigurācija nav pilnīga. Sazinieties ar administratoru.",
    "not_found": "DocuSeal dokuments nav atrasts.",
    "provider_error": _GENERIC,
    "unavailable": "DocuSeal pašlaik nav pieejams. Mēģiniet vēlāk.",
}


def get_agreement_error_message(error_code: str) -> str:
    """Return Latvian copy for a stored external_error_code, generic fallback."""
    return _MESSAGES.get(error_code, _GENERIC)

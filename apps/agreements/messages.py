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


# Local generation/lifecycle refusals are raised as stable, PII-free codes.
_LOCAL_LIFECYCLE_MESSAGES: dict[str, str] = {
    "document_not_ready": "Lokālais līguma PDF vēl nav sagatavots.",
    "document_unavailable": "Lokālais līguma PDF nav pieejams.",
    "document_integrity": "Lokālā līguma PDF pārbaude neizdevās.",
    "signed artifact required": "Vispirms augšupielādējiet parakstīto līgumu.",
    "signing path is frozen": (
        "Parakstīšanas veids ir fiksēts pēc līguma PDF sagatavošanas."
    ),
    "signing path mismatch": (
        "Līguma parakstīšanas veids neatbilst sagatavotajam PDF."
    ),
    "docuseal creation disabled": (
        "Jaunu DocuSeal sūtījumu izveide ir izslēgta."
    ),
    "guardian email required for electronic agreement": (
        "Elektroniskajam līgumam nav norādīts vecāka e-pasts."
    ),
}


def get_local_lifecycle_message(error: str) -> str | None:
    """Return Latvian copy for a local lifecycle refusal code, or None."""
    return _LOCAL_LIFECYCLE_MESSAGES.get(error)

"""Latvian copy for OCR error codes surfaced to parents.

The codes themselves are produced by `apps.integrations.ocr._classify_exception`
and persisted on `Document.ocr_error_code`. Keeping the user-facing copy in
one pure module means JS only renders text — no embedded English fallbacks,
no per-code branching on the client.
"""

from __future__ import annotations

# Order matches the classifier; copy is Latvian-only by project policy.
OCR_ERROR_MESSAGES_LV: dict[str, str] = {
    "provider_misconfigured": (
        "OCR pakalpojums šobrīd nav konfigurēts. "
        "Lūdzu, aizpildi laukus manuāli."
    ),
    "auth_failed": (
        "Neizdevās autorizēties OCR pakalpojumā. "
        "Lūdzu, aizpildi laukus manuāli — mēs to atrisināsim īsumā."
    ),
    "rate_limited": (
        "OCR pakalpojums šobrīd ir noslogots. "
        "Pamēģini pēc brīža vai aizpildi laukus manuāli."
    ),
    "request_timeout": (
        "OCR atbilde nepienāca laikā. "
        "Pamēģini vēlreiz vai aizpildi laukus manuāli."
    ),
    "provider_unavailable": (
        "OCR pakalpojums šobrīd nav pieejams. "
        "Pamēģini vēlāk vai aizpildi laukus manuāli."
    ),
    "invalid_response": (
        "Saņēmām neparedzētu atbildi no OCR pakalpojuma. "
        "Lūdzu, aizpildi laukus manuāli."
    ),
}


_GENERIC_FALLBACK_LV = (
    "Neizdevās apstrādāt dokumentu automātiski. "
    "Lūdzu, aizpildi laukus manuāli."
)


def get_ocr_error_message(code: str | None) -> str:
    """Return a Latvian message for an OCR error code.

    Unknown or empty codes return a generic "please fill manually" fallback
    so the UI never leaks raw codes to parents.
    """
    if not code:
        return _GENERIC_FALLBACK_LV
    return OCR_ERROR_MESSAGES_LV.get(code, _GENERIC_FALLBACK_LV)

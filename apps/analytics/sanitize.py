"""Analytics event-property and referral-code sanitization (P10).

The model is deny-by-default:

- `sanitize_referral_code` enforces the public format spec
  (`[a-z0-9_-]`, ≤ 64 chars, lowercased).
- `sanitize_event_props` keeps only the allowlisted prop keys and sanitises
  the `referral_code` value through the same helper. Anything else is
  silently dropped, including the request, user, and application objects.
"""

from __future__ import annotations

from collections.abc import Mapping
import re

REFERRAL_CODE_MAX_LENGTH = 64
_REFERRAL_RE = re.compile(r"^[a-z0-9_-]+$")

ALLOWED_PROP_KEYS = {
    "page_area",
    "event_source",
    "application_status",
    "referral_code",
    "error_kind",
}

ALLOWED_PROP_VALUE_MAX_LENGTH = 128


def sanitize_referral_code(value: object) -> str:
    code = str(value or "").strip().lower()
    if not code:
        return ""
    code = code[:REFERRAL_CODE_MAX_LENGTH]
    if not _REFERRAL_RE.fullmatch(code):
        return ""
    return code


def sanitize_event_props(props: Mapping[str, object] | None) -> dict[str, str]:
    if not props:
        return {}
    clean: dict[str, str] = {}
    for key, value in props.items():
        if key not in ALLOWED_PROP_KEYS:
            continue
        text = str(value or "").strip()
        if not text:
            continue
        if key == "referral_code":
            text = sanitize_referral_code(text)
            if not text:
                continue
        clean[key] = text[:ALLOWED_PROP_VALUE_MAX_LENGTH]
    return clean

"""Latvian name normalization for OCR-extracted person fields.

OCR providers (tiny-IDP and similar) return names in ALL CAPS following
passport/eID conventions. Latvian display convention is title case, with
nobiliary particles ("van", "de", "von", ...) kept lowercase except when
they are the first token of the name. Hyphenated compound surnames must
capitalize each sub-token.

The helper is pure and side-effect free; apply it only at consumption
boundaries (summary rendering, prefill reads). The encrypted OCR payload
at rest is intentionally left raw to preserve audit posture.
"""

from __future__ import annotations

# Nobiliary particles that stay lowercase except when they are the first
# token of the name. Kept conservative — only common forms used in Latvia.
_PARTICLES: frozenset[str] = frozenset(
    {
        "van",
        "der",
        "den",
        "de",
        "da",
        "di",
        "du",
        "la",
        "le",
        "von",
        "zu",
        "af",
        "al",
    }
)


def _cap_subtoken(subtoken: str) -> str:
    """Capitalize a single sub-token preserving diacritics.

    Empty string returns empty string. Otherwise: first character upper,
    remaining characters lower.
    """
    if not subtoken:
        return ""
    return subtoken[0].upper() + subtoken[1:].lower()


def _normalize_token(token: str, *, is_first: bool) -> str:
    """Normalize a whitespace-separated token.

    Handles hyphenated compound surnames by splitting on ``-`` and
    capitalizing each sub-token. Particles (e.g. "van") stay lowercase
    unless they form the first token of the full name.
    """
    if not token:
        return ""

    if "-" in token:
        sub_tokens = token.split("-")
        normalized_sub = []
        for index, sub in enumerate(sub_tokens):
            lower_sub = sub.lower()
            if lower_sub in _PARTICLES and not (is_first and index == 0):
                normalized_sub.append(lower_sub)
            else:
                normalized_sub.append(_cap_subtoken(sub))
        return "-".join(normalized_sub)

    lower_token = token.lower()
    if lower_token in _PARTICLES and not is_first:
        return lower_token
    return _cap_subtoken(token)


def normalize_latvian_name(name: object) -> str:
    """Convert an OCR-provided name to Latvian title case.

    Pure helper — no I/O, no Django imports. Safe to call from any layer.

    Args:
        name: Raw name string from OCR (typically ALL CAPS). Non-string
            input is defensively coerced to empty string.

    Returns:
        Title-cased name with particles kept lowercase (unless the entire
        name is a single particle token) and hyphenated compounds capitalized
        per sub-token. Empty input returns ``""``.
    """
    if not isinstance(name, str):
        return ""

    stripped = name.strip()
    if not stripped:
        return ""

    tokens = stripped.split()
    sole_token = len(tokens) == 1
    return " ".join(
        _normalize_token(token, is_first=(sole_token and index == 0))
        for index, token in enumerate(tokens)
    )

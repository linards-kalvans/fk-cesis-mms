"""Pure functions for the tiny-IDP live validation harness.

CLI wiring lives in __main__.py. This module is import-safe: it does NOT
require Django to be configured.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_SUBJECTS = {"guardian", "member"}
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Fields the tiny-IDP normalizer currently maps. Anything else expected by the
# manifest but absent from the normalized result is searched for in the raw
# payload (signals normalizer gap = tech debt).
NORMALIZED_PERSON_FIELDS = {"first_name", "last_name", "personal_id"}
NORMALIZED_DOCUMENT_FIELDS = {
    "document_number",
    "issuer",
    "issuance_date",
    "expiry_date",
}
SCORABLE_FIELDS = NORMALIZED_PERSON_FIELDS | NORMALIZED_DOCUMENT_FIELDS | {
    "date_of_birth",
}
# `kind` is metadata about the document subtype, not a value to score against
# the OCR output. It exists in the manifest so we can later validate the
# normalizer's kind-classification once it is wired up.
NON_SCORABLE_KEYS = {"kind"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    """One sample document on disk."""

    path: Path
    relative_key: str  # e.g. "guardian/linards-id.jpg"
    ocr_kind: str  # "guardian_identity" | "member_identity"
    content_type: str  # "image/jpeg" | "image/png"


@dataclass
class FieldScore:
    """Per-field scoring outcome.

    outcome:
      - "hit": normalized matches expected (case-insensitive trim).
      - "miss": normalized has a value, but it does not match expected.
      - "unsupported_field": normalizer dropped it; raw payload contains the
        expected value at `raw_path`. Signals normalizer gap (tech debt).
      - "missing_everywhere": neither normalized nor raw payload contain the
        expected value.
    """

    name: str
    outcome: str
    raw_path: str | None = None


@dataclass
class SampleResult:
    """End-to-end outcome for one sample."""

    relative_key: str  # only used for grouping in render; redacted in output
    sha_prefix: str  # 12-char sha256 hex prefix
    ocr_kind: str
    provider_kind: str | None  # subtype returned by provider (if any)
    expected_kind: str
    latency_ms: int
    field_scores: list[FieldScore] = field(default_factory=list)
    error_code: str | None = None  # set if provider call raised


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def sha256_prefix(content: bytes, length: int = 12) -> str:
    """Return the first `length` hex chars of sha256(content)."""
    return hashlib.sha256(content).hexdigest()[:length]


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Parse the ground-truth YAML manifest.

    Raises:
        ValueError: If any entry is missing the required 'kind' field.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"manifest root must be a mapping, got {type(raw)}")

    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"manifest entry {key!r} must be a mapping")
        if "kind" not in value:
            raise ValueError(
                f"manifest entry {key!r} missing required field 'kind'"
            )
        out[str(key)] = {k: v for k, v in value.items()}
    return out


# ---------------------------------------------------------------------------
# Sample discovery
# ---------------------------------------------------------------------------


_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def discover_samples(samples_dir: Path) -> Iterable[Sample]:
    """Walk `samples_dir/{guardian,member}/` and yield Sample objects."""
    for subject in sorted(SUPPORTED_SUBJECTS):
        subject_dir = samples_dir / subject
        if not subject_dir.is_dir():
            continue
        for file_path in sorted(subject_dir.iterdir()):
            if not file_path.is_file():
                continue
            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            yield Sample(
                path=file_path,
                relative_key=f"{subject}/{file_path.name}",
                ocr_kind=f"{subject}_identity",
                content_type=_CONTENT_TYPES[ext],
            )


# ---------------------------------------------------------------------------
# Raw-payload field discovery
# ---------------------------------------------------------------------------


def find_value_in_raw(
    payload: Any, target_key: str, target_value: str
) -> str | None:
    """Recursively search `payload` for `target_key` whose value matches.

    Returns the dotted/indexed path to the match, or None if absent.
    Matching is case-insensitive trim.
    """
    target_norm = str(target_value).strip().casefold()
    return _walk_for_value(payload, target_key, target_norm, path="")


def _walk_for_value(
    node: Any, target_key: str, target_value_norm: str, path: str
) -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            sub_path = f"{path}.{key}" if path else str(key)
            if key == target_key and isinstance(value, (str, int, float)):
                if str(value).strip().casefold() == target_value_norm:
                    return sub_path
            found = _walk_for_value(
                value, target_key, target_value_norm, sub_path
            )
            if found:
                return found
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            sub_path = f"{path}[{idx}]"
            found = _walk_for_value(
                value, target_key, target_value_norm, sub_path
            )
            if found:
                return found
    return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _values_match(a: str, b: str) -> bool:
    return str(a).strip().casefold() == str(b).strip().casefold()


def _lookup_normalized(field_name: str, normalized: dict[str, Any]) -> str | None:
    if field_name in NORMALIZED_PERSON_FIELDS:
        value = normalized.get("person_fields", {}).get(field_name)
        return None if value is None else str(value)
    if field_name in NORMALIZED_DOCUMENT_FIELDS:
        value = normalized.get("document_metadata", {}).get(field_name)
        return None if value is None else str(value)
    return None


@dataclass
class _ScoreCarrier:
    """Internal — `score_sample` returns SampleResult directly; this exists
    only for type clarity if we ever need to surface intermediate state."""


def score_sample(
    *,
    expected: dict[str, Any],
    normalized: dict[str, Any],
    raw_payload: dict[str, Any],
) -> SampleResult:
    """Compare manifest expectations against extraction output.

    `normalized` is a dict view of an OCRExtractionResult (caller converts).
    `raw_payload` is the dict returned by `post_document`.

    Returns a SampleResult with field_scores populated. SHA prefix, latency,
    kinds, error_code, relative_key are caller-populated afterward.
    """
    scores: list[FieldScore] = []

    for field_name, expected_value in expected.items():
        if field_name in NON_SCORABLE_KEYS:
            continue
        if field_name not in SCORABLE_FIELDS:
            # Manifest declares something we never expected — flag explicitly.
            scores.append(
                FieldScore(name=field_name, outcome="missing_everywhere")
            )
            continue

        expected_str = str(expected_value)
        norm_value = _lookup_normalized(field_name, normalized)

        if norm_value is not None:
            if _values_match(norm_value, expected_str):
                scores.append(FieldScore(name=field_name, outcome="hit"))
            else:
                scores.append(FieldScore(name=field_name, outcome="miss"))
            continue

        # Not in normalized — does raw contain it?
        raw_path = find_value_in_raw(raw_payload, field_name, expected_str)
        if raw_path:
            scores.append(
                FieldScore(
                    name=field_name,
                    outcome="unsupported_field",
                    raw_path=raw_path,
                )
            )
        else:
            scores.append(
                FieldScore(name=field_name, outcome="missing_everywhere")
            )

    # Stable order for report rendering.
    scores.sort(key=lambda s: s.name)
    return SampleResult(
        relative_key="",  # filled by caller
        sha_prefix="",  # filled by caller
        ocr_kind="",  # filled by caller
        provider_kind=None,
        expected_kind=str(expected.get("kind", "")),
        latency_ms=0,  # filled by caller
        field_scores=scores,
    )


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def redact_personal_id(value: str) -> str:
    """Latvian personal ID DDMMYY-XXXXX → keep date prefix only."""
    if not value:
        return ""
    if len(value) >= 7 and value[6] == "-" and value[:6].isdigit():
        return f"{value[:6]}-*****"
    return "***redacted***"


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_report(
    *,
    samples: list[SampleResult],
    negative_case_outcome: str,
    provider_host: str,
) -> str:
    """Render a redacted markdown report.

    Contains:
      - SHA prefix + kind per sample (never filename, never field values)
      - Per-field outcome (hit/miss/unsupported_field/missing_everywhere)
      - Latency, error_code, expected_kind vs provider_kind
      - Negative-case outcome (auth_failed expected)
      - Provider host (no API key, no full URL)
    """
    lines: list[str] = []
    lines.append("# P3 tiny-IDP live validation evidence")
    lines.append("")
    lines.append(f"Provider host: `{provider_host}`")
    lines.append(f"Negative-case (bad token) outcome: `{negative_case_outcome}`")
    lines.append("")
    lines.append(f"Samples processed: {len(samples)}")
    lines.append("")

    for i, sample in enumerate(samples, start=1):
        lines.append(f"## Sample {i}: `{sample.sha_prefix}` ({sample.ocr_kind})")
        lines.append("")
        lines.append(f"- expected kind: `{sample.expected_kind}`")
        lines.append(f"- provider kind: `{sample.provider_kind or '—'}`")
        lines.append(f"- latency: {sample.latency_ms} ms")
        if sample.error_code:
            lines.append(f"- error_code: `{sample.error_code}`")
        lines.append("")
        if sample.field_scores:
            lines.append("| Field | Outcome | Raw path (if dropped by normalizer) |")
            lines.append("|---|---|---|")
            for score in sample.field_scores:
                raw_col = f"`{score.raw_path}`" if score.raw_path else "—"
                lines.append(
                    f"| `{score.name}` | `{score.outcome}` | {raw_col} |"
                )
        lines.append("")

    return "\n".join(lines) + "\n"

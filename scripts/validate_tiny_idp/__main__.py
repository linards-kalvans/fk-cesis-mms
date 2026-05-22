"""CLI entrypoint for the tiny-IDP live validation harness.

Usage:
    uv run python -m scripts.validate_tiny_idp \
        --samples-dir tmp/tiny_idp_samples \
        --manifest   tmp/tiny_idp_samples/expected.yaml \
        --report     docs/p3_tiny_idp_validation.md

Defaults match the project layout, so the common case is just:
    uv run python -m scripts.validate_tiny_idp

The script:
  1. Bootstraps Django (settings only, no DB writes).
  2. Walks `samples_dir/{guardian,member}/` for .jpg/.jpeg/.png files.
  3. For each sample, calls tiny_idp.post_document() (raw) and
     normalize_tiny_idp_response() (normalized).
  4. Scores fields against the manifest using scripts.validate_tiny_idp.
  5. Runs a negative-case check: deliberately invalid auth -> expects
     auth_failed mapping.
  6. Writes a redacted markdown evidence report.

Exits non-zero if any sample raises an unexpected error, the manifest is
malformed, or the negative case does NOT classify as auth_failed.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


def _bootstrap_django() -> None:
    """Configure Django from .env so we can read tiny-IDP settings."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fk_cesis_mms.settings")
    import django

    django.setup()


def _normalized_to_dict(result) -> dict:
    """Convert OCRExtractionResult dataclass into the dict shape score_sample expects."""
    return {
        "person_fields": dict(result.person_fields),
        "document_metadata": dict(result.document_metadata),
        "confidence": dict(result.confidence),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_tiny_idp")
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=Path("tmp/tiny_idp_samples"),
        help="Root dir containing guardian/ and member/ sample subdirs.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tmp/tiny_idp_samples/expected.yaml"),
        help="YAML ground-truth manifest path.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/p3_tiny_idp_validation.md"),
        help="Markdown report output path.",
    )
    args = parser.parse_args(argv)

    _bootstrap_django()

    from django.conf import settings

    from apps.integrations import tiny_idp
    from apps.integrations.ocr import _classify_exception  # type: ignore[attr-defined]
    from scripts.validate_tiny_idp import (
        FieldScore,
        SampleResult,
        discover_samples,
        load_manifest,
        render_report,
        score_sample,
        sha256_prefix,
    )

    # Validate config up front so we fail fast with a clear message.
    try:
        tiny_idp.validate_tiny_idp_config()
    except tiny_idp.ProviderMisconfigurationError as exc:
        print(f"ERROR: tiny-IDP misconfigured: {exc}", file=sys.stderr)
        return 2

    provider_host = urlparse(settings.TINY_IDP_API_URL).hostname or "unknown"

    manifest = load_manifest(args.manifest)
    samples = list(discover_samples(args.samples_dir))
    if not samples:
        print(
            f"ERROR: no samples found under {args.samples_dir}/guardian or /member",
            file=sys.stderr,
        )
        return 2

    sample_results: list[SampleResult] = []

    for sample in samples:
        content = sample.path.read_bytes()
        sha_prefix = sha256_prefix(content)
        expected = manifest.get(sample.relative_key)

        start = time.monotonic()
        raw_payload: dict | None = None
        normalized_dict: dict | None = None
        error_code: str | None = None
        try:
            raw_payload = tiny_idp.post_document(
                file_name=sample.path.name,
                content=content,
                content_type=sample.content_type,
            )
            normalized = tiny_idp.normalize_tiny_idp_response(
                sample.ocr_kind, raw_payload
            )
            normalized_dict = _normalized_to_dict(normalized)
        except Exception as exc:  # noqa: BLE001 - script-level catch-all is fine
            error_code = _classify_exception(exc)

        latency_ms = int((time.monotonic() - start) * 1000)

        if expected is None:
            # Sample on disk has no manifest entry; record skeleton row.
            sample_results.append(
                SampleResult(
                    relative_key=sample.relative_key,
                    sha_prefix=sha_prefix,
                    ocr_kind=sample.ocr_kind,
                    provider_kind=(raw_payload or {}).get("document", {}).get("kind"),
                    expected_kind="-",
                    latency_ms=latency_ms,
                    field_scores=[
                        FieldScore(
                            name="(no manifest entry)",
                            outcome="missing_everywhere",
                        )
                    ],
                    error_code=error_code,
                )
            )
            continue

        if error_code is not None:
            sample_results.append(
                SampleResult(
                    relative_key=sample.relative_key,
                    sha_prefix=sha_prefix,
                    ocr_kind=sample.ocr_kind,
                    provider_kind=None,
                    expected_kind=str(expected.get("kind", "")),
                    latency_ms=latency_ms,
                    field_scores=[],
                    error_code=error_code,
                )
            )
            continue

        assert raw_payload is not None
        assert normalized_dict is not None

        result = score_sample(
            expected=expected,
            normalized=normalized_dict,
            raw_payload=raw_payload,
        )
        result.relative_key = sample.relative_key
        result.sha_prefix = sha_prefix
        result.ocr_kind = sample.ocr_kind
        result.provider_kind = (raw_payload.get("document", {}) or {}).get("kind")
        result.latency_ms = latency_ms
        sample_results.append(result)

    # Negative case: deliberately wrong key -> expect auth_failed.
    negative_outcome = _run_negative_case(tiny_idp, _classify_exception)

    report = render_report(
        samples=sample_results,
        negative_case_outcome=negative_outcome,
        provider_host=provider_host,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(f"Report written to {args.report}")

    # Surface concise console summary.
    for s in sample_results:
        summary = {
            sc.outcome: sum(1 for x in s.field_scores if x.outcome == sc.outcome)
            for sc in s.field_scores
        }
        print(
            f"  {s.sha_prefix} ({s.ocr_kind}): "
            f"latency={s.latency_ms}ms error={s.error_code or '-'} "
            f"counts={summary}"
        )

    if negative_outcome != "auth_failed":
        print(
            f"WARNING: negative case mapped to {negative_outcome!r}, expected 'auth_failed'",
            file=sys.stderr,
        )
        return 3

    return 0


def _run_negative_case(
    tiny_idp_module, classify: Callable[[Exception], str]
) -> str:
    """Call tiny-IDP with a deliberately invalid token; expect auth_failed.

    Returns the classified error code (or 'unexpected_success' if it somehow
    didn't raise).
    """
    from django.conf import settings as dj_settings

    real_key = getattr(dj_settings, "TINY_IDP_API_KEY", "")
    dj_settings.TINY_IDP_API_KEY = "definitely-not-a-real-key"  # type: ignore[misc]
    try:
        try:
            tiny_idp_module.post_document(
                file_name="negative.jpg",
                content=b"x",
                content_type="image/jpeg",
            )
            return "unexpected_success"
        except Exception as exc:  # noqa: BLE001
            return classify(exc)
    finally:
        dj_settings.TINY_IDP_API_KEY = real_key  # type: ignore[misc]


if __name__ == "__main__":
    raise SystemExit(main())

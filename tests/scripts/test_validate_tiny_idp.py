"""Unit tests for scripts.validate_tiny_idp pure functions."""

from __future__ import annotations

import pytest

from scripts.validate_tiny_idp import (
    FieldScore,
    SampleResult,
    discover_samples,
    find_value_in_raw,
    load_manifest,
    redact_personal_id,
    render_report,
    score_sample,
    sha256_prefix,
)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_sha256_prefix_returns_first_12_lowercase_hex_chars():
    # sha256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
    assert sha256_prefix(b"abc") == "ba7816bf8f01"


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


def test_load_manifest_returns_per_file_expectations(tmp_path):
    manifest = tmp_path / "expected.yaml"
    manifest.write_text(
        "guardian/a.jpg:\n"
        "  kind: id_card\n"
        "  first_name: \"Anna\"\n"
        "  date_of_birth: \"1980-01-01\"\n"
        "member/b.jpg:\n"
        "  kind: passport\n"
        "  document_number: \"LV1234567\"\n",
        encoding="utf-8",
    )
    parsed = load_manifest(manifest)
    assert parsed == {
        "guardian/a.jpg": {
            "kind": "id_card",
            "first_name": "Anna",
            "date_of_birth": "1980-01-01",
        },
        "member/b.jpg": {
            "kind": "passport",
            "document_number": "LV1234567",
        },
    }


def test_load_manifest_rejects_missing_kind(tmp_path):
    manifest = tmp_path / "expected.yaml"
    manifest.write_text(
        "guardian/a.jpg:\n  first_name: Anna\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required field 'kind'"):
        load_manifest(manifest)


# ---------------------------------------------------------------------------
# Sample discovery
# ---------------------------------------------------------------------------


def test_discover_samples_walks_guardian_and_member_subdirs(tmp_path):
    (tmp_path / "guardian").mkdir()
    (tmp_path / "member").mkdir()
    (tmp_path / "guardian" / "a.jpg").write_bytes(b"a")
    (tmp_path / "guardian" / "b.png").write_bytes(b"b")
    (tmp_path / "member" / "c.jpeg").write_bytes(b"c")
    (tmp_path / "member" / "ignore.txt").write_text("nope")

    samples = sorted(discover_samples(tmp_path), key=lambda s: s.relative_key)
    assert [s.relative_key for s in samples] == [
        "guardian/a.jpg",
        "guardian/b.png",
        "member/c.jpeg",
    ]
    assert samples[0].ocr_kind == "guardian_identity"
    assert samples[2].ocr_kind == "member_identity"
    assert samples[0].content_type == "image/jpeg"
    assert samples[1].content_type == "image/png"


# ---------------------------------------------------------------------------
# Raw-payload field discovery (for fields the normalizer drops)
# ---------------------------------------------------------------------------


def test_find_value_in_raw_searches_nested_dicts_and_lists():
    payload = {
        "entities": [
            {
                "type": "person",
                "fields": {"date_of_birth": "1980-01-01"},
            }
        ]
    }
    found = find_value_in_raw(payload, "date_of_birth", "1980-01-01")
    assert found == "entities[0].fields.date_of_birth"


def test_find_value_in_raw_returns_none_when_absent():
    payload = {"entities": []}
    assert find_value_in_raw(payload, "date_of_birth", "1980-01-01") is None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _normalized_fixture():
    return {
        "person_fields": {
            "first_name": "Anna",
            "last_name": "Bērziņa",
            "personal_id": "010180-12345",
        },
        "document_metadata": {
            "document_number": "LV1234567",
            "expiry_date": "2030-05-21",
        },
        "confidence": {"first_name": 0.99},
    }


def _raw_fixture():
    return {
        "entities": [
            {
                "type": "person",
                "fields": {
                    "first_name": "Anna",
                    "last_name": "Bērziņa",
                    "personal_id": "010180-12345",
                    "date_of_birth": "1980-01-01",
                },
            }
        ],
        "document": {
            "document_number": "LV1234567",
            "expiry_date": "2030-05-21",
        },
    }


def test_score_sample_marks_hits_misses_and_unsupported_fields():
    expected = {
        "kind": "id_card",
        "first_name": "Anna",
        "last_name": "WRONG",  # miss
        "personal_id": "010180-12345",
        "document_number": "LV1234567",
        "expiry_date": "2030-05-21",
        "date_of_birth": "1980-01-01",  # not in normalizer, but in raw
        "issuer": "PMLP",  # not in normalizer, not in raw
    }
    result = score_sample(
        expected=expected,
        normalized=_normalized_fixture(),
        raw_payload=_raw_fixture(),
    )

    by_field = {f.name: f for f in result.field_scores}
    assert by_field["first_name"].outcome == "hit"
    assert by_field["last_name"].outcome == "miss"
    assert by_field["personal_id"].outcome == "hit"
    assert by_field["document_number"].outcome == "hit"
    assert by_field["expiry_date"].outcome == "hit"
    # date_of_birth: normalizer drops it, raw has it → unsupported_field
    assert by_field["date_of_birth"].outcome == "unsupported_field"
    assert by_field["date_of_birth"].raw_path == "entities[0].fields.date_of_birth"
    # issuer: nowhere → missing_everywhere
    assert by_field["issuer"].outcome == "missing_everywhere"


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redact_personal_id_keeps_birth_century_only():
    # Latvian personal ID format DDMMYY-XXXXX → keep "DDMMYY-" + "*****"
    assert redact_personal_id("171280-11288") == "171280-*****"


def test_redact_personal_id_handles_short_or_unexpected_input():
    assert redact_personal_id("") == ""
    assert redact_personal_id("not-an-id") == "***redacted***"


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def test_render_report_is_markdown_and_contains_no_pii():
    sample = SampleResult(
        relative_key="guardian/a.jpg",
        sha_prefix="abcdef012345",
        ocr_kind="guardian_identity",
        provider_kind="id_card",
        expected_kind="id_card",
        latency_ms=843,
        field_scores=[
            FieldScore(name="first_name", outcome="hit"),
            FieldScore(name="last_name", outcome="miss"),
            FieldScore(
                name="date_of_birth",
                outcome="unsupported_field",
                raw_path="entities[0].fields.date_of_birth",
            ),
        ],
        error_code=None,
    )

    markdown = render_report(
        samples=[sample],
        negative_case_outcome="auth_failed",
        provider_host="tiny-idp.example.com",
    )

    assert markdown.startswith("# P3 tiny-IDP live validation evidence")
    assert "abcdef012345" in markdown  # sha prefix
    assert "guardian/a.jpg" not in markdown  # filename never in report
    assert "first_name" in markdown
    assert "hit" in markdown and "miss" in markdown
    assert "unsupported_field" in markdown
    assert "auth_failed" in markdown
    # Negative-control assertions — no PII leaks:
    assert "Anna" not in markdown
    assert "Bērziņa" not in markdown
    assert "171280" not in markdown
    assert "LV1234567" not in markdown

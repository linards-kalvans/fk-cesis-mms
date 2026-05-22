# P3 tiny-IDP Live Validation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone validation script that runs the real tiny-IDP provider against local sample documents, scores extracted fields against a ground-truth manifest (including provider-returned fields the normalizer currently drops, like `date_of_birth`), and writes a redacted evidence report committable to the repo. This produces the missing artifact for P3 sign-off.

**Architecture:**
- The harness is a standalone Python package (`scripts/validate_tiny_idp/`) — not a Django management command — because it is a dev/QA tool that admins never run. It performs minimal Django bootstrap (`django.setup()`) only to read `TINY_IDP_API_URL` / `TINY_IDP_API_KEY` / `OCR_ENCRYPTION_KEY` from settings.
- A small refactor in `apps/integrations/tiny_idp.py` splits `extract_document()` into two functions: `post_document()` (HTTP + raw JSON) and the existing `normalize_tiny_idp_response()` (normalization). The harness uses both so it can score raw provider output (e.g. `date_of_birth`) the normalizer currently drops.
- Pure functions (manifest loading, hashing, scoring, redaction, report rendering) live in `scripts/validate_tiny_idp/__init__.py` and are unit-tested. CLI wiring lives in `scripts/validate_tiny_idp/__main__.py`.
- Real sample documents stay in gitignored `tmp/tiny_idp_samples/`; only the redacted report `docs/p3_tiny_idp_validation.md` is committed.

**Tech Stack:** Python 3.12, Django 5.x settings, `requests`, `PyYAML`, `pytest` (with `pytest-django`), `ruff`, `mypy`, `uv`.

---

## File Structure

**Modify:**
- `apps/integrations/tiny_idp.py` — extract HTTP-and-decode into `post_document()`; `extract_document()` becomes a thin wrapper that calls `post_document()` + `normalize_tiny_idp_response()`. No behavior change for callers.
- `pyproject.toml` — add `pyyaml` dep via `uv add pyyaml`.

**Create:**
- `scripts/__init__.py` — empty marker so `scripts.validate_tiny_idp` is importable.
- `scripts/validate_tiny_idp/__init__.py` — pure functions: data classes, manifest loader, file walker, scoring, redaction, report renderer.
- `scripts/validate_tiny_idp/__main__.py` — CLI entry: argparse, `django.setup()`, walks samples, calls `post_document()` and `normalize_tiny_idp_response()`, runs negative auth test, writes report.
- `tests/integrations/test_tiny_idp_post_document.py` — TDD coverage for the new `post_document()` split.
- `tests/scripts/__init__.py` — empty marker.
- `tests/scripts/test_validate_tiny_idp.py` — unit tests for the pure functions in the harness.
- `docs/p3_tiny_idp_validation.md` — redacted evidence report (final artifact, written by running the harness).

**Already in place (do not recreate):**
- `tmp/tiny_idp_samples/guardian/linards-id.jpg`, `tmp/tiny_idp_samples/guardian/linards-passport.jpg`, `tmp/tiny_idp_samples/member/eid-karte.jpg`.
- `tmp/tiny_idp_samples/expected.yaml` (ground-truth manifest, user-filled).
- `tmp/tiny_idp_samples/README.md`.
- `.gitignore` already covers `/tmp/`.

---

## Conventions Reminder for the Implementer

- Always run Python via `uv run …` — never `python` or `pip` directly.
- This project uses **TDD**: every functional task writes a failing test first, then implements, then verifies the test passes.
- After every task: stage only files touched in that task; commit with a Conventional-Commits-style message (`feat:`, `refactor:`, `chore:`, `test:`, `docs:`).
- Do NOT modify test files in implementation steps; do NOT modify production code in test steps.
- Never commit anything under `tmp/`. Verify with `git status` before committing.

---

## Task 1: Refactor tiny-IDP transport to expose raw payload

**Files:**
- Modify: `apps/integrations/tiny_idp.py:95-147` — split `extract_document` into `post_document` + `extract_document`.
- Test: `tests/integrations/test_tiny_idp_post_document.py` (new).

**Why:** The validation harness must score fields the normalizer drops (e.g. `date_of_birth`). It needs access to the raw JSON tiny-IDP returns, not just the normalized `OCRExtractionResult`. Splitting `extract_document` into `post_document` (HTTP + decode → `dict`) and the existing normalizer keeps the public `extract_document` API and behavior identical while exposing the raw payload.

- [ ] **Step 1: Write the failing test**

Create `tests/integrations/test_tiny_idp_post_document.py`:

```python
"""Unit tests for the tiny-IDP HTTP-only transport split (post_document)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.integrations.tiny_idp import (
    AuthError,
    InvalidResponseError,
    ProviderMisconfigurationError,
    ProviderUnavailableError,
    RateLimitError,
    RequestTimeoutError,
    post_document,
)


_SAMPLE_PAYLOAD = {
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
        "issuer": "PMLP",
        "issuance_date": "2020-05-21",
        "expiry_date": "2030-05-21",
    },
    "confidence": {"first_name": 0.99},
    "flags": [],
    "model_version": "tinyidp-1.0.0",
}


@pytest.fixture
def tiny_idp_settings(settings):
    settings.TINY_IDP_API_URL = "https://tiny-idp.test/extract"
    settings.TINY_IDP_API_KEY = "test-key"
    return settings


def test_post_document_returns_raw_payload(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _SAMPLE_PAYLOAD
    mock_response.raise_for_status = MagicMock()

    captured = {}

    def fake_post(url, files=None, headers=None, **kwargs):
        captured["url"] = url
        captured["files"] = files
        captured["headers"] = headers
        return mock_response

    monkeypatch.setattr("apps.integrations.tiny_idp.requests.post", fake_post)

    payload = post_document(
        file_name="doc.jpg",
        content=b"binary-content",
        content_type="image/jpeg",
    )

    assert payload == _SAMPLE_PAYLOAD
    assert captured["url"] == "https://tiny-idp.test/extract"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["files"]["file"][0] == "doc.jpg"
    assert captured["files"]["file"][1] == b"binary-content"
    assert captured["files"]["file"][2] == "image/jpeg"


def test_post_document_raises_misconfig_when_url_missing(settings, monkeypatch):
    monkeypatch.delattr("django.conf.settings._wrapped", raising=False)
    settings.TINY_IDP_API_URL = ""
    settings.TINY_IDP_API_KEY = "key"

    with pytest.raises(ProviderMisconfigurationError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_auth_error(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = Exception("401 unauthorized")

    monkeypatch.setattr(
        "apps.integrations.tiny_idp.requests.post",
        lambda *a, **kw: mock_response,
    )

    with pytest.raises(AuthError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_rate_limit(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = Exception("429 rate limited")

    monkeypatch.setattr(
        "apps.integrations.tiny_idp.requests.post",
        lambda *a, **kw: mock_response,
    )

    with pytest.raises(RateLimitError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_timeout(tiny_idp_settings, monkeypatch):
    def raise_timeout(*a, **kw):
        raise OSError("connection timed out")

    monkeypatch.setattr("apps.integrations.tiny_idp.requests.post", raise_timeout)

    with pytest.raises(RequestTimeoutError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_unavailable(tiny_idp_settings, monkeypatch):
    def raise_conn(*a, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr("apps.integrations.tiny_idp.requests.post", raise_conn)

    with pytest.raises(ProviderUnavailableError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_invalid_response(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.side_effect = ValueError("not json")

    monkeypatch.setattr(
        "apps.integrations.tiny_idp.requests.post",
        lambda *a, **kw: mock_response,
    )

    with pytest.raises(InvalidResponseError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integrations/test_tiny_idp_post_document.py -v`
Expected: import error / `ImportError: cannot import name 'post_document'` (function not yet defined).

- [ ] **Step 3: Refactor `tiny_idp.py` to add `post_document` and reuse it from `extract_document`**

Replace `apps/integrations/tiny_idp.py` lines 95-147 (the current `extract_document` function and its docstring) with:

```python
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
        return resp.json()
    except ValueError as exc:
        raise InvalidResponseError(
            f"Malformed JSON response: {exc}"
        ) from exc


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
```

- [ ] **Step 4: Run the new test plus existing tiny-IDP tests to verify all pass**

Run: `uv run pytest tests/integrations/test_tiny_idp_post_document.py tests/integrations/test_tiny_idp_runtime.py tests/integrations/test_tiny_idp_adapter.py -v`
Expected: all PASS (new `post_document` tests pass, existing `extract_document` behavior unchanged).

- [ ] **Step 5: Run full suite + lint + typecheck to confirm no regression**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: `584 passed` (or `591 passed` with the 7 new tests), ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add apps/integrations/tiny_idp.py tests/integrations/test_tiny_idp_post_document.py
git commit -m "refactor(tiny-idp): split extract_document into post_document + normalize for harness use"
```

---

## Task 2: Add `pyyaml` dependency for ground-truth manifest parsing

**Files:**
- Modify: `pyproject.toml` (via `uv add`).
- Modify: `uv.lock` (auto-generated).

- [ ] **Step 1: Add the dep with `uv`**

Run: `uv add pyyaml`
Expected: pyproject.toml updated with `pyyaml = "^6.0.X"` (or similar) and `uv.lock` regenerated.

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "import yaml; print(yaml.__version__)"`
Expected: prints a version string like `6.0.2`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add pyyaml for tiny-IDP validation harness manifest parsing"
```

---

## Task 3: Pure-function module for the harness (data, manifest, scoring, redaction, report)

**Files:**
- Create: `scripts/__init__.py` (empty).
- Create: `scripts/validate_tiny_idp/__init__.py`.
- Create: `tests/scripts/__init__.py` (empty).
- Create: `tests/scripts/test_validate_tiny_idp.py`.

**Why:** Keeping logic in pure functions makes the harness unit-testable without HTTP or real document files. CLI wiring (Task 4) becomes a thin shell around these.

- [ ] **Step 1: Create empty package markers**

Create `scripts/__init__.py` with content:
```python
```
(an empty file — the absence of newlines is fine; just create it as 0 bytes).

Create `tests/scripts/__init__.py` with the same empty content.

- [ ] **Step 2: Write the failing tests**

Create `tests/scripts/test_validate_tiny_idp.py`:

```python
"""Unit tests for scripts.validate_tiny_idp pure functions."""

from __future__ import annotations

from pathlib import Path

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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/scripts/test_validate_tiny_idp.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.validate_tiny_idp'` (target module doesn't exist yet).

- [ ] **Step 4: Implement the pure-function module**

Create `scripts/validate_tiny_idp/__init__.py` with:

```python
"""Pure functions for the tiny-IDP live validation harness.

CLI wiring lives in __main__.py. This module is import-safe: it does NOT
require Django to be configured.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


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
        return normalized.get("person_fields", {}).get(field_name)
    if field_name in NORMALIZED_DOCUMENT_FIELDS:
        return normalized.get("document_metadata", {}).get(field_name)
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/scripts/test_validate_tiny_idp.py -v`
Expected: all 11 tests PASS.

- [ ] **Step 6: Lint + typecheck**

Run: `uv run ruff check scripts/ tests/scripts/ && uv run mypy scripts/`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/__init__.py scripts/validate_tiny_idp/__init__.py tests/scripts/__init__.py tests/scripts/test_validate_tiny_idp.py
git commit -m "feat(validation): add pure-function module for tiny-IDP live validation harness"
```

---

## Task 4: CLI entrypoint — wires the harness to Django settings and disk

**Files:**
- Create: `scripts/validate_tiny_idp/__main__.py`.

**Note:** No unit tests for the CLI itself — it is a thin orchestrator. Its correctness is validated by the live run in Task 5. All scorable logic is already covered by Task 3's unit tests.

- [ ] **Step 1: Implement the CLI module**

Create `scripts/validate_tiny_idp/__main__.py`:

```python
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
  5. Runs a negative-case check: deliberately invalid auth → expects
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
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlparse


def _bootstrap_django() -> None:
    """Configure Django from .env so we can read tiny-IDP settings."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
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
    from apps.integrations.ocr import _classify_exception
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
        except Exception as exc:  # noqa: BLE001 — script-level catch-all is fine
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
                    expected_kind="—",
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

    # Negative case: deliberately wrong key → expect auth_failed.
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
            f"latency={s.latency_ms}ms error={s.error_code or '—'} "
            f"counts={summary}"
        )

    if negative_outcome != "auth_failed":
        print(
            f"WARNING: negative case mapped to {negative_outcome!r}, expected 'auth_failed'",
            file=sys.stderr,
        )
        return 3

    return 0


def _run_negative_case(tiny_idp_module, classify) -> str:
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
```

- [ ] **Step 2: Run lint + typecheck**

Run: `uv run ruff check scripts/ && uv run mypy scripts/`
Expected: clean. If mypy complains about `_classify_exception` being private, suppress with `# type: ignore[attr-defined]` on that import line — acceptable trade-off for a dev-only script reusing existing logic.

- [ ] **Step 3: Smoke-test the CLI's argparse without hitting the network**

Run: `uv run python -m scripts.validate_tiny_idp --help`
Expected: usage text printed, exit 0.

- [ ] **Step 4: Commit**

```bash
git add scripts/validate_tiny_idp/__main__.py
git commit -m "feat(validation): add CLI entrypoint for tiny-IDP live validation harness"
```

---

## Task 5: Execute the live run and commit the evidence report

**Files:**
- Read: `tmp/tiny_idp_samples/` (gitignored, user-provided).
- Create: `docs/p3_tiny_idp_validation.md` (committed).
- Modify: `docs/milestones.md` — flip P3 from "implementation landed, validation pending" → "P3 signed off".
- Modify: `AGENTS.md` — update P3 Current Status to reflect validation complete.

**Pre-flight check before running:** the operator confirms `.env` has live `TINY_IDP_API_URL`, `TINY_IDP_API_KEY`, and `OCR_ENCRYPTION_KEY` set, and that the host is reachable from this machine. If the script exits non-zero on a real auth failure, stop and surface the result to the user — credential rotation may be the root cause and is a legitimate finding for the report itself.

- [ ] **Step 1: Verify samples and manifest are in place**

Run:
```bash
ls tmp/tiny_idp_samples/guardian/ tmp/tiny_idp_samples/member/
cat tmp/tiny_idp_samples/expected.yaml | head -10
```
Expected: at least 3 image files listed, manifest parses visually.

- [ ] **Step 2: Run the harness**

Run: `uv run python -m scripts.validate_tiny_idp`
Expected:
- Console: per-sample line with sha-prefix, kind, latency, error code, outcome counts.
- File: `docs/p3_tiny_idp_validation.md` written.
- Exit code 0 (negative case mapped to `auth_failed`).

If exit is non-zero, capture stderr and pause — do not commit a partial report. Report findings to the user.

- [ ] **Step 3: Inspect the report for PII leaks before committing**

Run:
```bash
grep -iE "(Linards|Kalvāns|Māra|Paraudziņa|171280|321251|PA2061862|PA9921450|LV7121213)" docs/p3_tiny_idp_validation.md && echo "PII FOUND — DO NOT COMMIT" || echo "OK — report is redacted"
```
Expected: `OK — report is redacted`. If PII is found, fix `render_report` in `scripts/validate_tiny_idp/__init__.py`, re-run the harness, re-check. Do not commit until the grep returns `OK`.

- [ ] **Step 4: Verify nothing under tmp/ was accidentally staged**

Run: `git status --porcelain | grep -E "^A.*tmp/" && echo "STAGED tmp FILES — DO NOT COMMIT" || echo "OK — tmp/ untouched"`
Expected: `OK — tmp/ untouched`. If anything under `tmp/` was staged, `git restore --staged tmp/...` before continuing.

- [ ] **Step 5: Update milestone tracker**

Open `docs/milestones.md`, find the P3 section, and edit it so:
- The P3 status flag changes from "implementation landed, validation pending" (or equivalent wording — read the current state first) to "Complete — live validation evidence in `docs/p3_tiny_idp_validation.md`".
- Add a note: `date_of_birth normalization tracked as tech debt in AGENTS.md (Task 6 follow-up debt)`.

Show the diff before committing — do not reword unrelated sections.

- [ ] **Step 6: Update AGENTS.md P3 status**

In `AGENTS.md`, update the line that currently reads `Live sample-document validation is still required before final implementation sign-off.` (in the `### P3 delivered` section) to:

```
- Live sample-document validation evidence captured in `docs/p3_tiny_idp_validation.md` (run via `uv run python -m scripts.validate_tiny_idp`). P3 signed off.
```

Also update the `Run real tiny-IDP sample-document validation and capture evidence before calling P3 fully signed off.` bullet in `### Task 6 follow-up debt` — remove it, since it is now done.

- [ ] **Step 7: Final verification**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all green. Test count should now be `584 + 7 (post_document) + 11 (harness pure funcs) = 602 passed` (approximate — accept the actual number as long as everything passes).

- [ ] **Step 8: Commit the evidence and docs updates**

```bash
git add docs/p3_tiny_idp_validation.md docs/milestones.md AGENTS.md
git commit -m "docs(p3): capture tiny-IDP live validation evidence and sign off P3"
```

---

## Self-Review Notes (post-write)

- Spec coverage:
  - Standalone script (not management command) ✓ — Tasks 3+4.
  - Raw-payload capture for `date_of_birth` scoring ✓ — Task 1 split + Task 3 `find_value_in_raw` + `score_sample` `unsupported_field` outcome.
  - Negative auth-failure case ✓ — Task 4 `_run_negative_case`.
  - Redacted committable report at `docs/p3_tiny_idp_validation.md` ✓ — Task 3 `render_report` + Task 5 redaction grep gate.
  - `date_of_birth` tech debt entry already landed in AGENTS.md (before this plan).
- Placeholder scan: no TBDs, every code step contains real code; every command has expected output.
- Type consistency: `SampleResult`, `FieldScore`, `Sample`, `score_sample`, `render_report`, `discover_samples`, `load_manifest`, `find_value_in_raw`, `sha256_prefix`, `redact_personal_id`, `post_document` — names match across tasks.
- Risk: `_classify_exception` is a private symbol in `apps.integrations.ocr`. Task 4 imports it. If a future change makes it strictly private (rename to `__classify_exception` or move it), the harness breaks. Acceptable for now — it's a script, not a library; if it breaks, fix it then.

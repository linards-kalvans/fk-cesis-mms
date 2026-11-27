"""Production local agreement renderer contract (Task 1).

The renderer is exercised with synthetic snapshots only.  No network access,
provider call, model row or shadow artifact is involved.
"""

from __future__ import annotations

import hashlib
import re
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

TEMPLATE_VERSION = "v1-2026-11"
SHADOW_TEMPLATE_VERSION = "shadow-v1-2026-11"

FIELD_NAMES = (
    "agreement_number",
    "child_name",
    "child_personal_id",
    "child_birth_date",
    "child_address",
    "guardian_name",
    "guardian_personal_id",
    "guardian_address",
    "guardian_email",
    "guardian_phone",
)


def _snapshot(path="paper", **overrides):
    fields = {
        "agreement_number": "FKC-2026-123",
        "child_name": "Jānis Bērziņš",
        "child_personal_id": "151210-22222",
        "child_birth_date": "10.12.2015",
        "child_address": "Rīgas iela 1, Cēsis",
        "guardian_name": "Anna Bērziņa",
        "guardian_personal_id": "111111-11111",
        "guardian_address": "Jāņa Poruka iela 8, Cēsis",
        "guardian_email": "anna@example.test",
        "guardian_phone": "+37120000000",
    }
    fields.update(overrides)
    return {"fields": fields, "signing_path": path}


def _render(snapshot, template_version=TEMPLATE_VERSION):
    from apps.agreements.pdf_rendering import render_agreement_pdf

    return render_agreement_pdf(snapshot, template_version=template_version)


def _text(pdf):
    import pymupdf

    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        pages = len(document)
        text = " ".join(page.get_text() for page in document)
    return " ".join(text.split()), pages


@pytest.mark.parametrize("path", ["paper", "electronic"])
def test_renders_all_frozen_fields_and_base_fee(path):
    snapshot = _snapshot(path)

    pdf = _render(snapshot)

    assert pdf.startswith(b"%PDF-")
    text, pages = _text(pdf)
    assert 1 <= pages <= 20
    for value in snapshot["fields"].values():
        assert value in text
    assert re.search(r"50(?:[.,]00)?\s*EUR", text, re.IGNORECASE)


def test_electronic_and_paper_wording_differ():
    electronic_text, _ = _text(_render(_snapshot("electronic")))
    paper_text, _ = _text(_render(_snapshot("paper")))

    electronic = electronic_text.casefold()
    paper = paper_text.casefold()
    assert "elektroniski parakstīts" in electronic
    assert "laika zīmog" in electronic
    assert "elektroniski parakstīts" not in paper
    assert "laika zīmog" not in paper
    assert "latviešu valodā" in paper
    assert "datums" in paper


@pytest.mark.parametrize("path", ["paper", "electronic"])
def test_production_output_has_no_shadow_comparison_markings(path):
    text, _ = _text(_render(_snapshot(path)))

    for marker in (
        "SALĪDZINĀŠANAI",
        "NAV DERĪGS PARAKSTĪŠANAI",
        "Salīdzināšanas paraugs",
    ):
        assert marker not in text


def test_escapes_html_and_preserves_latvian_text():
    name = "Ārija <script>alert(1)</script> Ģērķe"

    text, _ = _text(_render(_snapshot(child_name=name)))

    assert name in text
    assert "&lt;script&gt;" not in text


def test_long_values_render_within_limits():
    snapshot = _snapshot(guardian_address=("Ļoti gara adrese " * 200).strip())

    pdf = _render(snapshot)

    assert len(pdf) < 20 * 1024 * 1024
    text, pages = _text(pdf)
    assert 1 <= pages <= 20
    assert "Ļoti gara adrese" in text


def test_rejects_invalid_snapshot():
    valid = _snapshot()
    invalid_snapshots = (
        {"fields": {}, "signing_path": "paper"},
        {"fields": valid["fields"], "signing_path": "fax"},
        {
            "fields": {**valid["fields"], "child_name": 123},
            "signing_path": "paper",
        },
        {
            "fields": {**valid["fields"], "child_name": "x" * 5001},
            "signing_path": "paper",
        },
    )

    for snapshot in invalid_snapshots:
        with pytest.raises(ValueError, match="invalid_snapshot"):
            _render(snapshot)


def test_rejects_unknown_template_version():
    with pytest.raises(ValueError, match="unknown_template"):
        _render(_snapshot(), template_version="v1-2099-01")


def test_rejects_output_over_20_mib():
    oversized = b"%PDF-" + b"0" * (20 * 1024 * 1024)

    with patch("weasyprint.HTML.write_pdf", return_value=oversized):
        with pytest.raises(ValueError, match="output_limits"):
            _render(_snapshot())


def test_rejects_more_than_20_pages():
    class FakeDocument:
        page_count = 21

        def __len__(self):
            return 21

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("pymupdf.open", return_value=FakeDocument()):
        with pytest.raises(ValueError, match="output_limits"):
            _render(_snapshot())


def test_normal_render_makes_no_network_calls(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    pdf = _render(_snapshot())

    assert pdf.startswith(b"%PDF-")


def test_asset_fetcher_rejects_network_and_arbitrary_file_resources():
    from apps.agreements.pdf_rendering import AssetFetcher
    from weasyprint.urls import FatalURLFetchingError

    fetcher = AssetFetcher(set())

    for url in (
        "https://example.invalid/secret",
        "file:///etc/passwd",
        "data:text/plain,hello",
    ):
        with pytest.raises(FatalURLFetchingError):
            fetcher.fetch(url)


def test_production_provenance_records_immutable_assets():
    from apps.agreements.pdf_rendering import agreement_renderer_provenance

    provenance = agreement_renderer_provenance(TEMPLATE_VERSION)

    assert provenance["template_version"] == TEMPLATE_VERSION
    assert provenance["weasyprint"] == "70.0"
    assert isinstance(provenance["pango"], str) and provenance["pango"].strip()
    assert isinstance(provenance["harfbuzz"], str) and provenance["harfbuzz"].strip()
    assets = provenance["assets"]
    for name in (
        "v1_2026_11.html",
        "v1_2026_11.css",
        "DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf",
        "DejaVuSansMono-Bold.ttf",
        "fk-cesis-logo.png",
    ):
        assert name in assets
        assert re.fullmatch(r"[0-9a-f]{64}", assets[name])


def test_production_provenance_digests_match_on_disk_assets():
    from django.conf import settings

    from apps.agreements.pdf_rendering import agreement_renderer_provenance

    base = Path(settings.BASE_DIR)
    provenance = agreement_renderer_provenance(TEMPLATE_VERSION)
    assets = {
        "v1_2026_11.html": base / "templates/agreements/pdf/v1_2026_11.html",
        "v1_2026_11.css": base / "apps/agreements/pdf_assets/v1_2026_11.css",
    }

    for name, path in assets.items():
        assert provenance["assets"][name] == hashlib.sha256(
            path.read_bytes()
        ).hexdigest()


def test_renderer_rejects_asset_digest_drift(monkeypatch):
    from apps.agreements import pdf_rendering

    drifted = dict(pdf_rendering.PRODUCTION_ASSET_DIGESTS)
    drifted["v1_2026_11.css"] = "0" * 64
    monkeypatch.setattr(pdf_rendering, "PRODUCTION_ASSET_DIGESTS", drifted)

    with pytest.raises(RuntimeError, match="asset_digest_mismatch"):
        pdf_rendering.render_agreement_pdf(
            _snapshot(), template_version=TEMPLATE_VERSION
        )
    with pytest.raises(RuntimeError, match="asset_digest_mismatch"):
        pdf_rendering.agreement_renderer_provenance(TEMPLATE_VERSION)


def test_renderer_rejects_missing_asset(monkeypatch, tmp_path):
    from apps.agreements import pdf_rendering

    present = pdf_rendering._production_assets()

    def assets_with_missing_font():
        assets = dict(present)
        assets["DejaVuSans.ttf"] = tmp_path / "DejaVuSans.ttf"
        return assets

    monkeypatch.setattr(
        pdf_rendering, "_production_assets", assets_with_missing_font
    )

    with pytest.raises(RuntimeError, match="asset_unavailable"):
        pdf_rendering.render_agreement_pdf(
            _snapshot(), template_version=TEMPLATE_VERSION
        )
    with pytest.raises(RuntimeError, match="asset_unavailable"):
        pdf_rendering.agreement_renderer_provenance(TEMPLATE_VERSION)


def test_production_and_shadow_versions_are_distinct_and_immutable():
    from apps.agreements.pdf_rendering import (
        agreement_renderer_provenance,
        render_shadow_pdf,
        shadow_renderer_provenance,
    )

    assert (
        shadow_renderer_provenance()["template_version"]
        == SHADOW_TEMPLATE_VERSION
    )
    assert (
        agreement_renderer_provenance(TEMPLATE_VERSION)["template_version"]
        == TEMPLATE_VERSION
    )

    with pytest.raises(ValueError):
        _render(_snapshot(), template_version=SHADOW_TEMPLATE_VERSION)
    with pytest.raises(ValueError):
        render_shadow_pdf(_snapshot(), template_version=TEMPLATE_VERSION)
    with pytest.raises(ValueError):
        agreement_renderer_provenance("v1-2099-01")

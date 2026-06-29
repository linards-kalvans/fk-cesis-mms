"""Task 7 — JS static contract: building/apartment flow markers."""

from pathlib import Path


def test_address_autocomplete_js_tracks_building_for_apartments():
    js = Path("static/js/address_autocomplete.js").read_text(encoding="utf-8")

    assert "data-address-building-id" in js
    assert "data-address-building-label" in js
    assert "&building=" in js
    assert 'result.kind === "address"' in js
    assert 'result.kind === "apartment"' in js

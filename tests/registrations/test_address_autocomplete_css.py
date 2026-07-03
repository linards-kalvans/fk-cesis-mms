from pathlib import Path


CSS = Path("static/css/parent_theme.css").read_text()


def test_address_dropdown_can_escape_section_card_frame():
    assert ".fk-section-card" in CSS
    assert "overflow: visible" in CSS


def test_address_dropdown_has_overlay_styles():
    assert ".fk-address-dropdown" in CSS
    assert "position: absolute" in CSS
    assert "z-index:" in CSS
    assert "max-height:" in CSS
    assert "overflow-y: auto" in CSS

"""Reusable admin status-badge helper."""

from apps.core.admin_badges import status_badge


def test_badge_renders_span_with_level_class():
    html = str(status_badge("OK", "ok"))
    assert "fk-badge" in html
    assert "fk-badge--ok" in html
    assert "OK" in html
    assert html.startswith("<span")


def test_badge_tooltip_when_provided():
    html = str(status_badge("Neizdevās", "fail", tooltip="Kļūda X"))
    assert 'title="Kļūda X"' in html


def test_badge_no_tooltip_attr_when_absent():
    html = str(status_badge("OK", "ok"))
    assert "title=" not in html


def test_badge_unknown_level_falls_back_to_muted():
    html = str(status_badge("X", "bogus"))
    assert "fk-badge--muted" in html


def test_badge_escapes_text_and_tooltip():
    html = str(status_badge("<b>x</b>", "ok", tooltip='"<evil>"'))
    assert "<b>" not in html
    assert "&lt;b&gt;" in html
    assert "<evil>" not in html

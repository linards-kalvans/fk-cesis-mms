"""Regression tripwire for the `[hidden]` / `display` cascade conflict.

Several Hub elements (the document viewer's stages, its quick-links) are
shown/hidden by JavaScript toggling the boolean `hidden` attribute. But the
`hidden` attribute is only mapped to `display: none` by the *user-agent*
stylesheet, and any *author* `display` declaration on the same element - such
as `.viewer__stage { display: grid; }` or `.vbtn { display: inline-flex; }` -
outranks it regardless of selector specificity, because cascade *origin* is
decided before specificity. Without a global override, toggling `hidden` on
these elements does nothing visible at all: the three document stages render
stacked on top of each other and tab switching appears to do nothing.

This shipped unnoticed because every other Hub test asserts on response
*body* text, and hidden-but-not-actually-hidden content is still present in
that body - the bug is invisible to a Django test client, which never lays
out CSS or paints a page. What follows can only prove the specific guard
line is still present in the stylesheet that ships; it cannot exercise the
browser cascade and is not a substitute for looking at the rendered page.
"""

from __future__ import annotations

import re
from pathlib import Path

_HIDDEN_GUARD = re.compile(r"\[hidden\]\s*\{\s*display:\s*none\s*!important\s*;?\s*\}")

_TIP_RULE = re.compile(r"\.corr-summary__tip\s*\{(?P<body>[^}]*)\}")
_TIP_FOCUS_RULE = re.compile(
    r"\.corr-summary:focus-within\s+\.corr-summary__tip[^{]*\{[^}]*display:\s*block"
)

_SHIPPED_CSS = Path(__file__).resolve().parents[2] / "static" / "admin_hub" / "hub.css"
_MOCKUP_CSS = Path(__file__).resolve().parents[2] / "style-guide" / "admin" / "hub.css"


def _assert_tooltip_pointer_contract(css: str, stylesheet: str) -> None:
    tip_rule = _TIP_RULE.search(css)
    assert tip_rule, f"{stylesheet} must keep the .corr-summary__tip block"
    assert "pointer-events: none" in tip_rule.group("body"), (
        f"{stylesheet} must make .corr-summary__tip pointer-transparent. The tip "
        "is informational (no links), but its absolutely-positioned box can cover "
        "a neighbouring queue row's trigger and swallow that click."
    )
    assert _TIP_FOCUS_RULE.search(css), (
        f"{stylesheet} must keep the focus-within rule that displays "
        ".corr-summary__tip, so keyboard users can still read the tip."
    )


def test_shipped_hub_css_guards_the_hidden_attribute():
    """The stylesheet actually served by `{% static %}` must carry the
    `[hidden] { display: none !important; }` guard. If a future edit drops
    this rule, the viewer's tab switching silently breaks again - visibly,
    in a browser, invisibly, to every test that only reads response text."""
    css = _SHIPPED_CSS.read_text(encoding="utf-8")
    assert _HIDDEN_GUARD.search(css), (
        "static/admin_hub/hub.css must define "
        "`[hidden] { display: none !important; }` - without it, any element "
        "with its own `display` rule ignores the `hidden` attribute entirely."
    )


def test_mockup_hub_css_carries_the_same_guard():
    """`style-guide/admin/hub.css` is the reviewable mock-up meant to stay in
    sync with the shipped copy; the guard must not exist in only one of
    them."""
    css = _MOCKUP_CSS.read_text(encoding="utf-8")
    assert _HIDDEN_GUARD.search(css), (
        "style-guide/admin/hub.css is meant to stay in sync with "
        "static/admin_hub/hub.css and must carry the same [hidden] guard."
    )


def test_shipped_tooltip_is_pointer_transparent_but_stays_focus_visible():
    """The correction-summary tip must never intercept a click aimed at the
    row underneath it, while keeping its focus-within display rule so the
    same text remains available to keyboard users."""
    _assert_tooltip_pointer_contract(
        _SHIPPED_CSS.read_text(encoding="utf-8"), "static/admin_hub/hub.css"
    )


def test_mockup_tooltip_is_pointer_transparent_but_stays_focus_visible():
    """`style-guide/admin/hub.css` is kept in sync with the shipped copy, so
    it carries the same tooltip pointer contract."""
    _assert_tooltip_pointer_contract(
        _MOCKUP_CSS.read_text(encoding="utf-8"), "style-guide/admin/hub.css"
    )

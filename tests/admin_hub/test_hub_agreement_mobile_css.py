"""Static contract for the lifecycle action tables on narrow screens.

The browser acceptance run found that the two new discontinuation tables had
no horizontal scroll container: their min-content width expanded a 390 px
page to 720 CSS px. The fixed action bar also covered targets that normal
scroll-into-view placed at the bottom edge. These assertions pin the portable
CSS contract in both the shipped stylesheet and its reviewable mirror; the
real geometry is verified in the browser separately.
"""

from __future__ import annotations

from pathlib import Path

_SHIPPED_CSS = Path(__file__).resolve().parents[2] / "static" / "admin_hub" / "hub.css"
_MOCKUP_CSS = Path(__file__).resolve().parents[2] / "style-guide" / "admin" / "hub.css"

_MARKER = "/* lifecycle action tables + mobile clearance */"
_MOBILE_MEDIA = "@media (max-width: 680px)"

_DESKTOP_GEOMETRY = (
    ".lifecycle-actions .tray__body { min-width: 0; }",
    ".lifecycle-actions .tray__body > form { min-width: 0; }",
    ".lifecycle-actions [data-discontinuation-outcomes] { min-width: 0; }",
)

_TABLEWRAP_GEOMETRY = (
    "max-width: 100%;",
    "min-width: 0;",
    "overflow-x: auto;",
    "overscroll-behavior-x: contain;",
    "-webkit-overflow-scrolling: touch;",
)

_FOCUS_GEOMETRY = (
    "outline: 3px solid var(--fk-blue);",
    "outline-offset: 2px;",
)

_MOBILE_ONLY = (
    "html { scroll-padding-bottom: 220px; }",
    ".hub-page--flush { padding-bottom: 220px; }",
    ".lifecycle-actions details.tray summary,",
    ".lifecycle-actions .tray__body .btn { scroll-margin-bottom: 220px; }",
    ".hub-header__inner { padding: 10px 14px; gap: 10px; flex-wrap: wrap; }",
    ".hub-header__right { margin-left: auto; }",
    ".dltile { flex-wrap: wrap; }",
    '.dropzone input[type="file"] { min-width: 0; width: 100%; max-width: 100%; }',
)


def _lifecycle_section(css: str, stylesheet: str) -> str:
    assert _MARKER in css, f"{stylesheet} must keep the lifecycle CSS marker"
    return css[css.index(_MARKER) :]


def _balanced_brace_block(text: str, brace_index: int, stylesheet: str) -> str:
    """Return the text from an opening brace through its matching close."""
    assert text[brace_index] == "{", f"{stylesheet} expected an opening brace"
    depth = 0
    for index in range(brace_index, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index : index + 1]
    raise AssertionError(f"{stylesheet} has an unclosed CSS block")


def _rule_body(text: str, selector: str, stylesheet: str) -> str:
    """Return the balanced body of one selector block in ``text``."""
    try:
        selector_start = text.index(selector)
    except ValueError as exc:
        raise AssertionError(
            f"{stylesheet} must keep the {selector!r} rule"
        ) from exc
    opening_brace = text.index("{", selector_start)
    return _balanced_brace_block(text, opening_brace, stylesheet)


def _mobile_media_block(section: str, stylesheet: str) -> tuple[str, str]:
    """Split the lifecycle section into desktop scope and its bounded mobile block.

    The previous test sliced marker-to-EOF, so moving the mobile declarations
    outside the media query still passed. The media query is now located and
    brace-balanced, and the two parts are asserted separately.
    """
    assert section.count(_MOBILE_MEDIA) == 1, (
        f"{stylesheet} must keep exactly one lifecycle mobile media query"
    )
    media_start = section.index(_MOBILE_MEDIA)
    desktop = section[:media_start]
    opening_brace = section.index("{", media_start)
    brace_block = _balanced_brace_block(section, opening_brace, stylesheet)
    brace_start = section.index(brace_block, media_start)
    mobile = section[media_start : brace_start + len(brace_block)]
    assert mobile.startswith(_MOBILE_MEDIA)
    assert mobile.endswith("}"), f"{stylesheet} mobile media block must be closed"
    return desktop, mobile


def _assert_contract(css: str, stylesheet: str) -> None:
    section = _lifecycle_section(css, stylesheet)
    desktop, mobile = _mobile_media_block(section, stylesheet)

    # Desktop keeps the bounding/focus contract outside the mobile query.
    for declaration in _DESKTOP_GEOMETRY:
        assert declaration in desktop, (
            f"{stylesheet} must keep {declaration!r} in the desktop lifecycle scope"
        )

    tablewrap = _rule_body(desktop, ".tablewrap--lifecycle {", stylesheet)
    for declaration in _TABLEWRAP_GEOMETRY:
        assert declaration in tablewrap, (
            f"{stylesheet} .tablewrap--lifecycle must keep {declaration!r}"
        )

    focus = _rule_body(
        desktop, ".tablewrap--lifecycle:focus-visible {", stylesheet
    )
    for declaration in _FOCUS_GEOMETRY:
        assert declaration in focus, (
            f"{stylesheet} focus-visible rule must keep {declaration!r}"
        )

    # Mobile geometry and clearance must be inside the bounded 680px block...
    for declaration in _MOBILE_ONLY:
        assert declaration in mobile, (
            f"{stylesheet} must keep {declaration!r} inside the 680px mobile block"
        )
        # ...and must not leak unscoped into the desktop lifecycle section.
        assert declaration not in desktop, (
            f"{stylesheet} must not apply mobile declaration {declaration!r} un-scoped"
        )


def test_shipped_css_bounds_lifecycle_tables_and_clears_the_actionbar():
    _assert_contract(
        _SHIPPED_CSS.read_text(encoding="utf-8"), "static/admin_hub/hub.css"
    )


def test_mockup_css_keeps_the_same_lifecycle_mobile_contract():
    _assert_contract(
        _MOCKUP_CSS.read_text(encoding="utf-8"), "style-guide/admin/hub.css"
    )

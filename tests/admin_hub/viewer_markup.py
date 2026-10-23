"""Parsing helpers for the Admin Hub document viewer markup.

These are test-support helpers, not tests. They keep the Slice 2 viewer
regressions (``test_hub_cockpit.py``, ``test_hub_viewer_js.py``) reading the
same rendered fragment instead of each maintaining its own regexes.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
     "param", "source", "track", "wbr"}
)

_VIEWER_OPEN = re.compile(r'<div[^>]*class="[^"]*\bviewer\b[^"]*"[^>]*>')


def viewer_region(body: str) -> str:
    """Return the rendered viewer fragment, excluding the rest of the cockpit.

    The cockpit places ``{% include "admin_hub/_viewer.html" %}`` immediately
    before the review checklist, so the boundary is stable markup, not a guess
    about div nesting depth.
    """
    match = _VIEWER_OPEN.search(body)
    assert match is not None, "the cockpit must render the document viewer"
    start = match.start()
    end = body.find("<section data-checklist", match.end())
    assert end != -1, "the checklist section must follow the viewer"
    return body[start:end]


def tab_tags(region: str) -> list[str]:
    """Full ``<button>`` tags for every viewer tab, in render order."""
    return re.findall(r"<button[^>]*data-viewer-tab[^>]*>[^<]*</button>", region, re.S)


def tab_labels(region: str) -> list[str]:
    return [
        re.sub(r"^<button[^>]*>", "", tag).replace("</button>", "").strip()
        for tag in tab_tags(region)
    ]


def tab_index(tag: str) -> int:
    value = attr_value(tag, "data-viewer-tab")
    assert value is not None and value.isdigit(), f"tab has no numeric index: {tag!r}"
    return int(value)


def stage_open_tag(region: str, index: int) -> str:
    match = re.search(
        rf'<div[^>]*data-viewer-stage="{index}"[^>]*>', region, re.S
    )
    return match.group(0) if match else ""


def stage_html(region: str, index: int) -> str:
    """Markup inside one ``[data-viewer-stage]`` element.

    Stops at the next stage, the toolbar, or the all-missing empty state -
    whichever comes first - without pretending to parse nested divs.
    """
    match = re.search(
        rf'<div[^>]*data-viewer-stage="{index}"[^>]*>', region, re.S
    )
    if match is None:
        return ""
    rest = region[match.end():]
    boundary = re.search(
        r'<div[^>]*data-viewer-stage="'
        r'|<div[^>]*class="[^"]*viewer__bar'
        r'|<[^>]*data-viewer-empty',
        rest,
        re.S,
    )
    return rest[: boundary.start()] if boundary else rest


def open_tag_with_attr(fragment: str, attribute: str) -> str:
    """First opening tag in *fragment* carrying *attribute*."""
    match = re.search(rf"<[^>]*\b{re.escape(attribute)}\b[^>]*>", fragment, re.S)
    return match.group(0) if match else ""


def attr_value(tag: str, attribute: str) -> str | None:
    match = re.search(
        rf'\b{re.escape(attribute)}\s*=\s*"([^"]*)"', tag, re.S
    )
    return match.group(1) if match else None


def has_attribute(tag: str, attribute: str) -> bool:
    return re.search(rf"\b{re.escape(attribute)}\b", tag) is not None


def link_with_href(fragment: str, href: str) -> str:
    """First anchor whose ``href`` is exactly *href* (escaped for regex)."""
    match = re.search(rf'<a\b[^>]*href="{re.escape(href)}"[^>]*>', fragment, re.S)
    return match.group(0) if match else ""


class _TreeParser(HTMLParser):
    """Minimal HTML -> nested-dict parser for the Node DOM harness."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[dict[str, object]] = []
        self._stack: list[tuple[list[dict[str, object]], str | None]] = [
            (self.root, None)
        ]

    def handle_starttag(self, tag: str, attrs) -> None:
        node: dict[str, object] = {
            "tag": tag,
            "attrs": {key: "" if value is None else value for key, value in attrs},
            "children": [],
        }
        self._stack[-1][0].append(node)
        if tag not in _VOID_TAGS:
            self._stack.append((node["children"], tag))  # type: ignore[arg-type]

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._stack[-1][0].append(
            {
                "tag": tag,
                "attrs": {key: "" if value is None else value for key, value in attrs},
                "children": [],
            }
        )

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth][1] == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1][0].append({"text": data})


def viewer_tree(body: str) -> dict[str, object]:
    """The viewer fragment as a JSON-serialisable DOM tree."""
    parser = _TreeParser()
    parser.feed(viewer_region(body))
    parser.close()
    return {"children": parser.root}

"""Test-support parsing for the correction-history JS harness.

Not a test: turns real rendered Hub markup into the small JSON DOM tree that
``correction_messages_dom_harness.js`` executes the shipped script against.
"""

from __future__ import annotations

from html.parser import HTMLParser

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _TreeParser(HTMLParser):
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
                "attrs": {
                    key: "" if value is None else value
                    for key, value in attrs
                },
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


def dom_tree(body: str) -> dict[str, object]:
    parser = _TreeParser()
    parser.feed(body)
    parser.close()
    return {"children": parser.root}

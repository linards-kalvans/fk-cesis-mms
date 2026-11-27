"""Runnable regression for the agreement-preview signing-path switch (Task 5).

The shipped ``static/js/agreement_preview.js`` runs in Node's built-in ``vm``
sandbox against a minimal DOM/fetch harness. No npm dependency is required.
The harness resolves deferred manifest requests out of order so an older
response can be proven unable to replace the newly selected path.

This is not browser proof: CSS, native dialog modality and real HTTP caching
remain manual acceptance checks. If Node is unavailable the module skips.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import pytest

_NODE = shutil.which("node")
_HARNESS = Path(__file__).with_name("agreement_preview_dom_harness.js")
_SCRIPT = (
    Path(__file__).resolve().parents[2] / "static" / "js" / "agreement_preview.js"
)

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="Node.js is not installed; the agreement-preview JS harness cannot run.",
)


def _node(tag: str, attrs: dict[str, str] | None = None, children=None):
    return {"tag": tag, "attrs": attrs or {}, "children": children or []}


def _tree() -> dict[str, Any]:
    return {
        "children": [
            _node(
                "section",
                {
                    "class": "fk-agreement-preview",
                    "data-agreement-preview": "",
                    "data-preview-url": (
                        "/register/agreement-preview/"
                        "?backend=local&template_version=v1-2026-11"
                    ),
                    "data-preview-signing-path-source": (
                        "#id_preferred_agreement_signing"
                    ),
                    "data-preview-loading": "Līguma priekšskatījums tiek sagatavots…",
                    "data-preview-error": "Nav pieejams.",
                    "data-preview-page-label": "Lapa",
                },
                [
                    _node(
                        "div",
                        {"data-preview-home": ""},
                        [
                            _node(
                                "div",
                                {"data-preview-content": ""},
                                [
                                    _node(
                                        "p",
                                        {"data-preview-status": ""},
                                        [{"text": "Līguma priekšskatījums tiek sagatavots…"}],
                                    ),
                                    _node(
                                        "div",
                                        {"data-preview-paper": "", "hidden": ""},
                                        [
                                            _node(
                                                "img",
                                                {
                                                    "data-preview-image": "",
                                                    "alt": "Līguma paraugs",
                                                },
                                            )
                                        ],
                                    ),
                                    _node(
                                        "div",
                                        {"data-preview-navigation": "", "hidden": ""},
                                        [
                                            _node(
                                                "button",
                                                {"data-preview-prev": ""},
                                                [{"text": "←"}],
                                            ),
                                            _node("span", {"data-preview-page": ""}),
                                            _node(
                                                "button",
                                                {"data-preview-next": ""},
                                                [{"text": "→"}],
                                            ),
                                        ],
                                    ),
                                    _node(
                                        "button",
                                        {"data-preview-retry": "", "hidden": ""},
                                        [{"text": "Mēģināt vēlreiz"}],
                                    ),
                                ],
                            )
                        ],
                    ),
                    _node(
                        "button",
                        {"data-preview-expand": "", "disabled": ""},
                        [{"text": "Palielināt"}],
                    ),
                    _node(
                        "dialog",
                        {"data-preview-dialog": ""},
                        [
                            _node(
                                "button",
                                {"data-preview-close": ""},
                                [{"text": "Aizvērt"}],
                            ),
                            _node("div", {"data-preview-expanded": ""}),
                        ],
                    ),
                ],
            ),
            _node(
                "select",
                {
                    "id": "id_preferred_agreement_signing",
                    "name": "preferred_agreement_signing",
                    "value": "electronic",
                },
                [
                    _node("option", {"value": "electronic"}, [{"text": "Elektroniski"}]),
                    _node("option", {"value": "paper"}, [{"text": "Papīrs"}]),
                ],
            ),
        ]
    }


def _run(actions: list[dict[str, Any]]) -> dict[str, Any]:
    assert _NODE is not None
    process = subprocess.run(
        [_NODE, str(_HARNESS), str(_SCRIPT)],
        input=json.dumps({"tree": _tree(), "actions": actions}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, (
        "agreement_preview.js harness failed:\n"
        f"stdout={process.stdout}\nstderr={process.stderr}"
    )
    return cast(dict[str, Any], json.loads(process.stdout))


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


@pytest.mark.django_db
def test_workspace_exposes_the_signing_path_source(verified_client, draft_application):
    from django.urls import reverse

    html = verified_client.get(
        reverse("registrations:application-workspace", args=[draft_application.pk])
    ).content.decode()
    section = re.search(
        r"<section[^>]*\bdata-agreement-preview\b[^>]*>", html, re.S
    )
    assert section is not None
    assert (
        'data-preview-signing-path-source="#id_preferred_agreement_signing"'
        in section.group(0)
    )


@pytest.mark.django_db
def test_workspace_preview_url_asserts_the_configured_local_identity(
    verified_client, draft_application, settings
):
    from django.urls import reverse

    settings.AGREEMENT_DOCUMENT_MODE = "local"
    html = verified_client.get(
        reverse("registrations:application-workspace", args=[draft_application.pk])
    ).content.decode()
    match = re.search(r'data-preview-url="([^"]+)"', html)
    assert match is not None
    query = _query(match.group(1).replace("&amp;", "&"))
    assert query["backend"] == ["local"]
    assert query["template_version"] == ["v1-2026-11"]


def test_switching_the_path_requests_and_shows_the_new_identity():
    result = _run(
        [
            {"type": "intersect"},
            {"type": "settle"},
            {
                "type": "resolve",
                "index": 0,
                "manifest": {
                    "pages": [
                        "/register/agreement-preview/aaaa/1/"
                        "?backend=local&signing_path=electronic"
                    ]
                },
            },
            {"type": "settle"},
            {
                "type": "change-path",
                "selector": "#id_preferred_agreement_signing",
                "value": "paper",
            },
            {"type": "settle"},
            {
                "type": "resolve",
                "index": 1,
                "manifest": {
                    "pages": [
                        "/register/agreement-preview/bbbb/1/"
                        "?backend=local&signing_path=paper"
                    ]
                },
            },
            {"type": "settle"},
        ]
    )

    assert result["unresolved"] == []
    assert result["fetchCount"] == 2, "a path change must request its own manifest"
    assert _query(result["fetchCalls"][0])["signing_path"] == ["electronic"]
    assert _query(result["fetchCalls"][1])["signing_path"] == ["paper"]
    assert _query(result["fetchCalls"][1])["backend"] == ["local"]
    assert result["imageSrc"] is not None
    assert _query(result["imageSrc"])["signing_path"] == ["paper"]
    assert "electronic" not in result["imageSrc"]


def _switch_to_paper_then_resolve_new_image() -> list[dict[str, Any]]:
    return [
        {"type": "intersect"},
        {"type": "settle"},
        {
            "type": "resolve",
            "index": 0,
            "manifest": {
                "pages": [
                    "/register/agreement-preview/aaaa/1/"
                    "?backend=local&signing_path=electronic"
                ]
            },
        },
        {"type": "settle"},
        {
            "type": "change-path",
            "selector": "#id_preferred_agreement_signing",
            "value": "paper",
        },
        {"type": "settle"},
        {
            "type": "resolve",
            "index": 1,
            "manifest": {
                "pages": [
                    "/register/agreement-preview/bbbb/1/"
                    "?backend=local&signing_path=paper"
                ]
            },
        },
        {"type": "settle"},
    ]


def test_stale_old_image_load_cannot_replace_current_loading_state():
    result = _run(
        _switch_to_paper_then_resolve_new_image()
        + [{"type": "image-event", "event": "load"}, {"type": "settle"}]
    )

    assert _query(result["imageSrc"])["signing_path"] == ["paper"]
    assert result["statusHidden"] is False
    assert result["statusText"] == "Līguma priekšskatījums tiek sagatavots…"
    assert result["paperHidden"] is True
    assert result["retryHidden"] is True


def test_stale_old_image_error_cannot_replace_current_loading_state():
    result = _run(
        _switch_to_paper_then_resolve_new_image()
        + [{"type": "image-event", "event": "error"}, {"type": "settle"}]
    )

    assert _query(result["imageSrc"])["signing_path"] == ["paper"]
    assert result["statusHidden"] is False
    assert result["statusText"] == "Līguma priekšskatījums tiek sagatavots…"
    assert result["paperHidden"] is True
    assert result["retryHidden"] is True


def test_current_image_load_still_reveals_the_page():
    result = _run(
        _switch_to_paper_then_resolve_new_image()
        + [
            {
                "type": "image-event",
                "event": "load",
                "complete": True,
                "naturalWidth": 200,
            },
            {"type": "settle"},
        ]
    )

    assert _query(result["imageSrc"])["signing_path"] == ["paper"]
    assert result["statusHidden"] is True
    assert result["paperHidden"] is False


def test_an_older_response_cannot_replace_the_latest_path():
    result = _run(
        [
            {"type": "intersect"},
            {"type": "settle"},
            {
                "type": "resolve",
                "index": 0,
                "manifest": {
                    "pages": [
                        "/register/agreement-preview/aaaa/1/"
                        "?backend=local&signing_path=electronic"
                    ]
                },
            },
            {"type": "settle"},
            {
                "type": "change-path",
                "selector": "#id_preferred_agreement_signing",
                "value": "paper",
            },
            {"type": "settle"},
            {
                "type": "change-path",
                "selector": "#id_preferred_agreement_signing",
                "value": "electronic",
            },
            {"type": "settle"},
            {
                "type": "resolve",
                "index": 2,
                "manifest": {
                    "pages": [
                        "/register/agreement-preview/cccc/1/"
                        "?backend=local&signing_path=electronic"
                    ]
                },
            },
            {"type": "settle"},
            {
                "type": "resolve",
                "index": 1,
                "manifest": {
                    "pages": [
                        "/register/agreement-preview/bbbb/1/"
                        "?backend=local&signing_path=paper"
                    ]
                },
            },
            {"type": "settle"},
        ]
    )

    assert result["unresolved"] == []
    assert result["fetchCount"] == 3
    assert result["imageSrc"] is not None
    assert _query(result["imageSrc"])["signing_path"] == ["electronic"]
    assert "paper" not in result["imageSrc"]

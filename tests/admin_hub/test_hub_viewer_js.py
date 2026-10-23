"""Runnable regression for the Admin Hub viewer JavaScript (Slice 2).

The tests render the real cockpit markup, parse the viewer fragment into a
small DOM tree, and execute ``static/admin_hub/viewer.js`` in Node's built-in
``vm`` sandbox against a minimal DOM harness. No npm dependency is required.
If Node is unavailable the module skips and says so; the static markup
contract remains covered by ``test_hub_cockpit.py``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from django.urls import reverse

from tests.admin_hub.viewer_markup import viewer_tree

_NODE = shutil.which("node")
_HARNESS = Path(__file__).with_name("viewer_dom_harness.js")
_VIEWER_JS = Path(__file__).resolve().parents[2] / "static" / "admin_hub" / "viewer.js"

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.admin_view,
    pytest.mark.skipif(
        _NODE is None,
        reason="Node.js is not installed; the viewer JS harness cannot run.",
    ),
]


_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
_PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def _replace_document(application, kind, filename, content_type):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.utils import timezone

    from apps.documents.models import Document

    application.documents.filter(kind=kind, deleted_at__isnull=True).update(
        deleted_at=timezone.now()
    )
    payload = _PDF_BYTES if content_type == "application/pdf" else _IMAGE_BYTES
    return Document.objects.create(
        application=application,
        kind=kind,
        file=SimpleUploadedFile(filename, payload, content_type=content_type),
        original_filename=filename,
        content_type=content_type,
        file_size=len(payload),
    )


def _cockpit_body(client, reviewer, application):
    client.force_login(reviewer)
    return client.get(
        reverse("admin_hub:cockpit", args=[application.pk])
    ).content.decode()


def _run(body: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    assert _NODE is not None
    process = subprocess.run(
        [_NODE, str(_HARNESS), str(_VIEWER_JS)],
        input=json.dumps({"tree": viewer_tree(body), "actions": actions}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, (
        "viewer.js harness failed:\n"
        f"stdout={process.stdout}\nstderr={process.stderr}"
    )
    return cast(dict[str, Any], json.loads(process.stdout))


def _all_disabled(result: dict[str, Any], controls=("rotate", "zoom", "reset")) -> bool:
    return all(value for name in controls for value in result["controls"][name])


def _any_disabled(result: dict[str, Any], controls=("rotate", "zoom", "reset")) -> bool:
    return any(value for name in controls for value in result["controls"][name])


def _stage_transform(result: dict[str, Any], index: int):
    for stage in result["imageTransforms"]:
        if stage["index"] == index:
            return stage["transform"]
    raise AssertionError(f"stage {index} missing from harness result")


def test_image_controls_enable_only_after_the_image_loads(
    client, reviewer, submitted_application
):
    body = _cockpit_body(client, reviewer, submitted_application)

    before = _run(body, [])
    assert before["activeTab"] == 0
    assert _all_disabled(before), "transforms must start disabled before load"
    assert before["zoomLabel"] == "—", "zoom must not claim 100 % before load"

    after = _run(body, [{"type": "load", "stage": 0, "width": 800, "height": 600}])
    assert not _any_disabled(after), "a loaded image may be transformed"
    assert after["zoomLabel"] == "100 %"
    assert after["imageTransform"]


def test_fit_preserves_a_rotated_image_orientation(
    client, reviewer, submitted_application
):
    """The fit/reset control refits the view; it must not silently undo a
    reviewer's rotation."""
    body = _cockpit_body(client, reviewer, submitted_application)

    result = _run(
        body,
        [
            {"type": "load", "stage": 0, "width": 800, "height": 600},
            {"type": "click-control", "selector": '[data-viewer-rotate="90"]'},
            {"type": "click-control", "selector": "[data-viewer-reset]"},
        ],
    )

    transform = result["imageTransform"]
    assert transform, "fit must leave a transform on the loaded image"
    assert transform.startswith("rotate(90deg)"), (
        f"fit must preserve the 90-degree rotation; got {transform!r}"
    )
    assert result["zoomLabel"].endswith(" %")


def test_zoom_controls_work_for_a_loaded_image(
    client, reviewer, submitted_application
):
    body = _cockpit_body(client, reviewer, submitted_application)

    result = _run(
        body,
        [
            {"type": "load", "stage": 0, "width": 800, "height": 600},
            {"type": "click-control", "selector": '[data-viewer-zoom="0.15"]'},
        ],
    )

    assert result["zoomLabel"] == "115 %"


def test_pdf_disables_image_controls_and_the_toolbar_follows_the_tab(
    client, reviewer, submitted_application
):
    from apps.documents.models import Document

    pdf = _replace_document(
        submitted_application,
        Document.Kind.MEMBER_IDENTITY,
        "member_id.pdf",
        "application/pdf",
    )
    guardian_doc = submitted_application.documents.get(
        kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
    )
    body = _cockpit_body(client, reviewer, submitted_application)

    initial = _run(body, [])
    assert initial["activeTab"] == 0
    assert _all_disabled(initial), "a PDF has no raster transforms"
    assert initial["zoomLabel"] == "—"
    assert initial["open"] == {
        "href": reverse("documents:admin-document-preview", args=[pdf.id]),
        "hidden": False,
    }
    assert initial["get"] == {
        "href": reverse("documents:admin-document-download", args=[pdf.id]),
        "hidden": False,
    }

    loaded_image = _run(
        body,
        [
            {"type": "load", "stage": 2, "width": 800, "height": 600},
            {"type": "click-tab", "tab": 2},
        ],
    )
    assert loaded_image["activeTab"] == 2
    assert not _any_disabled(loaded_image)
    assert loaded_image["zoomLabel"] == "100 %"
    assert loaded_image["open"]["href"] == reverse(
        "documents:admin-document-preview", args=[guardian_doc.id]
    )
    assert loaded_image["get"]["href"] == reverse(
        "documents:admin-document-download", args=[guardian_doc.id]
    )

    back_on_pdf = _run(
        body,
        [
            {"type": "load", "stage": 2, "width": 800, "height": 600},
            {"type": "click-tab", "tab": 2},
            {"type": "click-tab", "tab": 0},
        ],
    )
    assert back_on_pdf["activeTab"] == 0
    assert _all_disabled(back_on_pdf)
    assert back_on_pdf["zoomLabel"] == "—"
    assert back_on_pdf["open"]["href"] == reverse(
        "documents:admin-document-preview", args=[pdf.id]
    )


def test_keyboard_transforms_do_not_touch_a_hidden_image_while_pdf_is_active(
    client, reviewer, submitted_application
):
    from apps.documents.models import Document

    _replace_document(
        submitted_application,
        Document.Kind.MEMBER_IDENTITY,
        "member_id.pdf",
        "application/pdf",
    )
    body = _cockpit_body(client, reviewer, submitted_application)

    loaded = _run(
        body,
        [
            {"type": "load", "stage": 2, "width": 800, "height": 600},
            {"type": "click-tab", "tab": 2},
        ],
    )
    after_keyboard = _run(
        body,
        [
            {"type": "load", "stage": 2, "width": 800, "height": 600},
            {"type": "click-tab", "tab": 2},
            {"type": "click-tab", "tab": 0},
            {"type": "keydown", "shiftKey": True, "key": "ArrowRight"},
        ],
    )
    assert _stage_transform(after_keyboard, 2) == _stage_transform(loaded, 2)


def test_image_error_shows_the_fallback_and_keeps_controls_disabled(
    client, reviewer, submitted_application
):
    body = _cockpit_body(client, reviewer, submitted_application)
    failed = _run(body, [{"type": "error", "stage": 0}])

    assert failed["imageErrorHidden"] is False, (
        "a failed image (e.g. HEIC in an unsupported browser) must show the fallback"
    )
    assert _all_disabled(failed)
    assert failed["zoomLabel"] == "—"


def test_initialisation_uses_the_first_available_tab(
    client, reviewer, submitted_application
):
    from django.utils import timezone

    from apps.documents.models import Document

    submitted_application.documents.filter(
        kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
    ).update(deleted_at=timezone.now())
    guardian_doc = submitted_application.documents.get(
        kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
    )
    body = _cockpit_body(client, reviewer, submitted_application)

    initial = _run(body, [])
    assert initial["activeTab"] == 2, (
        "JS must keep the first available tab active instead of tab 0"
    )
    assert initial["stages"][2]["hidden"] is False
    assert initial["stages"][0]["hidden"] is True
    assert initial["open"]["href"] == reverse(
        "documents:admin-document-preview", args=[guardian_doc.id]
    )

    loaded = _run(
        body, [{"type": "load", "stage": 2, "width": 800, "height": 600}]
    )
    assert not _any_disabled(loaded)
    assert loaded["zoomLabel"] == "100 %"


def test_all_missing_renders_no_active_tab_and_no_stale_links(
    client, reviewer, submitted_application
):
    from django.utils import timezone

    submitted_application.documents.update(deleted_at=timezone.now())
    body = _cockpit_body(client, reviewer, submitted_application)
    result = _run(body, [])

    assert result["emptyState"] is True
    assert result["activeTab"] is None
    assert all(stage["hidden"] for stage in result["stages"])
    assert result["open"] == {"href": None, "hidden": True}
    assert result["get"] == {"href": None, "hidden": True}
    assert result["zoomLabel"] == "—"

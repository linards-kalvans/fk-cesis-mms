"""Runnable regression for the Admin Hub correction-history JavaScript.

The cockpit is rendered from real Django data, the summary/dialog markup is
parsed into a small DOM tree, and the shipped ``correction_messages.js`` runs
in Node's built-in ``vm`` sandbox. No npm dependency is required.

This proves event handling, fetch-on-click, pagination, dismissal and focus
return. It is not browser proof: CSS hover, native dialog modality and Escape
remain manual acceptance checks. If Node is unavailable the module skips.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.registrations.models import ApplicationCorrectionMessage
from tests.admin_hub.correction_messages_markup import dom_tree

_NODE = shutil.which("node")
_HARNESS = Path(__file__).with_name("correction_messages_dom_harness.js")
_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "static"
    / "admin_hub"
    / "correction_messages.js"
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.admin_view,
    pytest.mark.skipif(
        _NODE is None,
        reason="Node.js is not installed; the correction-history JS harness cannot run.",
    ),
]


def _message(application, subject="Labojuma ziņa", body="E-pasta teksts."):
    return ApplicationCorrectionMessage.objects.create(
        application=application,
        status=ApplicationCorrectionMessage.Status.SENT,
        subject=subject,
        body=body,
        review_message="Piezīme.",
        sent_at=timezone.now(),
    )


def _cockpit_body(client, reviewer, application):
    client.force_login(reviewer)
    return client.get(
        reverse("admin_hub:cockpit", args=[application.pk])
    ).content.decode()


def _fragment(client, reviewer, application, page=None):
    client.force_login(reviewer)
    params = {"page": page} if page is not None else {}
    response = client.get(
        reverse("admin_hub:correction-messages", args=[application.pk]),
        params,
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 200
    return response.content.decode()


def _run(
    body: str,
    actions: list[dict[str, Any]],
    *,
    responses: list[dict[str, Any]] | None = None,
    response_mode: str = "ok",
    support_dialog: bool = True,
) -> dict[str, Any]:
    assert _NODE is not None
    process = subprocess.run(
        [_NODE, str(_HARNESS), str(_SCRIPT)],
        input=json.dumps(
            {
                "tree": dom_tree(body),
                "actions": actions,
                "responses": responses or [],
                "responseMode": response_mode,
                "supportDialog": support_dialog,
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0, (
        "correction_messages.js harness failed:\n"
        f"stdout={process.stdout}\nstderr={process.stderr}"
    )
    return cast(dict[str, Any], json.loads(process.stdout))


def test_hover_and_focus_reveal_summary_without_fetching(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)
    result = _run(
        body,
        [
            {"type": "hover", "selector": "[data-correction-summary]"},
            {"type": "focus", "selector": "[data-correction-open]"},
            {"type": "flush"},
        ],
        responses=[{"ok": True, "status": 200, "html": "<p>nav jāielādē</p>"}],
    )

    assert result["fetchCount"] == 0
    assert result["dialogOpen"] is False


def test_click_loads_the_authorized_fragment_and_sets_fallback(
    client, reviewer, submitted_application
):
    _message(submitted_application, subject="Ielādītā ziņa", body="Slepenais teksts")
    body = _cockpit_body(client, reviewer, submitted_application)
    fragment = _fragment(client, reviewer, submitted_application)
    history_url = reverse(
        "admin_hub:correction-messages", args=[submitted_application.pk]
    )

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
        ],
        responses=[{"ok": True, "status": 200, "html": fragment}],
    )

    assert result["fetchCount"] == 1
    assert result["fetchCalls"][0]["url"] == history_url
    assert result["fetchCalls"][0]["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert "Ielādē ziņu vēsturi" in result["loadingText"]
    assert "Ielādītā ziņa" in result["bodyText"]
    assert "Slepenais teksts" in result["bodyText"]
    assert result["dialogOpen"] is True
    assert result["defaultPrevented"] is True
    assert result["fallbackHref"] == history_url


def test_fetch_error_does_not_invent_empty_history(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)
    history_url = reverse(
        "admin_hub:correction-messages", args=[submitted_application.pk]
    )

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
        ],
        response_mode="error",
    )

    assert result["fetchCount"] == 1
    assert "Neizdevās ielādēt ziņu vēsturi" in result["bodyText"]
    assert "Nav reģistrētu" not in result["bodyText"]
    assert result["fallbackHref"] == history_url


def test_redirected_200_response_is_never_injected(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)
    history_url = reverse(
        "admin_hub:correction-messages", args=[submitted_application.pk]
    )

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
        ],
        responses=[
            {
                "ok": True,
                "status": 200,
                "redirected": True,
                "html": "<html><body>Django administration login</body></html>",
            }
        ],
    )

    assert result["fetchCount"] == 1
    assert "Neizdevās ielādēt ziņu vēsturi" in result["bodyText"]
    assert "Django administration login" not in result["bodyText"]
    assert result["bodyBusy"] == "false"
    assert result["fallbackHref"] == history_url


def test_non_history_200_body_is_not_injected(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
        ],
        responses=[
            {"ok": True, "status": 200, "html": "<html>login page</html>"}
        ],
    )

    assert "Neizdevās ielādēt ziņu vēsturi" in result["bodyText"]
    assert "login page" not in result["bodyText"]
    assert result["bodyBusy"] == "false"


def test_a_stale_response_cannot_replace_the_latest_one(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
        ],
        responses=[
            {
                "ok": True,
                "status": 200,
                "html": '<div data-correction-history>Pirmā atbilde</div>',
            },
            {
                "ok": True,
                "status": 200,
                "html": '<div data-correction-history>Otrā atbilde</div>',
            },
        ],
    )

    assert result["fetchCount"] == 2
    assert "Otrā atbilde" in result["bodyText"]
    assert "Pirmā atbilde" not in result["bodyText"]


def test_pagination_stays_inside_the_dialog(
    client, reviewer, submitted_application
):
    base = timezone.now() - datetime.timedelta(days=30)
    for index in range(1, 26):
        message = _message(
            submitted_application, subject=f"Ziņa {index:02d}"
        )
        ApplicationCorrectionMessage.objects.filter(pk=message.pk).update(
            created_at=base + datetime.timedelta(hours=index)
        )

    body = _cockpit_body(client, reviewer, submitted_application)
    first_page = _fragment(client, reviewer, submitted_application)
    second_page = _fragment(client, reviewer, submitted_application, page=2)

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
            {"type": "click", "selector": "[data-correction-page]"},
            {"type": "flush"},
        ],
        responses=[
            {"ok": True, "status": 200, "html": first_page},
            {"ok": True, "status": 200, "html": second_page},
        ],
    )

    assert result["fetchCount"] == 2
    assert "page=2" in result["fetchCalls"][1]["url"]
    assert "Ziņa 21" in result["bodyText"]
    assert "Ziņa 25" in result["bodyText"]
    assert "Ziņa 01" not in result["bodyText"]


def test_close_button_returns_focus_to_the_trigger(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)
    fragment = _fragment(client, reviewer, submitted_application)

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
            {"type": "click", "selector": "[data-correction-close]"},
        ],
        responses=[{"ok": True, "status": 200, "html": fragment}],
    )

    assert result["dialogOpen"] is False
    active = result["activeElement"]
    assert active is not None
    assert "data-correction-open" in active["attrs"]


def test_backdrop_click_closes_the_dialog(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)
    fragment = _fragment(client, reviewer, submitted_application)

    result = _run(
        body,
        [
            {"type": "click", "selector": "[data-correction-open]"},
            {"type": "flush"},
            {"type": "click", "selector": "[data-correction-dialog]"},
        ],
        responses=[{"ok": True, "status": 200, "html": fragment}],
    )

    assert result["dialogOpen"] is False


def test_without_native_dialog_support_the_link_navigates(
    client, reviewer, submitted_application
):
    _message(submitted_application)
    body = _cockpit_body(client, reviewer, submitted_application)

    result = _run(
        body,
        [{"type": "click", "selector": "[data-correction-open]"}],
        support_dialog=False,
    )

    assert result["fetchCount"] == 0
    assert result["defaultPrevented"] is False

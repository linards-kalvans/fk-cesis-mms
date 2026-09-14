"""No Hub page may render a template comment as visible text.

Django's ``{# ... #}`` comment is **single-line only**. A multi-line one is
not a comment at all: the marker and the prose between it render into the
page. Seven such comments shipped on the Hub's detail pages, printing English
developer notes into a Latvian staff UI and breaking the action-bar layout,
because inline text became flex content beside the buttons.

Nothing caught it: the whole suite asserts on response bodies, and no
assertion said the body must *not* contain something. This does.
"""

from __future__ import annotations

import pathlib

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def _hub_urls(application):
    return [
        reverse("admin_hub:queue"),
        reverse("admin_hub:invoices"),
        reverse("admin_hub:exports"),
        reverse("admin_hub:cockpit", args=[application.pk]),
        reverse("admin_hub:agreement", args=[application.pk]),
        reverse("admin_hub:billing", args=[application.pk]),
    ]


def test_no_rendered_hub_page_contains_a_comment_marker(
    client, reviewer, approved_application
):
    """approved_application is used because the agreement and billing views
    404 without an agreement, and those two pages carried three of the eight
    broken comments between them."""
    client.force_login(reviewer)
    for url in _hub_urls(approved_application):
        body = client.get(url).content.decode()
        assert "{#" not in body, f"template comment marker leaked into {url}"
        assert "#}" not in body, f"template comment marker leaked into {url}"


def test_no_template_uses_a_multiline_single_line_comment():
    """The rendering test above only covers pages a request can reach with the
    fixtures at hand. This one reads the templates directly, so a broken
    comment in a branch no test happens to render still fails."""
    offenders = []
    for path in sorted(pathlib.Path("templates").rglob("*.html")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if "{#" in line and "#}" not in line:
                offenders.append(f"{path}:{number}")
    assert not offenders, (
        "multi-line {# #} comments render as visible text; use "
        "{% comment %}...{% endcomment %} instead: " + ", ".join(offenders)
    )

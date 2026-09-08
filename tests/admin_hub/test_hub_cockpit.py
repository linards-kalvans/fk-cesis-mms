"""Review cockpit page."""

from __future__ import annotations

import re

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def test_cockpit_requires_staff(client, submitted_application):
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_cockpit_renders_the_field_readout(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Datu pārbaude" in body
    # All four field groups, not just a sample of them.
    assert "Bērns" in body
    assert "Vecāks / likumiskais pārstāvis" in body
    assert "Ekipējums un izvēles" in body
    assert "Piekrišanas" in body
    assert "Formas izmērs" in body
    assert submitted_application.member_full_name in body


def test_cockpit_shows_the_check_off_bar_with_the_renamed_action(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "Apstiprināt visus" in body
    assert "Atzīmēt visus" not in body, "the action was renamed"


def test_approve_button_is_never_gated_on_the_checklist(
    client, reviewer, submitted_application
):
    """The checklist is a working aid. Nothing about it may disable approval.

    Parses the actual <button> element carrying the approve label, rather
    than scanning a substring window of the page, so this fails if the
    button ever grows a `disabled` attribute or an `is-disabled` class -
    whether or not that text happens to land within an arbitrary window.
    """
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    match = re.search(r"<button[^>]*>\s*Apstiprināt pieteikumu[^<]*</button>", body)
    assert match is not None, "approve button not found in the rendered page"
    button_html = match.group(0)
    assert "disabled" not in button_html
    assert "is-disabled" not in button_html


def test_cockpit_posts_approval_to_the_existing_admin_endpoint(
    client, reviewer, submitted_application
):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    approve_url = reverse(
        "admin:registrations_registrationapplication_approve",
        args=[submitted_application.pk],
    )
    assert approve_url in body
    assert "csrfmiddlewaretoken" in body


def test_cockpit_carries_a_next_back_to_itself(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert f'value="{url}"' in body


def test_cockpit_document_links_use_the_authorized_preview_view(
    client, reviewer, submitted_application
):
    """Every document link on the page must be the reversed authorized-proxy
    URL for that application's actual document rows - not merely a page that
    happens to mention the proxy's URL prefix somewhere."""
    from apps.documents.models import Document

    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()

    member_doc = submitted_application.documents.get(
        kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
    )
    guardian_doc = submitted_application.documents.get(
        kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
    )
    portrait_doc = submitted_application.documents.get(
        kind=Document.Kind.MEMBER_PORTRAIT, deleted_at__isnull=True
    )

    for doc in (member_doc, guardian_doc, portrait_doc):
        assert reverse("documents:admin-document-preview", args=[doc.id]) in body
        assert reverse("documents:admin-document-download", args=[doc.id]) in body


def test_cockpit_offers_rotation(client, reviewer, submitted_application):
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    assert "data-viewer-rotate" in body


def test_cockpit_404s_for_an_unknown_application(client, reviewer):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:cockpit", args=[999999]))
    assert response.status_code == 404

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


def test_cockpit_approval_posts_next_to_agreement(client, reviewer, submitted_application):
    """Approval must hand off straight to the agreement Hub page: the
    approve form carries `next` = the agreement URL in both the query string
    and the hidden input, so the admin approve endpoint redirects there
    instead of back to the cockpit."""
    client.force_login(reviewer)
    cockpit_url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    agreement_url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    body = client.get(cockpit_url).content.decode()

    assert f"?next={agreement_url}" in body
    assert f'value="{agreement_url}"' in body


def test_approved_cockpit_has_no_redundant_agreement_continue_button(
    client, reviewer, approved_application
):
    """With approval landing on the agreement page directly, the cockpit's
    post-approval continuation CTA is a dead step and must be gone."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[approved_application.pk])
    ).content.decode()

    assert "Turpināt: Līgums" not in body


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

def _approve_button_tag(body: str) -> str:
    """The in-card approve button's own tag, so an assertion cannot be
    satisfied by a `disabled` belonging to some other element."""
    import re

    match = re.search(
        r"<button[^>]*>\s*Apstiprināt pieteikumu[^<]*</button>", body, re.S
    )
    assert match, "approve button not found"
    return match.group(0)


def test_step_rail_links_forward_once_an_agreement_exists(
    client, reviewer, approved_application
):
    """Steps 3-8 live on other pages, and the rail is the only place all eight
    appear together. It shipped as non-clickable text with no other forward
    link anywhere, so the agreement download and signed-copy upload were
    reachable only by typing a URL."""
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[approved_application.pk])
    body = client.get(url).content.decode()
    agreement_url = reverse("admin_hub:agreement", args=[approved_application.pk])
    billing_url = reverse("admin_hub:billing", args=[approved_application.pk])
    assert f'href="{agreement_url}"' in body
    assert f'href="{billing_url}"' in body


def test_step_rail_does_not_link_to_pages_that_would_404(
    client, reviewer, submitted_application
):
    """A submitted application has no agreement, so the agreement and billing
    views raise 404. The rail must not offer those steps as links."""
    client.force_login(reviewer)
    url = reverse("admin_hub:cockpit", args=[submitted_application.pk])
    body = client.get(url).content.decode()
    agreement_url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    assert f'href="{agreement_url}"' not in body


def test_approve_action_is_offered_for_a_submitted_application(
    client, reviewer, submitted_application
):
    """approve_application refuses anything but a submitted application, so
    offering the button regardless of status promised an action that errors.
    The bar showed "Apstiprināt pieteikumu" on every application.

    Note these are two tests, not one: approved_application is *derived from*
    submitted_application, so a single test requesting both would receive the
    same, already-approved object and assert against itself."""
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()
    assert "disabled" not in _approve_button_tag(body)


def test_approve_action_is_withdrawn_once_approved(
    client, reviewer, approved_application
):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[approved_application.pk])
    ).content.decode()
    assert "disabled" in _approve_button_tag(body)

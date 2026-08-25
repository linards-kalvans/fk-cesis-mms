"""Tests for the Agreement admin document surface and its presentation helper.

Covers:
- ``AgreementDocumentLink`` (TypedDict) + ``build_agreement_document_links``
  presentation helper (exact ``get_state_display`` / ``get_signing_path_display``
  labels, caller-side external-id filtering, history rows).
- ``AgreementAdmin`` remains non-editable (``has_change_permission=False``)
  but gains staff-only ``has_view_permission``, a custom change template, a
  document endpoint, and inline iframe preview + attachment download.

Assumption (flagged in report): the shared link item + list builder live in
``apps.agreements.presentation`` as ``AgreementDocumentLink`` (TypedDict) and
``build_agreement_document_links(agreements, *, url_builder=...)``.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member

pytestmark = pytest.mark.django_db


_AGREEMENT_STATE_CASES = [
    (Agreement.State.GENERATED, "Sagatavots"),
    (Agreement.State.SENT, "Nosūtīts parakstīšanai"),
    (Agreement.State.SIGNED, "Parakstīts"),
    (Agreement.State.VOID, "Atcelts"),
    (Agreement.State.SUPERSEDED, "Aizvietots"),
    (Agreement.State.DISCONTINUED, "Pārtraukts"),
]


# ---------------------------------------------------------------------------
# Presentation helper
# ---------------------------------------------------------------------------


def _build_links(agreements, url_builder=lambda ag: f"/dl/{ag.pk}"):
    from apps.agreements.presentation import build_agreement_document_links

    return build_agreement_document_links(agreements, url_builder=url_builder)


def test_link_is_dict_with_exact_labels_and_url(agreement_member):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.external_id = "stub-1"
    a.save(update_fields=["external_id"])

    links = _build_links([a])
    assert len(links) == 1
    link = links[0]
    assert link["agreement"] == a
    assert link["state_label"] == "Sagatavots"
    assert link["signing_path_label"] == "Elektroniski"
    assert link["download_url"] == f"/dl/{a.pk}"


@pytest.mark.parametrize("state, expected", _AGREEMENT_STATE_CASES)
def test_link_state_label_is_exact_display(agreement_member, state, expected):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.state = state
    a.external_id = "stub-1"
    a.save(update_fields=["state", "external_id"])

    links = _build_links([a])
    assert links[0]["state_label"] == expected


@pytest.mark.parametrize(
    "path, expected",
    [
        (Agreement.SigningPath.ELECTRONIC, "Elektroniski"),
        (Agreement.SigningPath.PAPER, "Ar roku, papīra dokuments"),
    ],
)
def test_link_signing_path_label_is_exact_display(agreement_member, path, expected):
    a = create_agreement_for_member(agreement_member, path)
    a.external_id = "stub-1"
    a.save(update_fields=["external_id"])

    links = _build_links([a])
    assert links[0]["signing_path_label"] == expected


def test_builds_link_for_every_agreement_passed(agreement_member):
    current = create_agreement_for_member(
        agreement_member, Agreement.SigningPath.ELECTRONIC
    )
    current.external_id = "stub-current"
    current.save(update_fields=["external_id"])

    hist = Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        state=Agreement.State.SIGNED,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        generated_at=timezone.now(),
        external_id="stub-history",
    )

    links = _build_links([current, hist])
    pks = {link["agreement"].pk for link in links}
    assert pks == {current.pk, hist.pk}


def test_helper_does_not_filter_blank_external_id(agreement_member):
    """External-id filtering is the caller's job — the helper builds a link
    for every agreement it is given, even one with a blank external_id."""
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    # external_id left blank
    links = _build_links([a])
    assert len(links) == 1
    assert links[0]["agreement"] == a
    assert links[0]["download_url"] == f"/dl/{a.pk}"


# ---------------------------------------------------------------------------
# AgreementAdmin permissions + template
# ---------------------------------------------------------------------------


@pytest.fixture
def agreement_admin():
    from django.contrib import admin

    from apps.agreements.admin import AgreementAdmin

    return AgreementAdmin(Agreement, admin.site)


@pytest.fixture
def staff_request(db):
    user = User.objects.create_user(username="viewer", is_staff=True)
    req = RequestFactory().get("/")
    req.user = user
    return req


@pytest.fixture
def agreement_staff_client(db):
    user = User.objects.create_user(
        username="staffview", is_staff=True, password="pw"
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def viewable_agreement(agreement_member):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.external_id = "stub-1"
    a.save(update_fields=["external_id"])
    return a


def test_agreement_admin_is_non_editable(agreement_admin, staff_request):
    assert agreement_admin.has_change_permission(staff_request) is False
    assert agreement_admin.has_delete_permission(staff_request) is False
    assert agreement_admin.has_add_permission(staff_request) is False


def test_agreement_admin_view_permission_is_staff_only(agreement_admin, staff_request):
    assert agreement_admin.has_view_permission(staff_request) is True
    anon = RequestFactory().get("/")
    anon.user = AnonymousUser()
    assert agreement_admin.has_view_permission(anon) is False


def test_agreement_admin_uses_custom_change_template(agreement_admin):
    assert agreement_admin.change_form_template is not None
    assert agreement_admin.change_form_template.endswith(".html")


# ---------------------------------------------------------------------------
# AgreementAdmin change page + document endpoint
# ---------------------------------------------------------------------------


def test_change_page_viewable_by_staff(agreement_staff_client, viewable_agreement):
    url = reverse("admin:agreements_agreement_change", args=[viewable_agreement.pk])
    resp = agreement_staff_client.get(url)
    assert resp.status_code == 200


def test_change_page_renders_preview_iframe_and_download(
    settings, agreement_staff_client, viewable_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    url = reverse("admin:agreements_agreement_change", args=[viewable_agreement.pk])
    resp = agreement_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    doc_url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[viewable_agreement.pk]
    )
    assert "<iframe" in html
    # The inline preview iframe must point at the named route with inline disposition.
    assert f"{doc_url}?disposition=inline" in html
    # The download anchor must point at the same route with attachment disposition.
    assert f"{doc_url}?disposition=attachment" in html
    assert "Lejupielādēt ģenerēto līgumu" in html


def test_change_page_hides_download_without_external_id(
    settings, agreement_staff_client, agreement_member
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    # No external_id
    url = reverse("admin:agreements_agreement_change", args=[a.pk])
    resp = agreement_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Lejupielādēt ģenerēto līgumu" not in html


def test_document_route_streams_pdf(
    settings, agreement_staff_client, viewable_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[viewable_agreement.pk]
    )
    resp = agreement_staff_client.get(url)
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content).startswith(b"%PDF-")


def test_document_route_inline_disposition(
    settings, agreement_staff_client, viewable_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[viewable_agreement.pk]
    )
    resp = agreement_staff_client.get(f"{url}?disposition=inline")
    assert "inline" in resp["Content-Disposition"]


def test_document_route_attachment_disposition(
    settings, agreement_staff_client, viewable_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[viewable_agreement.pk]
    )
    resp = agreement_staff_client.get(f"{url}?disposition=attachment")
    assert "attachment" in resp["Content-Disposition"]


def test_document_route_invalid_disposition_404(
    settings, agreement_staff_client, viewable_agreement
):
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[viewable_agreement.pk]
    )
    resp = agreement_staff_client.get(f"{url}?disposition=bogus")
    assert resp.status_code == 404


@pytest.mark.parametrize("state, label", _AGREEMENT_STATE_CASES)
def test_change_page_renders_state_label_preview_and_download(
    settings, agreement_staff_client, agreement_member, state, label
):
    """Real rendering: the change page must show the exact state display plus
    the inline iframe and download control for the agreement's state."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.state = state
    a.external_id = "stub-1"
    a.save(update_fields=["state", "external_id"])

    url = reverse("admin:agreements_agreement_change", args=[a.pk])
    resp = agreement_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert label in html
    assert "<iframe" in html
    assert "Lejupielādēt ģenerēto līgumu" in html


def test_change_page_does_not_leak_docuseal_url(
    settings, agreement_staff_client, agreement_member
):
    """The DocuSeal document URL must never appear in the agreement change
    page, even when external_url is stored on the row."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.external_id = "stub-1"
    a.external_url = "https://sign.example/s/abc"
    a.save(update_fields=["external_id", "external_url"])

    url = reverse("admin:agreements_agreement_change", args=[a.pk])
    resp = agreement_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "https://sign.example" not in html
    assert "sign.example" not in html
    assert "Atvērt DocuSeal" not in html


def test_document_route_no_external_id_redirects_with_message(
    settings, agreement_staff_client, agreement_member
):
    """No external id → Latvian admin message + redirect to the source
    change page (not 404)."""
    settings.AGREEMENT_PROVIDER_MODE = "stub"
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    # external_id left blank
    url = reverse("admin:agreements_agreement_docuseal_document", args=[a.pk])
    resp = agreement_staff_client.get(url, follow=True)
    assert resp.status_code == 200
    assert "DocuSeal sūtījums vēl nav izveidots" in resp.content.decode()


def test_document_route_provider_error_redirects_with_latvian_message(
    settings, agreement_staff_client, viewable_agreement
):
    """A provider error must surface a fixed Latvian generic error on the
    source page — never the raw provider exception text."""
    from apps.integrations import agreement_platform as ap

    settings.AGREEMENT_PROVIDER_MODE = "stub"
    url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[viewable_agreement.pk]
    )
    with patch(
        "apps.integrations.agreement_platform.stream_submission_document",
        side_effect=ap.AgreementPlatformNotFoundError("gone"),
        create=True,
    ):
        resp = agreement_staff_client.get(url, follow=True)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Radās kļūda saziņā ar DocuSeal" in html
    assert "gone" not in html

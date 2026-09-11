"""P16-A: read-only Agreement admin signed-artifact panel + serve tests.

Covers:

* ``AgreementAdmin`` stays read-only (no add / change / delete).
* Staff with view permission can use the named signed-artifact route
  (``admin:agreements_agreement_signed_artifact``) and see an independent
  signed-artifact panel only when a file exists.
* Existing DocuSeal generated-document iframe/link behavior is preserved.
* Nonstaff cannot serve.

Red-phase discipline: route, panel context, and the artifact fields are
absent until implementation; every test asserts existence first.
"""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, User
from django.core.files.base import ContentFile
from django.test import Client, RequestFactory
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.agreements.admin import AgreementAdmin
from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member

pytestmark = pytest.mark.django_db


def _resolve(name, args=()):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return None


def _artifact_url(agreement):
    return _resolve("admin:agreements_agreement_signed_artifact", (agreement.pk,))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agreement(agreement_member):
    return create_agreement_for_member(agreement_member, Agreement.SigningPath.PAPER)


@pytest.fixture
def agreement_admin():
    return AgreementAdmin(Agreement, admin.site)


@pytest.fixture
def staff_request(db):
    user = User.objects.create_user(username="artifact-viewer", is_staff=True)
    req = RequestFactory().get("/")
    req.user = user
    return req


@pytest.fixture
def view_staff_client(db):
    """Authenticated staff user with view (but no change) permission."""
    user = User.objects.create_user(username="viewer", is_staff=True, password="pw")
    client = Client()
    client.force_login(user)
    return client


def _store(agreement, filename, body, content_type):
    assert hasattr(Agreement, "signed_artifact")
    agreement.signed_artifact.save(filename, ContentFile(body), save=False)
    agreement.signed_artifact_original_filename = filename
    agreement.signed_artifact_content_type = content_type
    agreement.signed_artifact_file_size = len(body)
    now = timezone.now()
    agreement.signed_artifact_uploaded_at = agreement.signed_artifact_uploaded_at or now
    agreement.signed_artifact_updated_at = now
    agreement.save(
        update_fields=[
            "signed_artifact",
            "signed_artifact_original_filename",
            "signed_artifact_content_type",
            "signed_artifact_file_size",
            "signed_artifact_uploaded_at",
            "signed_artifact_updated_at",
            "updated_at",
        ]
    )
    agreement.refresh_from_db()
    return agreement


# ---------------------------------------------------------------------------
# Read-only posture (requirement 7)
# ---------------------------------------------------------------------------


def test_agreement_admin_remains_read_only_no_add_no_delete(agreement_admin, staff_request):
    assert agreement_admin.has_change_permission(staff_request) is False
    assert agreement_admin.has_delete_permission(staff_request) is False
    assert agreement_admin.has_add_permission(staff_request) is False


def test_view_permission_is_staff_only(agreement_admin, staff_request):
    assert agreement_admin.has_view_permission(staff_request) is True
    anon = RequestFactory().get("/")
    anon.user = AnonymousUser()
    assert agreement_admin.has_view_permission(anon) is False


def test_signed_artifact_route_resolves(agreement):
    assert _artifact_url(agreement) is not None


# ---------------------------------------------------------------------------
# Change-page panel (requirement 7)
# ---------------------------------------------------------------------------


def test_change_page_renders_signed_artifact_panel_only_when_file_exists(
    view_staff_client, agreement,
):
    assert _artifact_url(agreement) is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    url = reverse("admin:agreements_agreement_change", args=[agreement.pk])
    resp = view_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()

    assert "Parakstītais dokuments" in html
    assert "Status nav pieejams" in html
    artifact_url = _artifact_url(agreement)
    assert f"{artifact_url}?disposition=inline" in html
    assert f"{artifact_url}?disposition=attachment" in html


def test_change_page_hides_signed_artifact_panel_without_file(
    view_staff_client, agreement,
):
    url = reverse("admin:agreements_agreement_change", args=[agreement.pk])
    resp = view_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Parakstītais dokuments" not in html
    assert "Status nav pieejams" not in html


def test_change_page_preserves_docuseal_iframe_and_download_behavior(
    view_staff_client, agreement,
):
    """Existing DocuSeal inline-iframe + download controls stay intact beside
    the new signed-artifact panel — two distinct same-origin routes."""
    assert _artifact_url(agreement) is not None
    agreement.external_id = "stub-1"
    agreement.save(update_fields=["external_id"])
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    url = reverse("admin:agreements_agreement_change", args=[agreement.pk])
    resp = view_staff_client.get(url)
    assert resp.status_code == 200
    html = resp.content.decode()

    docuseal_url = reverse(
        "admin:agreements_agreement_docuseal_document", args=[agreement.pk]
    )
    assert "<iframe" in html
    assert f"{docuseal_url}?disposition=inline" in html
    assert f"{docuseal_url}?disposition=attachment" in html
    assert "Lejupielādēt ģenerēto līgumu" in html
    # Independent signed-artifact panel still present.
    assert "Parakstītais dokuments" in html
    assert _artifact_url(agreement) in html


def test_change_page_never_exposes_raw_storage_url(
    view_staff_client, agreement,
):
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    url = reverse("admin:agreements_agreement_change", args=[agreement.pk])
    resp = view_staff_client.get(url)
    html = resp.content.decode()
    assert "agreements/signed/" not in html
    assert "private-uploads" not in html


# ---------------------------------------------------------------------------
# Serve route (requirement 7)
# ---------------------------------------------------------------------------


def test_staff_with_view_permission_can_serve_pdf_inline(
    view_staff_client, agreement,
):
    assert _artifact_url(agreement) is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    resp = view_staff_client.get(_artifact_url(agreement))
    assert resp.status_code == 200
    assert "inline" in resp["Content-Disposition"]
    assert resp["Content-Type"] == "application/pdf"


def test_edoc_serve_is_attachment(view_staff_client, agreement):
    assert _artifact_url(agreement) is not None
    _store(agreement, "signed.edoc", b"EDOC-2026", "")
    resp = view_staff_client.get(_artifact_url(agreement))
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]


def test_nonstaff_cannot_serve(agreement):
    assert _artifact_url(agreement) is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    resp = Client().get(_artifact_url(agreement))
    assert resp.status_code in (302, 403)


def test_serve_blank_artifact_is_404(view_staff_client, agreement):
    assert _artifact_url(agreement) is not None
    resp = view_staff_client.get(_artifact_url(agreement))
    assert resp.status_code == 404


def test_serve_invalid_disposition_is_404(view_staff_client, agreement):
    assert _artifact_url(agreement) is not None
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    resp = view_staff_client.get(f"{_artifact_url(agreement)}?disposition=bogus")
    assert resp.status_code == 404
"""P16-A: family-hub signed-artifact listing + guardian-scoped proxy tests.

Covers:

* the guardian-scoped staff route
  ``admin:members_guardian_signed_artifact``;
* the hub listing every member's Agreement artifacts — current, superseded,
  voided and discontinued — newest first per member;
* guardian → member → Agreement ownership: any mismatch is a 404;
* the existing DocuSeal document list stays a distinct region.

Red-phase discipline: the route and the hub's artifact links are absent
until implementation; every test asserts existence first.
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def _resolve(name, args=()):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return None


def _proxy_url(guardian, agreement):
    return _resolve("admin:members_guardian_signed_artifact", (guardian.pk, agreement.pk))


def _hub_url(guardian):
    return reverse("admin:members_guardian_family_hub", args=[guardian.pk])


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def family_members(guardian, member):
    """Two members under the shared guardian, plus member-scoped agreements."""
    m2 = Member.objects.create(full_name="Otrs Bērns", guardian=guardian)
    t0 = timezone.now()
    current = Agreement.objects.create(
        member=member,
        is_current=True,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    superseded = Agreement.objects.create(
        member=member,
        is_current=False,
        state=Agreement.State.SUPERSEDED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    voided = Agreement.objects.create(
        member=m2,
        is_current=True,
        state=Agreement.State.VOID,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    discontinued = Agreement.objects.create(
        member=m2,
        is_current=False,
        state=Agreement.State.DISCONTINUED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    return {
        "current": current,
        "superseded": superseded,
        "voided": voided,
        "discontinued": discontinued,
    }


@pytest.fixture
def foreign_agreement(db):
    """An Agreement belonging to a different guardian's member."""
    from tests.support import make_guardian

    other_guardian = make_guardian(full_name="Cits Vecāks")
    other_member = Member.objects.create(
        full_name="Cits Bērns", guardian=other_guardian
    )
    agreement = Agreement.objects.create(
        member=other_member,
        is_current=True,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=timezone.now(),
    )
    return other_guardian, agreement


@pytest.fixture
def plain_staff_client(db):
    user = User.objects.create_user(username="hub-plain", is_staff=True, password="pw")
    client = Client()
    client.force_login(user)
    return client


def _store(agreement, filename, body, content_type, *, at=None):
    assert hasattr(Agreement, "signed_artifact")
    agreement.signed_artifact.save(filename, ContentFile(body), save=False)
    agreement.signed_artifact_original_filename = filename
    agreement.signed_artifact_content_type = content_type
    agreement.signed_artifact_file_size = len(body)
    now = at or timezone.now()
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
# Route + listing (requirement 8)
# ---------------------------------------------------------------------------


def test_family_hub_signed_artifact_route_resolves(guardian, family_members):
    assert _proxy_url(guardian, family_members["current"]) is not None


def test_family_hub_lists_every_members_artifact_newest_first_per_member(
    staff_client, guardian, family_members,
):
    assert hasattr(Agreement, "signed_artifact")
    t0 = timezone.now()
    # member 1: current is newer than superseded; member 2: voided newer than
    # discontinued. All four lifecycle states carry artifacts.
    _store(
        family_members["superseded"], "older.pdf", b"%PDF-", "application/pdf",
        at=t0 - timezone.timedelta(days=2),
    )
    _store(
        family_members["current"], "newest.pdf", b"%PDF-", "application/pdf",
        at=t0 - timezone.timedelta(days=1),
    )
    _store(
        family_members["discontinued"], "oldest.edoc", b"EDOC", "",
        at=t0 - timezone.timedelta(days=4),
    )
    _store(
        family_members["voided"], "voided.pdf", b"%PDF-", "application/pdf",
        at=t0 - timezone.timedelta(days=3),
    )

    resp = staff_client.get(_hub_url(guardian))
    assert resp.status_code == 200
    html = resp.content.decode()

    proxy_urls = {
        key: _proxy_url(guardian, agreement)
        for key, agreement in family_members.items()
    }
    assert all(url is not None for url in proxy_urls.values())
    for url in proxy_urls.values():
        assert url in html
    assert "Status nav pieejams" in html

    # Newest-first per member: member1 current before superseded.
    assert html.index(proxy_urls["current"]) < html.index(proxy_urls["superseded"])
    # Newest-first per member: member2 voided before discontinued.
    assert html.index(proxy_urls["voided"]) < html.index(proxy_urls["discontinued"])


def test_family_hub_requires_change_permission(
    guardian, family_members, plain_staff_client,
):
    assert Client().get(_hub_url(guardian)).status_code in (302, 403)
    assert plain_staff_client.get(_hub_url(guardian)).status_code == 403


def test_family_hub_docuseal_list_stays_distinct(
    staff_client, guardian, family_members,
):
    assert hasattr(Agreement, "signed_artifact")
    agreement = family_members["current"]
    agreement.external_id = "stub-docuseal"
    agreement.save(update_fields=["external_id"])
    _store(agreement, "signed.pdf", b"%PDF-1.7\n", "application/pdf")

    resp = staff_client.get(_hub_url(guardian))
    assert resp.status_code == 200
    html = resp.content.decode()

    # DocuSeal generated-document list intact…
    assert "Lejupielādēt ģenerēto līgumu" in html
    docuseal_url = reverse(
        "admin:members_guardian_docuseal_document", args=[guardian.pk, agreement.pk]
    )
    assert docuseal_url in html
    # …and the signed-artifact proxy is a separate route.
    assert _proxy_url(guardian, agreement) in html
    assert _proxy_url(guardian, agreement) != docuseal_url


# ---------------------------------------------------------------------------
# Proxy ownership + serving (requirements 5, 8)
# ---------------------------------------------------------------------------


def test_proxy_serves_owned_pdf_as_attachment(staff_client, guardian, family_members):
    assert _proxy_url(guardian, family_members["current"]) is not None
    _store(family_members["current"], "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    resp = staff_client.get(_proxy_url(guardian, family_members["current"]))
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]
    assert resp["Content-Type"] == "application/pdf"


def test_proxy_serves_owned_edoc_as_attachment(staff_client, guardian, family_members):
    assert _proxy_url(guardian, family_members["current"]) is not None
    _store(family_members["current"], "signed.edoc", b"EDOC-2026", "")
    resp = staff_client.get(_proxy_url(guardian, family_members["current"]))
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]


def test_proxy_foreign_guardians_agreement_is_404(
    staff_client, guardian, foreign_agreement, family_members,
):
    other_guardian, agreement = foreign_agreement
    assert hasattr(Agreement, "signed_artifact")
    _store(agreement, "foreign.pdf", b"%PDF-", "application/pdf")
    url = _proxy_url(guardian, agreement)
    assert url is not None
    assert staff_client.get(url).status_code == 404
    # Same guardian's own agreement served from the other guardian route? The
    # ownership chain is guardian-scoped: fetching guardian1's agreement via
    # guardian2's hub must also 404.
    url = _resolve(
        "admin:members_guardian_signed_artifact",
        (other_guardian.pk, family_members["current"].pk),
    )
    assert url is not None
    assert staff_client.get(url).status_code == 404


def test_proxy_missing_agreement_is_404(staff_client, guardian, family_members):
    assert _proxy_url(guardian, family_members["current"]) is not None
    resp = staff_client.get(_proxy_url(guardian, family_members["current"]))
    assert resp.status_code == 404


def test_proxy_blank_artifact_is_404(staff_client, guardian, member, family_members):
    # Agreement without a stored file.
    agreement = Agreement.objects.create(
        member=member,
        is_current=False,
        state=Agreement.State.SUPERSEDED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=timezone.now(),
    )
    url = _proxy_url(guardian, agreement)
    assert url is not None
    assert staff_client.get(url).status_code == 404
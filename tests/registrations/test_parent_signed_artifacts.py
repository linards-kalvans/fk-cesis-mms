"""P16-A: guardian parent-portal signed-artifact section + proxy tests.

Covers:

* portal section rendered only when at least one owned artifact exists,
  grouped per member and newest first, with same-origin links only;
* the proxy route ``registrations:parent-signed-artifact``: no parent
  session redirects to registration start; own artifact is always
  attachment; foreign / missing / blank artifact and inline-disposition
  attempts are 404; no raw storage/provider URL reaches the guardian;
* application and invoice content stay on the portal page.

Red-phase discipline: route, portal section, and artifact fields are
absent until implementation; every test asserts existence first.
"""

from __future__ import annotations

import pytest
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


def _proxy_url(agreement):
    return _resolve("registrations:parent-signed-artifact", (agreement.pk,))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def portal_family(parent_account, make_guardian):
    """Guardian + two members + agreements with artifacts under the parent."""
    guardian = make_guardian(parent_account, full_name="Portāla Vecāks")
    m1 = Member.objects.create(full_name="Bērns Viens", guardian=guardian)
    m2 = Member.objects.create(full_name="Bērns Otrs", guardian=guardian)
    t0 = timezone.now()
    newest = Agreement.objects.create(
        member=m1,
        is_current=True,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    older = Agreement.objects.create(
        member=m1,
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
    return {"newest": newest, "older": older, "voided": voided}


@pytest.fixture
def foreign_agreement(other_parent_account, make_guardian):
    """An artifact belonging to a different parent's family."""
    other_guardian = make_guardian(other_parent_account, full_name="Cits Vecāks")
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
    return agreement


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
# Proxy route (requirement 9)
# ---------------------------------------------------------------------------


def test_parent_signed_artifact_route_resolves(portal_family):
    assert _proxy_url(portal_family["newest"]) is not None


def test_no_parent_session_redirects_to_registration_start(portal_family):
    assert _proxy_url(portal_family["newest"]) is not None
    resp = Client().get(_proxy_url(portal_family["newest"]))
    assert resp.status_code == 302
    assert resp.url == reverse("registrations:start-registration")


def test_own_pdf_is_attachment_never_inline(verified_client, portal_family):
    assert _proxy_url(portal_family["newest"]) is not None
    _store(portal_family["newest"], "signed.pdf", b"%PDF-1.7\n", "application/pdf")
    url = _proxy_url(portal_family["newest"])
    resp = verified_client.get(url)
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]
    assert "inline" not in resp["Content-Disposition"]
    # Guardian must never receive an inline response — inline attempts 404.
    assert verified_client.get(f"{url}?disposition=inline").status_code == 404


def test_own_edoc_is_attachment(verified_client, portal_family):
    assert _proxy_url(portal_family["newest"]) is not None
    _store(portal_family["newest"], "signed.edoc", b"EDOC-2026", "")
    resp = verified_client.get(_proxy_url(portal_family["newest"]))
    assert resp.status_code == 200
    assert "attachment" in resp["Content-Disposition"]


def test_foreign_agreement_is_404(verified_client, foreign_agreement):
    assert _proxy_url(foreign_agreement) is not None
    _store(foreign_agreement, "foreign.pdf", b"%PDF-", "application/pdf")
    assert verified_client.get(_proxy_url(foreign_agreement)).status_code == 404


def test_missing_agreement_is_404(verified_client):
    url = _resolve("registrations:parent-signed-artifact", (999999,))
    assert url is not None
    assert verified_client.get(url).status_code == 404


def test_blank_artifact_is_404(verified_client, portal_family):
    assert _proxy_url(portal_family["newest"]) is not None
    assert verified_client.get(_proxy_url(portal_family["newest"])).status_code == 404


# ---------------------------------------------------------------------------
# Portal section (requirement 9)
# ---------------------------------------------------------------------------


def test_portal_shows_section_grouped_per_member_newest_first(
    verified_client, parent_account, portal_family,
):
    from apps.registrations.services import create_or_update_draft

    create_or_update_draft(
        data={"guardian_email": parent_account.email},
        files={},
        verified_account=parent_account,
    )
    assert hasattr(Agreement, "signed_artifact")
    t0 = timezone.now()
    _store(
        portal_family["older"], "older.pdf", b"%PDF-", "application/pdf",
        at=t0 - timezone.timedelta(days=2),
    )
    _store(
        portal_family["newest"], "newest.pdf", b"%PDF-", "application/pdf",
        at=t0 - timezone.timedelta(days=1),
    )
    _store(portal_family["voided"], "voided.edoc", b"EDOC", "")

    resp = verified_client.get(reverse("registrations:parent-portal"))
    assert resp.status_code == 200
    html = resp.content.decode()

    assert "Parakstītie līgumi" in html
    assert "Status nav pieejams" in html
    # Grouped per member — both child names render in the section.
    assert "Bērns Viens" in html
    assert "Bērns Otrs" in html

    newest_url = _proxy_url(portal_family["newest"])
    older_url = _proxy_url(portal_family["older"])
    voided_url = _proxy_url(portal_family["voided"])
    assert newest_url in html
    assert older_url in html
    assert voided_url in html
    # Newest-first per member.
    assert html.index(newest_url) < html.index(older_url)
    # Same-origin links only — no absolute http(s) artifact URL anywhere.
    assert f"http://{resp.wsgi_request.get_host()}{newest_url}" not in html

    # Raw storage / provider URLs never leak.
    assert "agreements/signed/" not in html
    assert "private-uploads" not in html
    assert "sign.example" not in html

    # Application + invoice content preserved, artifact section between them.
    assert "Mani pieteikumi" in html
    assert "Mani rēķini" in html
    assert html.index("Parakstītie līgumi") > html.index("Pieteikumu saraksts")
    assert html.index("Parakstītie līgumi") < html.index("Mani rēķini")


def test_portal_hides_section_when_no_artifacts(
    verified_client, portal_family,
):
    resp = verified_client.get(reverse("registrations:parent-portal"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Parakstītie līgumi" not in html
    assert "Status nav pieejams" not in html


def test_portal_does_not_list_foreign_artifact(
    verified_client, portal_family, foreign_agreement,
):
    assert hasattr(Agreement, "signed_artifact")
    _store(portal_family["newest"], "own.pdf", b"%PDF-", "application/pdf")
    _store(foreign_agreement, "foreign.pdf", b"%PDF-", "application/pdf")

    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode()
    assert _proxy_url(portal_family["newest"]) in html
    assert _proxy_url(foreign_agreement) not in html


def test_artifact_groups_keep_equal_member_names_distinct(
    parent_account, make_guardian,
):
    """Grouping must be per member identity, not per display name: two owned
    members with identical ``full_name`` each get their own group with one
    artifact, never a single merged group."""
    from apps.registrations import views as registrations_views

    groups_fn = getattr(registrations_views, "_parent_artifact_groups", None)
    assert groups_fn is not None, "P16-A _parent_artifact_groups missing"
    assert hasattr(Agreement, "signed_artifact")

    guardian = make_guardian(parent_account, full_name="Twin Parent")
    t0 = timezone.now()
    m1 = Member.objects.create(full_name="Twin Child", guardian=guardian)
    m2 = Member.objects.create(full_name="Twin Child", guardian=guardian)
    a1 = Agreement.objects.create(
        member=m1,
        is_current=True,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    a2 = Agreement.objects.create(
        member=m2,
        is_current=True,
        state=Agreement.State.GENERATED,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=t0,
    )
    _store(a1, "one.pdf", b"%PDF-", "application/pdf")
    _store(a2, "two.pdf", b"%PDF-", "application/pdf")

    groups = groups_fn(parent_account)
    assert len(groups) == 2, f"expected two distinct groups, got {groups!r}"
    artifact_counts = sorted(len(group["artifacts"]) for group in groups)
    assert artifact_counts == [1, 1]
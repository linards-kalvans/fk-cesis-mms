"""P2 Task 3 — Canonical application workspace route contract.

Covers:
- Owner can open /applications/<id>/ (200) with child/application context.
- Non-owner gets 404 on /applications/<id>/.
- Legacy edit/summary/detail routes redirect to canonical workspace (302).
- Submitted application workspace is read-only (no save-draft/submit buttons).
- POST to read-only workspace returns 404.
- POST to editable workspace saves draft and redirects.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft, submit_application

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: Client, account: ParentAccount) -> None:
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_guardian_identity_file(name="guardian.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_member_identity_file(name="member.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_member_portrait_file(name="portrait.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _ensure_kit_sizes():
    """Create kit size options if they don't already exist."""
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        defaults={"label": "S", "is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        defaults={"label": "S", "is_active": True},
    )
    return shirt.pk, shorts.pk


def _make_workspace_draft(email="workspace@example.com", child_name="Workspace Child"):
    """Create a verified draft application and return (account, application)."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37120000000",
    )
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Workspace Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga 1",
            "member_full_name": child_name,
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=acct,
    )
    return acct, app


def _make_submitted_app(email="readonly@example.com", child_name="Readonly Child"):
    """Create a fully submitted application and return (account, application)."""
    shirt_pk, shorts_pk = _ensure_kit_sizes()
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37120000004",
    )
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Readonly Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000004",
            "guardian_declared_address": "Riga 1",
            "member_full_name": child_name,
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
            "member_same_address_as_guardian": True,
            "preferred_agreement_signing": "paper",
            "member_kit_size_shirt": shirt_pk,
            "member_kit_size_shorts": shorts_pk,
        },
        files={
            "guardian_identity_document": _make_guardian_identity_file("guardian.png"),
            "member_identity_document": _make_member_identity_file("member.png"),
            "member_portrait_document": _make_member_portrait_file("portrait.png"),
        },
        verified_account=acct,
    )
    submit_application(app, acct)
    return acct, app


# ===========================================================================
# 1. Canonical workspace route — owner access
# ===========================================================================


class TestCanonicalWorkspaceRoute:
    """Owner must be able to open /applications/<id>/ and see child/application context."""

    def test_owner_can_open_canonical_workspace_route(self):
        """GET /applications/<id>/ must return 200 for the owning parent."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Workspace Child" in content

    def test_non_owner_gets_404_on_canonical_workspace_route(self):
        """GET /applications/<id>/ must return 404 for a non-owning parent."""
        owner_acct, app = _make_workspace_draft("owner@example.com", "Owner Child")
        stranger = ParentAccount.objects.create(
            email="stranger@example.com",
            phone="+37120000002",
        )
        stranger_client = Client()
        _login(stranger_client, stranger)

        resp = stranger_client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 404


# ===========================================================================
# 2. Legacy route redirects to canonical workspace
# ===========================================================================


class TestLegacyRouteRedirects:
    """Old edit/summary/detail routes must redirect to /applications/<id>/."""

    def setup_method(self):
        self.client = Client()

    def _create_draft_and_login(self, email="redirect@example.com"):
        acct, app = _make_workspace_draft(email)
        _login(self.client, acct)
        return acct, app

    def test_edit_route_redirects_to_canonical_workspace(self):
        """GET /applications/<id>/edit/ must redirect (302) to /applications/<id>/."""
        acct, app = self._create_draft_and_login()

        resp = self.client.get(f"/applications/{app.pk}/edit/")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/applications/{app.pk}/")

    def test_summary_route_redirects_to_canonical_workspace(self):
        """GET /applications/<id>/summary/ must redirect (302) to /applications/<id>/."""
        acct, app = self._create_draft_and_login()

        resp = self.client.get(f"/applications/{app.pk}/summary/")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/applications/{app.pk}/")

    def test_detail_route_redirects_to_canonical_workspace(self):
        """GET /applications/<id>/detail/ must redirect (302) to /applications/<id>/."""
        acct, app = self._create_draft_and_login()

        resp = self.client.get(f"/applications/{app.pk}/detail/")

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith(f"/applications/{app.pk}/")


# ===========================================================================
# 3. Submitted application workspace is read-only
# ===========================================================================


class TestSubmittedApplicationReadOnly:
    """Submitted application workspace must not show save-draft or submit actions."""

    def test_submitted_application_workspace_is_read_only(self):
        """Workspace for submitted app must not contain save-draft or submit buttons."""
        client = Client()
        acct, app = _make_submitted_app()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        content = resp.content.decode()

        assert resp.status_code == 200
        assert "Saglabāt melnrakstu" not in content
        assert "Iesniegt pieteikumu" not in content
        assert "Iesniegts" in content or "submitted" in content.lower()

    def test_post_to_readonly_workspace_returns_404(self):
        """POST to workspace for submitted app must return 404."""
        client = Client()
        acct, app = _make_submitted_app()
        _login(client, acct)

        resp = client.post(
            f"/applications/{app.pk}/",
            {
                "guardian_full_name": "Readonly Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_email": acct.email,
                "guardian_phone": "+37120000004",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Readonly Child",
                "member_personal_id": "010125-54321",
                "member_birth_date": "2025-01-01",
                "member_same_address_as_guardian": True,
                "preferred_agreement_signing": "paper",
            },
        )

        assert resp.status_code == 404


# ===========================================================================
# 4. Editable workspace allows save and submit
# ===========================================================================


class TestEditableWorkspaceActions:
    """Editable workspace must show save-draft and submit buttons,
    and POST must save draft and redirect."""

    def test_editable_workspace_shows_submit_button(self):
        """Draft workspace must contain the submit button."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        content = resp.content.decode()

        assert resp.status_code == 200
        assert "Iesniegt pieteikumu" in content

    def test_editable_workspace_post_saves_draft_and_redirects(self):
        """POST with save_draft action must save and redirect to workspace."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.post(
            f"/applications/{app.pk}/",
            {
                "guardian_full_name": "Updated Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_email": acct.email,
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 2",
                "member_full_name": "Updated Child",
                "member_personal_id": "010125-54321",
                "member_birth_date": "2025-01-01",
                "preferred_agreement_signing": "paper",
                "submit_action": "save_draft",
            },
        )

        assert resp.status_code == 302
        assert f"/applications/{app.pk}/" in resp.headers["Location"]
        app.refresh_from_db()
        assert app.guardian_name == "Updated Parent"
        assert app.status == "draft"

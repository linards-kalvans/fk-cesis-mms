"""P2 Task 1 — Canonical application workspace route contract.

Covers:
- Owner can open /applications/<id>/ (200) with child/application context.
- Non-owner gets 404 on /applications/<id>/.
- Legacy edit route redirects to canonical workspace (302).
- Submitted application workspace is read-only (no save-draft/submit buttons).
- Workspace page uses shared parent shell hooks from Task 2.
- Workspace page loads parent CSS assets via base template.
- Editable workspace page uses new shell hooks, not orphaned old ones only.
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


# ===========================================================================
# 4. Workspace page uses shared parent shell hooks (Task 2 contract)
# ===========================================================================


class TestWorkspaceParentShellHooks:
    """Workspace page must render inside the shared parent-page shell.

    The canonical application workspace at /applications/<id>/ must extend
    parent_ui/base_parent_page.html (or otherwise include its hooks) so that
    it shares the consistent fk-parent-page wrapper and fk-site-header
    component introduced in Task 2.
    """

    def test_workspace_has_fk_parent_page_wrapper(self):
        """Workspace page must contain 'fk-parent-page' CSS hook."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert "fk-parent-page" in content, (
            "Workspace page must use fk-parent-page shell wrapper from "
            "parent_ui/base_parent_page.html."
        )

    def test_workspace_has_fk_site_header(self):
        """Workspace page must contain 'fk-site-header' CSS hook."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert "fk-site-header" in content, (
            "Workspace page must include fk-site-header from "
            "parent_ui/includes/header.html."
        )


# ===========================================================================
# 5. Workspace page loads Task 2 CSS assets via base template
# ===========================================================================


class TestWorkspaceCssAssets:
    """Workspace page must inherit parent CSS assets from base template.

    Since the workspace should extend parent_ui/base_parent_page.html which
    in turn extends base.html, the response must include the parent theme
    and parent pages CSS links.
    """

    def test_workspace_includes_parent_theme_css(self):
        """Workspace response must contain parent_theme.css link."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert "parent_theme.css" in content, (
            "Workspace page must include css/parent_theme.css via base template."
        )

    def test_workspace_includes_parent_pages_css(self):
        """Workspace response must contain parent_pages.css link."""
        client = Client()
        acct, app = _make_workspace_draft()
        _login(client, acct)

        resp = client.get(f"/applications/{app.pk}/")
        assert resp.status_code == 200

        content = resp.content.decode()
        assert "parent_pages.css" in content, (
            "Workspace page must include css/parent_pages.css via base template."
        )


# ===========================================================================
# 6. Editable workspace uses new shell hooks (not orphaned old ones only)
# ===========================================================================


class TestEditableWorkspaceShellContract:
    """Editable workspace must use the new parent-ui shell, not only
    the old fk-parent-shell orphaned class.

    The workspace template should extend parent_ui/base_parent_page.html
    so that it gets fk-parent-page and fk-site-header from the shared
    primitive system.
    """

    def test_workspace_template_extends_parent_ui_base(self):
        """application_workspace.html must extend parent_ui/base_parent_page.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "application_workspace.html"
        content = tpl.read_text()
        assert "parent_ui/base_parent_page.html" in content, (
            "application_workspace.html must extend parent_ui/base_parent_page.html "
            "to inherit fk-parent-page shell and fk-site-header."
        )

    def test_edit_template_extends_parent_ui_base(self):
        """edit_registration.html must extend parent_ui/base_parent_page.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "edit_registration.html"
        content = tpl.read_text()
        assert "parent_ui/base_parent_page.html" in content, (
            "edit_registration.html must extend parent_ui/base_parent_page.html "
            "to inherit fk-parent-page shell and fk-site-header."
        )

"""Task 2 — Shared parent shell and redesigned register/verify/portal pages.

Covers Task 2 acceptance criteria from the approved 2026-05-11 P2 plan:
- AC1: Base template includes new parent-facing assets (Google fonts, tokens.css, parent_theme.css, parent_pages.css)
- AC2: Register page uses new shared parent-page shell (fk-parent-page, fk-site-header)
- AC3: Verify page redesigned (secure framing, pending email, code form)
- AC4: Portal redesigned (hero summary, primary CTA, start-new CTA, empty state, status cards)
- AC5: Verified entry behavior remains functional

Strategy:
- Assert stable text hooks and high-level shell hooks (fk-parent-page, fk-site-header).
- Do not assert exact DOM nesting or element depth.
- Tests target new UI structure introduced by Task 2.
"""

import pytest
from django.core import mail
from django.test import Client

from apps.accounts.models import ParentAccount

from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_via_magic_link(client, account):
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _create_and_login(email="visualex@example.com"):
    """Create a ParentAccount, log in, return (client, account)."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37111111111",
    )
    client = Client()
    _login_via_magic_link(client, acct)
    return client, acct


# ===========================================================================
# AC1 — Base template includes new parent-facing assets
# ===========================================================================


class TestBaseTemplateAssets:
    """Base template must include Google fonts and parent CSS links."""

    def test_base_template_links_anton_font(self):
        """Base template must link Google Anton font."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Anton" in content, (
            "Base template must include Google Anton font link."
        )

    def test_base_template_links_inter_font(self):
        """Base template must link Google Inter font."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Inter" in content, (
            "Base template must include Google Inter font link."
        )

    def test_base_template_links_tokens_css(self):
        """Base template must link tokens.css."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "tokens.css" in content, (
            "Base template must link style-guide/tokens.css."
        )

    def test_base_template_links_parent_theme_css(self):
        """Base template must link parent_theme.css."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "parent_theme.css" in content, (
            "Base template must link css/parent_theme.css."
        )

    def test_base_template_links_parent_pages_css(self):
        """Base template must link parent_pages.css."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "parent_pages.css" in content, (
            "Base template must link css/parent_pages.css."
        )

    def test_base_template_tokens_css_is_absolute_path(self):
        """tokens.css must be linked with absolute /static/ path."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'href="/static/style-guide/tokens.css"' in content, (
            "tokens.css must use absolute {% static %} path."
        )

    def test_base_template_parent_theme_css_is_absolute_path(self):
        """parent_theme.css must be linked with absolute /static/ path."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'href="/static/css/parent_theme.css"' in content, (
            "parent_theme.css must use absolute {% static %} path."
        )

    def test_base_template_parent_pages_css_is_absolute_path(self):
        """parent_pages.css must be linked with absolute /static/ path."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'href="/static/css/parent_pages.css"' in content, (
            "parent_pages.css must use absolute {% static %} path."
        )

    def test_base_template_google_fonts_use_preconnect(self):
        """Google font links must use preconnect to fonts.googleapis.com."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fonts.googleapis.com" in content, (
            "Google fonts must be linked via fonts.googleapis.com."
        )
        assert "preconnect" in content, (
            "Google font links must include preconnect hints."
        )


# ===========================================================================
# AC2 — Register page uses new shared parent-page shell
# ===========================================================================


class TestRegisterPageParentShell:
    """Register page must render inside the new fk-parent-page shell."""

    def test_register_page_has_fk_parent_page_wrapper(self):
        """Register page must contain 'fk-parent-page' CSS hook."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode(), (
            "Register page must use fk-parent-page shell wrapper."
        )

    def test_register_page_has_fk_site_header(self):
        """Register page must contain 'fk-site-header' CSS hook."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "fk-site-header" in resp.content.decode(), (
            "Register page must include fk-site-header component."
        )

    def test_register_page_has_fk_cesis_branding(self):
        """Register page must contain 'FK Cēsis' branding text."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "FK Cēsis" in resp.content.decode()

    def test_register_page_has_bernas_registracija_heading(self):
        """Register page must contain 'Bērna reģistrācija' heading."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert "Bērna reģistrācija" in resp.content.decode()

    def test_register_page_has_primary_button(self):
        """Register page must contain a primary CTA button."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-button" in content and "primary" in content, (
            "Register page must contain a primary CTA button."
        )


# ===========================================================================
# AC2 continued — Register page keeps secure guidance text
# ===========================================================================


class TestRegisterPageGuidance:
    """Register page must explain secure verification and make email step obvious."""

    def test_register_page_explains_secure_verification(self):
        """Register page must contain 'Droša piekļuve' guidance text."""
        resp = Client().get("/register/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Droša piekļuve" in content

    def test_register_page_email_step_is_obvious(self):
        """Register page must contain 'E-pasts' label."""
        resp = Client().get("/register/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "E-pasts" in content

    def test_register_page_has_email_input(self):
        """Register page must render an email input field."""
        resp = Client().get("/register/")
        content = resp.content.decode()
        assert "email" in content.lower()


# ===========================================================================
# AC3 — Verify page redesigned behavior
# ===========================================================================


class TestVerifyPageRedesign:
    """Verify page must show secure verification framing and pending email."""

    def test_verify_page_has_fk_parent_page_wrapper(self):
        """Verify page must use fk-parent-page shell."""
        client = Client()
        client.post("/register/", {"email": "verifyredesign@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode(), (
            "Verify page must use fk-parent-page shell wrapper."
        )

    def test_verify_page_has_secure_verification_framing(self):
        """Verify page must contain 'Droša piekļuve' text."""
        client = Client()
        client.post("/register/", {"email": "verifyredesign@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Droša piekļuve" in content, (
            "Verify page must show secure verification framing text."
        )

    def test_verify_page_shows_pending_email(self):
        """Verify page must display the pending verification email."""
        client = Client()
        client.post("/register/", {"email": "pending@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "pending@example.com" in content, (
            "Verify page must show the pending verification email."
        )

    def test_verify_page_has_code_form_label(self):
        """Verify page must have a clear code entry label."""
        client = Client()
        client.post("/register/", {"email": "verifylabel@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Piekļuves kods" in content, (
            "Verify page must have 'Piekļuves kods' label."
        )

    def test_verify_page_has_submit_button(self):
        """Verify page must have a submit button."""
        client = Client()
        client.post("/register/", {"email": "verifybutton@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Apstiprināt" in content, (
            "Verify page must have 'Apstiprināt' submit button."
        )


# ===========================================================================
# AC4 — Portal redesigned behavior
# ===========================================================================


class TestPortalHeroSummary:
    """Portal must show hero summary with Mani pieteikumi / Pārskatiet un turpiniet."""

    def test_portal_has_fk_parent_page_wrapper(self):
        """Portal page must use fk-parent-page shell."""
        acct = ParentAccount.objects.create(
            email="portalhero@example.com",
            phone="+37111111111",
        )
        client = Client()
        _login_via_magic_link(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode(), (
            "Portal must use fk-parent-page shell wrapper."
        )

    def test_portal_shows_mani_pieteikumi_eyebrow(self):
        """Portal must contain 'Mani pieteikumi' eyebrow text."""
        acct = ParentAccount.objects.create(
            email="portalhero2@example.com",
            phone="+37122222222",
        )
        client = Client()
        _login_via_magic_link(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Mani pieteikumi" in content, (
            "Portal must show 'Mani pieteikumi' eyebrow."
        )

    def test_portal_shows_parskatiet_un_turpiniet_heading(self):
        """Portal must contain 'Pārskatiet un turpiniet' heading."""
        acct = ParentAccount.objects.create(
            email="portalhero3@example.com",
            phone="+37133333333",
        )
        client = Client()
        _login_via_magic_link(client, acct)
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Pārskatiet un turpiniet" in content, (
            "Portal must show 'Pārskatiet un turpiniet' heading."
        )


class TestPortalPrimaryContinueCTA:
    """Portal must show primary continue CTA when editable application exists."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="primarycta@example.com",
            phone="+37144444444",
        )
        self.client = Client()
        _login_via_magic_link(self.client, self.acct)

    def _create_draft(self, email="primarycta@example.com", child="PrimaryCTA Child"):
        return create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "PrimaryCTA Guardian",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37155555555",
                "guardian_declared_address": "Riga 1",
                "member_full_name": child,
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_portal_shows_primary_continue_action_when_editable_application_exists(self):
        """Portal must show 'Turpināt pieteikumu' when an editable draft exists."""
        self._create_draft()
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Turpināt pieteikumu" in content, (
            "Portal must show 'Turpināt pieteikumu' CTA when draft exists."
        )

    def test_portal_primary_continue_links_to_application_workspace(self):
        """Portal primary CTA must link to the application workspace route."""
        app = self._create_draft()
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert f"/applications/{app.pk}/" in content, (
            "Portal primary CTA must link to /applications/<id>/."
        )


class TestPortalStartNewCTA:
    """Portal must always show start-new CTA."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="startnew@example.com",
            phone="+37166666666",
        )
        self.client = Client()
        _login_via_magic_link(self.client, self.acct)

    def _create_draft(self):
        return create_or_update_draft(
            data={
                "guardian_email": "startnew@example.com",
                "guardian_full_name": "StartNew Guardian",
                "guardian_personal_id": "010101-22222",
                "guardian_phone": "+37177777777",
                "guardian_declared_address": "Riga 2",
                "member_full_name": "StartNew Child",
                "member_personal_id": "010125-22222",
                "member_birth_date": "2025-02-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_portal_shows_start_new_action_even_when_editable_application_exists(self):
        """Portal must always show 'Sākt jaunu reģistrāciju' regardless of draft state."""
        self._create_draft()
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Sākt jaunu reģistrāciju" in content, (
            "Portal must show 'Sākt jaunu reģistrāciju' when draft exists."
        )

    def test_portal_shows_start_new_action_when_no_draft_exists(self):
        """Portal must show 'Sākt jaunu reģistrāciju' when no draft exists."""
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Sākt jaunu reģistrāciju" in content, (
            "Portal must show 'Sākt jaunu reģistrāciju' when no draft exists."
        )


class TestPortalEmptyState:
    """Portal must show empty state text when no applications exist."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="emptystate@example.com",
            phone="+37188888888",
        )
        self.client = Client()
        _login_via_magic_link(self.client, self.acct)

    def test_portal_shows_empty_state_text_when_no_applications(self):
        """Portal must show empty state text when no applications exist."""
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Nav pieteikumu" in content, (
            "Portal must show 'Nav pieteikumu' empty state text."
        )


class TestPortalApplicationCards:
    """Portal application cards must render status and CTA text."""

    def setup_method(self):
        self.acct = ParentAccount.objects.create(
            email="cardstest@example.com",
            phone="+37199999999",
        )
        self.client = Client()
        _login_via_magic_link(self.client, self.acct)

    def _create_draft(self, child_name="CardChild"):
        return create_or_update_draft(
            data={
                "guardian_email": "cardstest@example.com",
                "guardian_full_name": "Cards Guardian",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37100000000",
                "guardian_declared_address": "Riga 3",
                "member_full_name": child_name,
                "member_personal_id": "010125-33333",
                "member_birth_date": "2025-03-01",
            },
            files={},
            verified_account=self.acct,
        )

    def test_draft_application_card_shows_turpat_cta(self):
        """Draft application card must show 'Turpināt' CTA."""
        self._create_draft()
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Turpināt" in content, (
            "Draft application card must show 'Turpināt' CTA."
        )

    def test_application_card_shows_status_text(self):
        """Application card must show status text (Melnraksts for draft)."""
        self._create_draft()
        resp = self.client.get("/portal/")
        content = resp.content.decode()
        assert resp.status_code == 200
        assert "Melnraksts" in content, (
            "Application card must show 'Melnraksts' status for draft."
        )


# ===========================================================================
# AC5 — Keep verified entry behavior intact
# ===========================================================================


class TestVerifiedEntryIntact:
    """Register/verify workflow must remain functional after Task 2 redesign."""

    def test_get_register_returns_200(self):
        """GET /register/ must return 200."""
        resp = Client().get("/register/")
        assert resp.status_code == 200

    def test_register_page_has_email_input(self):
        """Register page must render an email input."""
        resp = Client().get("/register/")
        content = resp.content.decode()
        assert "email" in content.lower()

    def test_post_register_sends_code(self):
        """POST /register/ must send a one-time code."""
        from django.core import mail

        client = Client()
        client.post("/register/", {"email": "intact@example.com"})
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["intact@example.com"]

    def test_post_register_redirects_to_verify(self):
        """POST /register/ must redirect to /register/verify/."""
        client = Client()
        resp = client.post("/register/", {"email": "intact2@example.com"})
        assert resp.status_code == 302
        assert "/register/verify/" in resp.url

    def test_verify_page_requires_pending_email(self):
        """GET /register/verify/ without pending email must not return 200."""
        client = Client()
        resp = client.get("/register/verify/")
        assert resp.status_code != 200

    def test_verify_page_shows_pending_email(self):
        """GET /register/verify/ must show pending email in session."""
        client = Client()
        client.post("/register/", {"email": "intact3@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        assert "intact3@example.com" in resp.content.decode()

    def test_verified_user_can_access_portal(self):
        """After code verification, user must access /portal/."""
        import re

        client = Client()
        client.post("/register/", {"email": "intact4@example.com"})
        body = mail.outbox[-1].body
        code = re.search(r"\b\d{6}\b", body).group(0)
        resp = client.post("/register/verify/", {"code": code})
        assert resp.status_code == 302

        resp2 = client.get("/portal/")
        assert resp2.status_code == 200

    def test_unverified_user_cannot_access_portal(self):
        """Unverified user must be redirected from /portal/."""
        client = Client()
        resp = client.get("/portal/", follow=False)
        assert resp.status_code == 302
        assert "/register/" in resp.url


# ===========================================================================
# Task 2 Gap — Shared parent_ui primitive system file existence
# ===========================================================================


class TestParentUiPrimitiveFiles:
    """parent_ui/ template primitives must exist as files on disk.

    These files form the shared primitive system that parent-facing
    templates (register, verify, portal, application workspace) extend
    or include. Their absence means pages fall back to ad-hoc structure
    in includes/parent_shell.html.
    """

    def test_base_parent_page_template_exists(self):
        """base_parent_page.html must exist on disk."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "base_parent_page.html").exists(), (
            "templates/parent_ui/base_parent_page.html must exist."
        )

    def test_header_include_exists(self):
        """templates/parent_ui/includes/header.html must exist."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "includes" / "header.html").exists(), (
            "templates/parent_ui/includes/header.html must exist."
        )

    def test_hero_card_include_exists(self):
        """templates/parent_ui/includes/hero_card.html must exist."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "includes" / "hero_card.html").exists(), (
            "templates/parent_ui/includes/hero_card.html must exist."
        )

    def test_section_card_include_exists(self):
        """templates/parent_ui/includes/section_card.html must exist."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "includes" / "section_card.html").exists(), (
            "templates/parent_ui/includes/section_card.html must exist."
        )

    def test_status_badge_include_exists(self):
        """templates/parent_ui/includes/status_badge.html must exist."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "includes" / "status_badge.html").exists(), (
            "templates/parent_ui/includes/status_badge.html must exist."
        )

    def test_alert_include_exists(self):
        """templates/parent_ui/includes/alert.html must exist."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "includes" / "alert.html").exists(), (
            "templates/parent_ui/includes/alert.html must exist."
        )

    def test_error_summary_include_exists(self):
        """templates/parent_ui/includes/error_summary.html must exist."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui"
        assert (base / "includes" / "error_summary.html").exists(), (
            "templates/parent_ui/includes/error_summary.html must exist."
        )


# ===========================================================================
# Task 2 Gap — Templates use parent_ui primitives, not only parent_shell
# ===========================================================================


class TestParentUiPrimitiveUsage:
    """Parent-facing templates must extend or include parent_ui primitives.

    The parent_ui system is the shared design primitive layer. Pages must
    reference parent_ui/ templates, not only includes/parent_shell.html.
    """

    def test_register_template_extends_parent_ui_base(self):
        """start_registration.html must extend parent_ui/base_parent_page.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "start_registration.html"
        content = tpl.read_text()
        assert "parent_ui/base_parent_page.html" in content, (
            "start_registration.html must extend parent_ui/base_parent_page.html."
        )

    def test_verify_template_extends_parent_ui_base(self):
        """verify_code.html must extend parent_ui/base_parent_page.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "verify_code.html"
        content = tpl.read_text()
        assert "parent_ui/base_parent_page.html" in content, (
            "verify_code.html must extend parent_ui/base_parent_page.html."
        )

    def test_portal_template_extends_parent_ui_base(self):
        """parent_portal.html must extend parent_ui/base_parent_page.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        assert "parent_ui/base_parent_page.html" in content, (
            "parent_portal.html must extend parent_ui/base_parent_page.html."
        )

    def test_portal_includes_status_badge_primitive(self):
        """parent_portal.html must include the status_badge primitive for rendering application statuses."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        assert "status_badge.html" in content, (
            "parent_portal.html must include parent_ui/includes/status_badge.html for status rendering."
        )


# ===========================================================================
# Task 2 Gap — base_parent_page.html extends base.html
# ===========================================================================


class TestBaseParentPageExtendsBase:
    """base_parent_page.html must extend base.html, not be a standalone document.

    This ensures all parent-facing pages inherit the shared base template
    (CSRF middleware integration, Django template context processors,
    consistent <html>/<head>/<body> structure) rather than duplicating
    the DOCTYPE, html, head, and body tags.
    """

    def test_base_parent_page_extends_base_html(self):
        """base_parent_page.html must extend base.html via {% extends %}."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "base_parent_page.html"
        content = base.read_text()
        assert "extends" in content, (
            "base_parent_page.html must use {% extends %} tag."
        )
        assert "base.html" in content, (
            "base_parent_page.html must extend base.html."
        )

    def test_base_parent_page_does_not_duplicate_doctype(self):
        """base_parent_page.html must not contain a bare <!DOCTYPE html> when extending base.html.

        If base_parent_page.html extends base.html, DOCTYPE lives in base.html
        and must not be duplicated in the child.
        """
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "base_parent_page.html"
        content = base.read_text()
        # Strip any {% extends %} line to avoid false positive from the extends tag itself.
        lines = [line for line in content.splitlines() if "extends" not in line]
        joined = "\n".join(lines)
        assert "<!DOCTYPE html>" not in joined, (
            "base_parent_page.html must not duplicate <!DOCTYPE html> when extending base.html."
        )

    def test_base_parent_page_does_not_duplicate_html_tag(self):
        """base_parent_page.html must not contain <html> tag when extending base.html."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "base_parent_page.html"
        content = base.read_text()
        lines = [line for line in content.splitlines() if "extends" not in line]
        joined = "\n".join(lines)
        assert "<html" not in joined, (
            "base_parent_page.html must not duplicate <html> tag when extending base.html."
        )

    def test_base_parent_page_does_not_duplicate_body_tag(self):
        """base_parent_page.html must not contain <body> tag when extending base.html."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "base_parent_page.html"
        content = base.read_text()
        lines = [line for line in content.splitlines() if "extends" not in line]
        joined = "\n".join(lines)
        assert "<body" not in joined, (
            "base_parent_page.html must not duplicate <body> tag when extending base.html."
        )


# ===========================================================================
# Task 2 Gap — Register template uses hero_card and section_card
# ===========================================================================


class TestRegisterTemplateUsesPrimitives:
    """start_registration.html must use parent_ui hero_card and section_card primitives.

    Instead of inline divs, the register page should include the shared
    hero_card.html and section_card.html primitives for consistent
    design system usage.
    """

    def test_register_includes_hero_card(self):
        """start_registration.html must include hero_card.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "start_registration.html"
        content = tpl.read_text()
        assert "hero_card.html" in content, (
            "start_registration.html must include parent_ui/includes/hero_card.html."
        )

    def test_register_includes_section_card(self):
        """start_registration.html must include section_card.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "start_registration.html"
        content = tpl.read_text()
        assert "section_card.html" in content, (
            "start_registration.html must include parent_ui/includes/section_card.html."
        )


# ===========================================================================
# Task 2 Gap — Verify template uses hero_card, section_card, and alert
# ===========================================================================


class TestVerifyTemplateUsesPrimitives:
    """verify_code.html must use parent_ui hero_card, section_card, and alert primitives.

    The verify page should use the shared primitives rather than inline
    divs, and must include the alert primitive for error message rendering.
    """

    def test_verify_includes_hero_card(self):
        """verify_code.html must include hero_card.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "verify_code.html"
        content = tpl.read_text()
        assert "hero_card.html" in content, (
            "verify_code.html must include parent_ui/includes/hero_card.html."
        )

    def test_verify_includes_section_card(self):
        """verify_code.html must include section_card.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "verify_code.html"
        content = tpl.read_text()
        assert "section_card.html" in content, (
            "verify_code.html must include parent_ui/includes/section_card.html."
        )

    def test_verify_includes_alert_for_errors(self):
        """verify_code.html must include alert.html for error message presentation."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "verify_code.html"
        content = tpl.read_text()
        assert "alert.html" in content, (
            "verify_code.html must include parent_ui/includes/alert.html for error/message rendering."
        )


# ===========================================================================
# Task 2 Gap — Portal template uses hero_card, section_card, status_badge
# ===========================================================================


class TestPortalTemplateUsesPrimitives:
    """parent_portal.html must use parent_ui hero_card, section_card, and status_badge primitives.

    The portal hero card and application cards should use the shared
    primitives rather than inline div classes.
    """

    def test_portal_includes_hero_card(self):
        """parent_portal.html must include hero_card.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        assert "hero_card.html" in content, (
            "parent_portal.html must include parent_ui/includes/hero_card.html."
        )

    def test_portal_includes_section_card(self):
        """parent_portal.html must include section_card.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        assert "section_card.html" in content, (
            "parent_portal.html must include parent_ui/includes/section_card.html."
        )

    def test_portal_includes_status_badge(self):
        """parent_portal.html must include status_badge.html."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        assert "status_badge.html" in content, (
            "parent_portal.html must include parent_ui/includes/status_badge.html."
        )


# ===========================================================================
# Task 2 Gap — Portal uses {% url %} for editable CTA links
# ===========================================================================


class TestPortalUsesUrlTagsForEditableCtas:
    """Portal editable CTA links must use {% url %} tags, not hardcoded paths.

    Hardcoded /applications/<id>/ links break when URL patterns change
    (e.g. adding prefixes, locale prefixes, or routing changes). All
    editable application CTAs must use the named URL pattern.
    """

    def test_portal_hero_cta_uses_url_tag(self):
        """Portal hero 'Turpināt pieteikumu' CTA must use {% url %} tag, not hardcoded path."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        # The hero CTA (line with "Turpināt pieteikumu" inside a non-card context)
        # must use {% url %} not a hardcoded /applications/ link.
        assert "{% url" in content, (
            "parent_portal.html must use {% url %} tags for CTA links."
        )
        # Check that the hero-level Turpināt pieteikumu link uses url tag.
        # We look for the pattern: the hero CTA should NOT be a bare href="/applications/"
        # The hero CTA is the one outside the application card loop.
        lines = content.splitlines()
        hero_cta_line_idx = None
        for i, line in enumerate(lines):
            if "Turpināt pieteikumu" in line and "{% for app" not in line:
                # Check this is not inside the {% for app %} loop
                # by checking indentation and surrounding context
                hero_cta_line_idx = i
                break

        assert hero_cta_line_idx is not None, (
            "Could not find hero-level 'Turpināt pieteikumu' CTA."
        )
        hero_line = lines[hero_cta_line_idx]
        assert "{% url" in hero_line, (
            f"Hero CTA at line {hero_cta_line_idx + 1} must use {{% url %}} tag, not hardcoded path. "
            f"Found: {hero_line.strip()}"
        )

    def test_portal_editable_ctas_not_hardcoded(self):
        """Portal must not use hardcoded /applications/<id>/ for editable CTAs."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        lines = content.splitlines()

        # Find all lines with href="/applications/" that are NOT inside
        # a {% url %} tag — these are hardcoded links that should use {% url %}.
        hardcoded_count = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip lines that are part of {% url %} usage
            if "{% url" in stripped:
                continue
            # Skip the {% elif %} lines that check status
            if "app.status" in stripped:
                continue
            # Check for hardcoded /applications/ links
            if 'href="/applications/' in stripped or 'href=\'/applications/' in stripped:
                hardcoded_count += 1

        assert hardcoded_count == 0, (
            f"parent_portal.html must not use hardcoded /applications/<id>/ links. "
            f"Found {hardcoded_count} hardcoded link(s). All editable CTAs must use {{% url %}}."
        )


# ===========================================================================
# Task 2 Gap — Error summary primitive referenced where appropriate
# ===========================================================================


class TestErrorSummaryUsage:
    """Templates that render form errors must reference error_summary.html.

    The error_summary primitive provides a consistent top-level error
    presentation pattern. Forms with top-level validation errors should
    include it.
    """

    def test_error_summary_template_exists(self):
        """error_summary.html must exist on disk."""
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "includes" / "error_summary.html"
        assert base.exists(), (
            "templates/parent_ui/includes/error_summary.html must exist."
        )

    def test_verify_template_includes_error_summary(self):
        """verify_code.html must include error_summary.html for form error presentation."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "verify_code.html"
        content = tpl.read_text()
        assert "error_summary.html" in content, (
            "verify_code.html must include parent_ui/includes/error_summary.html for form error presentation."
        )

    def test_register_template_includes_error_summary(self):
        """start_registration.html must include error_summary.html for form error presentation."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "start_registration.html"
        content = tpl.read_text()
        assert "error_summary.html" in content, (
            "start_registration.html must include parent_ui/includes/error_summary.html for form error presentation."
        )

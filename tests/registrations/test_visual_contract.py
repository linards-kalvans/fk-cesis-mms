"""Consolidated visual / template contract for parent pages.

Merges the previous test_parent_visual_pages.py (68 tests, 1003 LOC) and
test_task2_logo_and_css.py (24 tests, 430 LOC) into one home.

Pins user-visible contract only: stable CSS class hooks, include-template
existence, asset link paths, and Latvian copy strings that we deliberately
surface to parents.

Disposition summary (92 source tests → new file):
  DUP-WITHIN:  5  (exact duplicates within the same source file — dropped)
  DUP-CROSS:   4  (same assertion in both files — kept once)
  PARAM:      28  (collapsed into parametrize cases)
  UNIQUE:     55  (one explicit test each, all preserved)

These tests do NOT assert DOM nesting depth or pixel layout — those
belong in a future visual-regression harness.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.core import mail
from django.http import HttpResponse
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import create_or_update_draft

pytestmark = [pytest.mark.django_db, pytest.mark.slow]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
_STATIC = Path(__file__).resolve().parents[2] / "static"


def _login_via_magic_link(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_verified_client(email: str = "visual@example.com") -> tuple[Client, ParentAccount]:
    acct = ParentAccount.objects.create(email=email, phone="+37111111111")
    c = Client()
    _login_via_magic_link(c, acct)
    return c, acct


def _create_draft(acct: ParentAccount, *, child: str = "Visual Child", suffix: str = "11") -> RegistrationApplication:
    return create_or_update_draft(
        data={
            "guardian_email": acct.email,
            "guardian_first_name": "Visual",
            "guardian_family_name": "Guardian",
            "guardian_personal_id": f"010101-{suffix}111",
            "guardian_phone": "+37155555555",
            "guardian_declared_address": "Riga 1",
            "member_full_name": child,
            "member_personal_id": f"010125-{suffix}111",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=acct,
    )


# ===========================================================================
# Asset links on the base parent template
# ===========================================================================


class TestBaseTemplateAssets:
    """Base template must include Google fonts and parent CSS links on /register/."""

    @pytest.mark.parametrize(
        "substring",
        [
            # Font presence (at least one of the display fonts must appear)
            "Inter",
            "tokens.css",
            "parent_theme.css",
            "parent_pages.css",
            'href="/static/style-guide/tokens.css"',
            'href="/static/css/parent_theme.css"',
            'href="/static/css/parent_pages.css"',
        ],
    )
    def test_base_template_links_asset(self, substring: str) -> None:
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert substring in resp.content.decode(), (
            f"Base template must contain {substring!r}."
        )

    def test_base_template_links_display_font(self) -> None:
        """Base template must link a display font (Barlow+Condensed or Anton)."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Barlow+Condensed" in content or "Anton" in content, (
            "Base template must include a Google display font link."
        )

    def test_base_template_google_fonts_use_preconnect(self) -> None:
        """Google font links must use preconnect to fonts.googleapis.com."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fonts.googleapis.com" in content
        assert "preconnect" in content

    def test_base_template_links_favicon(self) -> None:
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert 'rel="icon"' in content
        assert 'type="image/png"' in content
        assert 'href="/static/img/favicon.png"' in content


# ===========================================================================
# Shell hooks present on parent-facing landing pages
# ===========================================================================


class TestParentShellHooks:
    """Every parent-facing landing page wears the same shell hooks."""

    @pytest.mark.parametrize("hook", ["fk-parent-page", "fk-site-header"])
    def test_register_page_has_shell_hook(self, hook: str) -> None:
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert hook in resp.content.decode()

    def test_verify_page_has_fk_parent_page(self) -> None:
        client = Client()
        client.post("/register/", {"email": "verifyshell@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode()

    def test_verify_page_has_fk_site_header(self) -> None:
        client = Client()
        client.post("/register/", {"email": "verifyshell2@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        assert "fk-site-header" in resp.content.decode()

    def test_portal_has_fk_parent_page(self, verified_client: Client) -> None:
        resp = verified_client.get("/portal/")
        assert resp.status_code == 200
        assert "fk-parent-page" in resp.content.decode()


# ===========================================================================
# Logo path contract
# ===========================================================================


class TestLogoPath:
    """Header must reference fk-cesis-logo.png, not stale img/logo.png."""

    def test_header_template_uses_fk_cesis_logo_path(self) -> None:
        tpl = _TEMPLATES / "parent_ui" / "includes" / "header.html"
        assert "img/fk-cesis-logo.png" in tpl.read_text()

    def test_header_template_does_not_use_stale_logo_png(self) -> None:
        tpl = _TEMPLATES / "parent_ui" / "includes" / "header.html"
        assert "img/logo.png" not in tpl.read_text()

    @pytest.mark.parametrize(
        "page,setup",
        [
            ("register", None),
            ("verify", "post_register"),
            ("portal", "login"),
        ],
    )
    def test_rendered_page_contains_fk_cesis_logo(self, page: str, setup: str | None) -> None:
        if setup is None:
            resp = Client().get("/register/")
        elif setup == "post_register":
            c = Client()
            c.post("/register/", {"email": "logotest@example.com"})
            resp = c.get("/register/verify/")
        else:  # login
            c, _ = _make_verified_client("portallogotest@example.com")
            resp = c.get("/portal/")
        assert resp.status_code == 200
        assert "fk-cesis-logo.png" in resp.content.decode()

    def test_favicon_file_exists(self) -> None:
        assert (_STATIC / "img" / "favicon.png").exists()


# ===========================================================================
# Register page copy & structure
# ===========================================================================


class TestRegisterPageCopy:
    """Register page must contain required Latvian copy strings and structural hooks."""

    @pytest.mark.parametrize(
        "text",
        [
            "FK Cēsis",
            "Bērna reģistrācija",
            "Droša piekļuve",
            "E-pasts",
        ],
    )
    def test_register_page_has_copy(self, text: str) -> None:
        resp = Client().get("/register/")
        assert resp.status_code == 200
        assert text in resp.content.decode()

    def test_register_page_has_primary_button(self) -> None:
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-button" in content and "primary" in content


# ===========================================================================
# Verify page copy & structure
# ===========================================================================


class TestVerifyPageCopy:
    """Verify page must display secure framing, pending email, and form labels."""

    def _get_verify(self, email: str = "verifytest@example.com") -> tuple[Client, HttpResponse]:
        c = Client()
        c.post("/register/", {"email": email})
        return c, c.get("/register/verify/")

    def test_verify_page_has_secure_verification_framing(self) -> None:
        _, resp = self._get_verify("verifysec@example.com")
        assert resp.status_code == 200
        assert "Droša piekļuve" in resp.content.decode()

    def test_verify_page_shows_pending_email(self) -> None:
        _, resp = self._get_verify("verifypending@example.com")
        assert resp.status_code == 200
        assert "verifypending@example.com" in resp.content.decode()

    def test_verify_page_has_code_form_label(self) -> None:
        _, resp = self._get_verify("verifylabel@example.com")
        assert resp.status_code == 200
        assert "Piekļuves kods" in resp.content.decode()

    def test_verify_page_has_submit_button(self) -> None:
        _, resp = self._get_verify("verifysubmit@example.com")
        assert resp.status_code == 200
        assert "Apstiprināt" in resp.content.decode()


# ===========================================================================
# Portal page copy & CTA behavior
# ===========================================================================


class TestPortalCopy:
    """Portal must show hero summary copy and branding on every visit."""

    @pytest.mark.parametrize(
        "text",
        [
            "Mani pieteikumi",
            "Pārskatiet un turpiniet",
            "FK Cēsis",
        ],
    )
    def test_portal_has_copy(self, verified_client: Client, text: str) -> None:
        resp = verified_client.get("/portal/")
        assert resp.status_code == 200
        assert text in resp.content.decode()


class TestPortalCTAs:
    """Portal CTAs must appear in the correct states."""

    def test_portal_shows_primary_continue_when_draft_exists(self) -> None:
        c, acct = _make_verified_client("portalcta1@example.com")
        _create_draft(acct, suffix="21")
        resp = c.get("/portal/")
        assert "Turpināt pieteikumu" in resp.content.decode()

    def test_portal_primary_continue_links_to_application_workspace(self) -> None:
        c, acct = _make_verified_client("portalcta2@example.com")
        app = _create_draft(acct, suffix="22")
        resp = c.get("/portal/")
        assert f"/applications/{app.pk}/" in resp.content.decode()

    def test_portal_shows_start_new_when_draft_exists(self) -> None:
        c, acct = _make_verified_client("portalcta3@example.com")
        _create_draft(acct, suffix="23")
        resp = c.get("/portal/")
        assert "Sākt jaunu reģistrāciju" in resp.content.decode()

    def test_portal_shows_start_new_when_no_draft_exists(self, verified_client: Client) -> None:
        resp = verified_client.get("/portal/")
        assert "Sākt jaunu reģistrāciju" in resp.content.decode()

    def test_draft_card_shows_turpinat_cta(self) -> None:
        c, acct = _make_verified_client("portalcta4@example.com")
        _create_draft(acct, suffix="24")
        resp = c.get("/portal/")
        assert "Turpināt" in resp.content.decode()

    def test_draft_card_shows_melnraksts_status(self) -> None:
        c, acct = _make_verified_client("portalcta5@example.com")
        _create_draft(acct, suffix="25")
        resp = c.get("/portal/")
        assert "Melnraksts" in resp.content.decode()


# ===========================================================================
# Verified-entry behavior (register → verify → portal flow)
# ===========================================================================


class TestVerifiedEntryBehavior:
    """Register/verify workflow must remain functional."""

    def test_get_register_returns_200(self) -> None:
        assert Client().get("/register/").status_code == 200

    def test_post_register_sends_code(self) -> None:
        Client().post("/register/", {"email": "flowtest1@example.com"})
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["flowtest1@example.com"]

    def test_post_register_redirects_to_verify(self) -> None:
        resp = Client().post("/register/", {"email": "flowtest2@example.com"})
        assert resp.status_code == 302
        assert "/register/verify/" in resp.url

    def test_verify_page_requires_pending_email(self) -> None:
        resp = Client().get("/register/verify/")
        assert resp.status_code != 200

    def test_verified_user_can_access_portal(self) -> None:
        c = Client()
        c.post("/register/", {"email": "flowtest3@example.com"})
        body = mail.outbox[-1].body
        match = re.search(r"\b\d{6}\b", body)
        assert match is not None, "Could not find 6-digit code in verification email."
        code = match.group(0)
        resp = c.post("/register/verify/", {"code": code})
        assert resp.status_code == 302
        assert c.get("/portal/").status_code == 200

    def test_unverified_user_cannot_access_portal(self) -> None:
        resp = Client().get("/portal/", follow=False)
        assert resp.status_code == 302
        assert "/register/" in resp.url


# ===========================================================================
# Template file existence
# ===========================================================================


class TestParentUiTemplatesExist:
    """All parent_ui template files must exist on disk."""

    @pytest.mark.parametrize(
        "rel_path",
        [
            "parent_ui/base_parent_page.html",
            "parent_ui/includes/header.html",
            "parent_ui/includes/hero_card.html",
            "parent_ui/includes/section_card.html",
            "parent_ui/includes/status_badge.html",
            "parent_ui/includes/alert.html",
            "parent_ui/includes/error_summary.html",
        ],
    )
    def test_template_exists(self, rel_path: str) -> None:
        p = _TEMPLATES / rel_path
        assert p.exists(), f"Missing template: {rel_path}"


# ===========================================================================
# Template inheritance & include contract
# ===========================================================================


class TestTemplateInheritance:
    """Parent-facing templates must extend base_parent_page.html."""

    @pytest.mark.parametrize(
        "tpl_path",
        [
            "registrations/start_registration.html",
            "registrations/verify_code.html",
            "registrations/parent_portal.html",
        ],
    )
    def test_template_extends_parent_ui_base(self, tpl_path: str) -> None:
        content = (_TEMPLATES / tpl_path).read_text()
        assert "parent_ui/base_parent_page.html" in content


class TestTemplateIncludesPrimitives:
    """Each parent-facing template must include the correct primitives."""

    @pytest.mark.parametrize(
        "tpl_rel,primitive",
        [
            ("registrations/start_registration.html", "hero_card.html"),
            # start_registration owns its section card inline (single
            # <section class="fk-section-card">) rather than re-including the
            # partial, so the section_card include assertion was removed in
            # P4 Slice E Task 3 alongside the duplicate-include bug fix.
            ("registrations/start_registration.html", "error_summary.html"),
            ("registrations/verify_code.html", "hero_card.html"),
            # verify_code owns its section card inline (single
            # <section class="fk-section-card">) rather than re-including the
            # partial, mirroring start_registration's pattern. The
            # section_card include assertion was removed in P4 Slice E Task 4
            # alongside the inline-style → .fk-page-intro migration.
            ("registrations/verify_code.html", "alert.html"),
            ("registrations/verify_code.html", "error_summary.html"),
            ("registrations/parent_portal.html", "hero_card.html"),
            ("registrations/parent_portal.html", "section_card.html"),
            ("registrations/parent_portal.html", "status_badge.html"),
        ],
    )
    def test_template_includes_primitive(self, tpl_rel: str, primitive: str) -> None:
        content = (_TEMPLATES / tpl_rel).read_text()
        assert primitive in content, (
            f"{tpl_rel} must include {primitive}."
        )


# ===========================================================================
# base_parent_page structural rules
# ===========================================================================


class TestBaseParentPageStructure:
    """base_parent_page.html must extend base.html and not duplicate shell tags."""

    def _read_base(self) -> str:
        return (_TEMPLATES / "parent_ui" / "base_parent_page.html").read_text()

    def _non_extends_lines(self, content: str) -> str:
        return "\n".join(line for line in content.splitlines() if "extends" not in line)

    def test_extends_base_html(self) -> None:
        content = self._read_base()
        assert "extends" in content
        assert "base.html" in content

    def test_no_duplicate_doctype(self) -> None:
        assert "<!DOCTYPE html>" not in self._non_extends_lines(self._read_base())

    def test_no_duplicate_html_tag(self) -> None:
        assert "<html" not in self._non_extends_lines(self._read_base())

    def test_no_duplicate_body_tag(self) -> None:
        assert "<body" not in self._non_extends_lines(self._read_base())


# ===========================================================================
# Portal uses {% url %} tags — no hardcoded /applications/ hrefs
# ===========================================================================


class TestPortalUrlTags:
    """Portal editable CTA links must use {% url %} tags, not hardcoded paths."""

    def _portal_content(self) -> str:
        return (_TEMPLATES / "registrations" / "parent_portal.html").read_text()

    def test_portal_uses_url_tag(self) -> None:
        assert "{% url" in self._portal_content()

    def test_portal_hero_cta_uses_url_tag(self) -> None:
        lines = self._portal_content().splitlines()
        hero_idx = next(
            (i for i, line in enumerate(lines) if "Turpināt pieteikumu" in line),
            None,
        )
        assert hero_idx is not None, "Could not find 'Turpināt pieteikumu' CTA line."
        assert "{% url" in lines[hero_idx], (
            f"Hero CTA at line {hero_idx + 1} must use {{% url %}} tag, not hardcoded path."
        )

    def test_portal_editable_ctas_not_hardcoded(self) -> None:
        hardcoded = sum(
            1
            for line in self._portal_content().splitlines()
            if "{% url" not in line
            and "app.status" not in line
            and ('href="/applications/' in line or "href='/applications/" in line)
        )
        assert hardcoded == 0, (
            f"parent_portal.html must not use hardcoded /applications/ links. "
            f"Found {hardcoded} hardcoded link(s)."
        )


# ===========================================================================
# CSS layout contract
# ===========================================================================


class TestCssLayoutContract:
    """CSS files must expose the wide container and header style tokens."""

    def test_parent_theme_has_wide_container_1180px(self) -> None:
        css = (_STATIC / "css" / "parent_theme.css").read_text()
        assert "1180px" in css or "1180" in css

    def test_fk_parent_page_not_640px(self) -> None:
        css = (_STATIC / "css" / "parent_theme.css").read_text()
        lines = css.splitlines()
        in_rule = False
        for line in lines:
            if ".fk-parent-page" in line and "{" in line:
                in_rule = True
                continue
            if in_rule:
                if "}" in line:
                    break
                if "max-width" in line:
                    assert "640px" not in line

    def test_portal_css_has_wide_container_1240px(self) -> None:
        css = (_STATIC / "css" / "parent_theme.css").read_text()
        assert "1240px" in css or "1240" in css

    def test_fk_page_wrapper_not_640px(self) -> None:
        css = (_STATIC / "css" / "parent_pages.css").read_text()
        lines = css.splitlines()
        in_rule = False
        for line in lines:
            if ".fk-page-wrapper" in line and "{" in line:
                in_rule = True
                continue
            if in_rule:
                if "}" in line:
                    break
                if "max-width" in line:
                    assert "640px" not in line

    def test_header_has_navy_background(self) -> None:
        css = (_STATIC / "css" / "parent_theme.css").read_text()
        assert "--fk-blue" in css or "#0f0851" in css
        lines = css.splitlines()
        in_header = False
        has_bg = False
        for line in lines:
            s = line.strip()
            if ".fk-site-header" in s and "{" in s:
                in_header = True
                continue
            if in_header:
                if "}" in s:
                    break
                if "background" in s.lower():
                    has_bg = True
        assert has_bg, ".fk-site-header must define a background color."

    def test_header_has_red_border(self) -> None:
        css = (_STATIC / "css" / "parent_theme.css").read_text()
        lines = css.splitlines()
        in_header = False
        has_red_border = False
        for line in lines:
            s = line.strip()
            if ".fk-site-header" in s and "{" in s:
                in_header = True
                continue
            if in_header:
                if "}" in s:
                    break
                if "border" in s.lower() and "red" in s.lower():
                    has_red_border = True
        assert has_red_border, ".fk-site-header must have a red bottom border."

    def test_header_logo_is_large_enough(self) -> None:
        css = (_STATIC / "css" / "parent_theme.css").read_text()
        lines = css.splitlines()
        in_rule = False
        for line in lines:
            s = line.strip()
            if ".fk-site-header img" in s and "{" in s:
                in_rule = True
                continue
            if in_rule:
                if "}" in s:
                    break
                if "height" in s:
                    m = re.search(r"(\d+)px", s)
                    if m:
                        assert int(m.group(1)) >= 64, (
                            f".fk-site-header img height must be >= 64px. Found: {m.group(1)}px."
                        )


# ===========================================================================
# Template class hooks
# ===========================================================================


class TestTemplateClassHooks:
    """Templates must expose the CSS class hooks from the style-guide."""

    @pytest.mark.parametrize(
        "tpl_rel,hook",
        [
            # fk-eyebrow was previously asserted on start_registration because
            # the form was wrapped in <div class="fk-guidance-section fk-eyebrow">.
            # That wrapper was a typographic bug (eyebrow is a tagline style);
            # removed in P4 Slice E Task 3. The eyebrow still renders inside the
            # hero_card partial — that surface is covered by its own primitive
            # tests.
            ("registrations/start_registration.html", "fk-lead"),
            ("registrations/parent_portal.html", "application-card"),
        ],
    )
    def test_template_has_class_hook(self, tpl_rel: str, hook: str) -> None:
        content = (_TEMPLATES / tpl_rel).read_text()
        assert hook in content, f"{tpl_rel} must contain class hook {hook!r}."

    def test_portal_has_wide_list_layout_class(self) -> None:
        content = (_TEMPLATES / "registrations" / "parent_portal.html").read_text()
        assert re.search(r"\bapplications\b", content) or re.search(r"\bfk-applications\b", content)

    def test_portal_hero_exposes_heading_treatment(self) -> None:
        content = (_TEMPLATES / "registrations" / "parent_portal.html").read_text()
        assert "anton" in content.lower() or "fk-eyebrow" in content

    def test_status_badge_has_all_variant_classes(self) -> None:
        content = (_TEMPLATES / "parent_ui" / "includes" / "status_badge.html").read_text()
        assert "draft" in content
        assert "submitted" in content
        assert (
            "fix_requested" in content
            or "fix-requested" in content
            or "fixrequested" in content.lower()
        )


# ===========================================================================
# Single hero card per page (no duplicates or empty headings)
# ===========================================================================


class TestSingleHeroCard:
    """Each parent-facing page must render exactly one fk-hero-card."""

    @staticmethod
    def _count(content: str) -> int:
        return content.count('class="fk-hero-card"')

    def test_register_page_has_exactly_one_hero_card(self) -> None:
        resp = Client().get("/register/")
        assert resp.status_code == 200
        count = self._count(resp.content.decode())
        assert count == 1, f"Register page must render exactly 1 fk-hero-card; found {count}."

    def test_verify_page_has_exactly_one_hero_card(self) -> None:
        c = Client()
        c.post("/register/", {"email": "singlehero@example.com"})
        resp = c.get("/register/verify/")
        assert resp.status_code == 200
        count = self._count(resp.content.decode())
        assert count == 1, f"Verify page must render exactly 1 fk-hero-card; found {count}."

    def test_portal_page_has_exactly_one_hero_card(self) -> None:
        c, _ = _make_verified_client("portalhero@example.com")
        resp = c.get("/portal/")
        assert resp.status_code == 200
        count = self._count(resp.content.decode())
        assert count == 1, f"Portal page must render exactly 1 fk-hero-card; found {count}."

    def test_portal_no_empty_hero_heading(self) -> None:
        c, _ = _make_verified_client("portalheading@example.com")
        resp = c.get("/portal/")
        assert resp.status_code == 200
        assert "<h1></h1>" not in resp.content.decode()


class TestVisualContractSliceD:
    """Cross-page visual selectors introduced by Slice D + Slice E.

    All mobile CSS contract assertions for parent_theme.css live here so the
    portal_polish file stays focused on partial-rendering and template wiring.
    """

    @staticmethod
    def _css() -> str:
        from pathlib import Path
        return (
            Path(__file__).resolve().parents[2]
            / "static" / "css" / "parent_theme.css"
        ).read_text(encoding="utf-8")

    # -- Slice D selectors (presence only) --

    def test_upload_slot_selector_present(self):
        assert ".fk-upload-slot" in self._css()

    def test_camera_only_selector_present(self):
        assert ".fk-camera-only" in self._css()

    def test_wizard_nav_sticky_selector_present(self):
        assert ".fk-wizard-nav--sticky" in self._css()

    def test_visually_hidden_selector_present(self):
        assert ".fk-visually-hidden" in self._css()

    def test_address_row_selector_present(self):
        assert ".fk-address-row" in self._css()

    # -- Slice E: portal + wizard mobile rules --

    def test_applications_grid_stacks_under_720(self):
        css = self._css()
        # Multiple 720px blocks may exist in the file; the rules can land in
        # any of them, so we concatenate all block bodies before asserting.
        bodies = re.findall(
            r"@media\s*\(\s*max-width:\s*720px\s*\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            css,
            re.DOTALL,
        )
        joined = "\n".join(bodies)
        assert re.search(
            r"\.fk-applications\s*\{[^}]*grid-template-columns\s*:\s*1fr",
            joined,
        ), ".fk-applications must declare grid-template-columns: 1fr"
        assert ".fk-application-card" in joined
        assert ".fk-app-actions" in joined
        assert ".fk-helper-card" in joined

    def test_review_meta_modifier_has_spacing_rule(self):
        css = self._css()
        assert re.search(
            r"\.fk-app-meta--review\s*\{[^}]*margin-top\s*:",
            css,
        ), ".fk-app-meta--review must declare margin-top"

    def test_wizard_nav_buttons_stretch_to_grid_track_under_720(self):
        css = self._css()
        bodies = re.findall(
            r"@media\s*\(\s*max-width:\s*720px\s*\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            css,
            re.DOTALL,
        )
        joined = "\n".join(bodies)
        assert re.search(
            r"\.fk-wizard-nav\s+\.fk-button\s*\{[^}]*width\s*:\s*100%",
            joined,
        ), ".fk-wizard-nav .fk-button must declare width: 100% inside a 720px media query"
        assert re.search(
            r"\.fk-wizard-nav\s+\.fk-button\s*\{[^}]*box-sizing\s*:\s*border-box",
            joined,
        ), ".fk-wizard-nav .fk-button must declare box-sizing: border-box"

    def test_wizard_nav_buttons_shrink_padding_under_720(self):
        css = self._css()
        bodies = re.findall(
            r"@media\s*\(\s*max-width:\s*720px\s*\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            css,
            re.DOTALL,
        )
        joined = "\n".join(bodies)
        assert re.search(
            r"\.fk-wizard-nav\s+\.fk-button\s*\{[^}]*padding\s*:\s*0\s+14px",
            joined,
        ), ".fk-wizard-nav .fk-button must downscale padding to 0 14px on mobile"

    def test_wizard_actions_stack_vertically_under_720(self):
        css = self._css()
        bodies = re.findall(
            r"@media\s*\(\s*max-width:\s*720px\s*\)\s*\{((?:[^{}]|\{[^{}]*\})*)\}",
            css,
            re.DOTALL,
        )
        joined = "\n".join(bodies)
        assert re.search(
            r"\.fk-wizard-actions\s*\{[^}]*grid-template-columns\s*:\s*1fr",
            joined,
        ), ".fk-wizard-actions must use grid-template-columns: 1fr on mobile"

"""Task 2 — Logo path and CSS/layout contract gaps.

Covers the specific Task 2 bugfix scope:
A. FK Cēsis logo path: header must reference fk-cesis-logo.png, not stale img/logo.png.
B. Registration page/layout contract: wide container (~1180px), eyebrow/lead hooks,
   navy header with red border cue — aligned to style-guide/fk_cesis_responsive_registration.html.
C. Portal/list layout contract: wide list layout (~1240px), richer card primitives —
   aligned to style-guide/fk_cesis_list.html.

Strategy:
- File-content assertions on templates and CSS (stable, user-approved).
- Rendered-content assertions on key pages (register, verify, portal).
- No pixel tests; assert class names, hooks, and CSS property values.
"""

import re
from pathlib import Path

import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_via_magic_link(client, account):
    """Issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _create_and_login(email="task2@example.com"):
    """Create a ParentAccount, log in, return (client, account)."""
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37111111111",
    )
    client = Client()
    _login_via_magic_link(client, acct)
    return client, acct


# ===========================================================================
# A. Logo path — header must reference fk-cesis-logo.png
# ===========================================================================


class TestLogoPath:
    """Header template must reference fk-cesis-logo.png, not stale img/logo.png."""

    def test_header_template_uses_fk_cesis_logo_path(self):
        """parent_ui/includes/header.html must use img/fk-cesis-logo.png static path."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "includes" / "header.html"
        content = tpl.read_text()
        assert "img/fk-cesis-logo.png" in content, (
            "header.html must reference img/fk-cesis-logo.png, not img/logo.png."
        )

    def test_header_template_does_not_use_stale_logo_png(self):
        """parent_ui/includes/header.html must NOT reference img/logo.png."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "includes" / "header.html"
        content = tpl.read_text()
        assert "img/logo.png" not in content, (
            "header.html must not reference stale img/logo.png."
        )

    def test_rendered_register_page_contains_fk_cesis_logo(self):
        """GET /register/ must render fk-cesis-logo.png in the header."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-cesis-logo.png" in content, (
            "Register page must include fk-cesis-logo.png in rendered output."
        )

    def test_rendered_verify_page_contains_fk_cesis_logo(self):
        """POST to /register/ then GET /register/verify/ must render fk-cesis-logo.png."""
        client = Client()
        client.post("/register/", {"email": "verifylogo@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-cesis-logo.png" in content, (
            "Verify page must include fk-cesis-logo.png in rendered output."
        )

    def test_rendered_portal_page_contains_fk_cesis_logo(self):
        """Logged-in GET /portal/ must render fk-cesis-logo.png in the header."""
        client, acct = _create_and_login("portallogo@example.com")
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-cesis-logo.png" in content, (
            "Portal page must include fk-cesis-logo.png in rendered output."
        )


# ===========================================================================
# B. Registration page/layout contract
#    (aligned to style-guide/fk_cesis_responsive_registration.html)
# ===========================================================================


class TestRegistrationWideContainer:
    """Registration pages must use wide container (~1180px), not narrow 640px."""

    def test_parent_theme_has_wide_container_max_width(self):
        """parent_theme.css must define a wide container max-width (~1180px), not narrow 640px."""
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css").read_text()
        # The wide container hook must exist and have a max-width >= 1000px.
        # Current bug: .fk-parent-page has max-width: 640px.
        assert "max-width" in css, (
            "parent_theme.css must define max-width for container."
        )
        # Assert the presence of a wide container variable or class with ~1180px.
        # The style-guide uses --max: 1180px as the root variable.
        assert "1180px" in css or "1180" in css, (
            "parent_theme.css must define wide container max-width around 1180px (style-guide direction). "
            "Current narrow 640px must be replaced."
        )

    def test_fk_parent_page_wide_container_in_css(self):
        """.fk-parent-page CSS must target ~1180px, not 640px."""
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css").read_text()
        # Check that .fk-parent-page does NOT have max-width: 640px
        # We look for the .fk-parent-page rule and verify its max-width.
        lines = css.splitlines()
        in_fk_parent_page = False
        for line in lines:
            if ".fk-parent-page" in line and "{" in line:
                in_fk_parent_page = True
                continue
            if in_fk_parent_page:
                if "}" in line:
                    in_fk_parent_page = False
                    break
                if "max-width" in line:
                    assert "640px" not in line, (
                        ".fk-parent-page must not use max-width: 640px. "
                        "Style-guide direction is ~1180px wide container."
                    )

    def test_registration_page_has_eyebrow_treatment(self):
        """start_registration.html must expose fk-eyebrow class hook for eyebrow text."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "start_registration.html"
        content = tpl.read_text()
        assert "fk-eyebrow" in content, (
            "start_registration.html must include fk-eyebrow class hook for eyebrow treatment "
            "(style-guide: eyebrow is red, uppercase, letter-spacing, 13px)."
        )

    def test_registration_page_has_lead_treatment(self):
        """start_registration.html must expose fk-lead class hook for lead paragraph."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "start_registration.html"
        content = tpl.read_text()
        assert "fk-lead" in content, (
            "start_registration.html must include fk-lead class hook for lead paragraph "
            "(style-guide: lead is muted, 18px, 1.6 line-height)."
        )

    def test_header_has_navy_background_with_red_border(self):
        """fk-site-header must have navy background and red bottom border in CSS."""
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css").read_text()
        # The header must have a navy background color
        assert "--fk-blue" in css or "#0f0851" in css, (
            "CSS must define navy color token."
        )
        # fk-site-header must reference navy background
        # Check for background-color or background on fk-site-header
        lines = css.splitlines()
        in_header = False
        has_navy_bg = False
        has_red_border = False
        for line in lines:
            stripped = line.strip()
            if ".fk-site-header" in stripped and "{" in stripped:
                in_header = True
                continue
            if in_header:
                if "}" in stripped:
                    in_header = False
                    break
                if "background" in stripped.lower():
                    has_navy_bg = True
                if "border" in stripped.lower() and "red" in stripped.lower():
                    has_red_border = True
        assert has_navy_bg, (
            ".fk-site-header must have a navy background (style-guide: navy header)."
        )
        assert has_red_border, (
            ".fk-site-header must have a red bottom border (style-guide: 4-5px red border cue)."
        )

    def test_header_logo_is_large_enough(self):
        """Header logo image must be at least 64px wide (style-guide: 72-78px)."""
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css").read_text()
        # Current bug: .fk-site-header img has height: 40px — too small.
        # Style-guide uses 72-78px logo.
        lines = css.splitlines()
        in_header_img = False
        for line in lines:
            stripped = line.strip()
            if ".fk-site-header img" in stripped and "{" in stripped:
                in_header_img = True
                continue
            if in_header_img:
                if "}" in stripped:
                    in_header_img = False
                    break
                if "height" in stripped:
                    # Extract number from height declaration
                    import re
                    m = re.search(r"(\d+)px", stripped)
                    if m:
                        h = int(m.group(1))
                        assert h >= 64, (
                            f".fk-site-header img height must be >= 64px (style-guide: 72-78px). "
                            f"Current: {h}px."
                        )


# ===========================================================================
# C. Portal/list layout contract
#    (aligned to style-guide/fk_cesis_list.html)
# ===========================================================================


class TestPortalWideContainer:
    """Portal page must use wide list layout (~1240px), not narrow single-column shell."""

    def test_portal_page_has_wide_container_max_width(self):
        """Portal page container must use ~1240px max-width, not 640px."""
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "parent_theme.css").read_text()
        # The wide container variable or class must exist with ~1240px.
        # Style-guide uses --maxw: 1240px for the list page.
        assert "1240px" in css or "1240" in css, (
            "CSS must define wide container max-width around 1240px for portal/list layout "
            "(style-guide: --maxw: 1240px)."
        )

    def test_fk_page_wrapper_wide_container_in_css(self):
        """.fk-page-wrapper CSS must target ~1240px, not 640px."""
        css = (Path(__file__).resolve().parents[2] / "static" / "css" / "parent_pages.css").read_text()
        lines = css.splitlines()
        in_wrapper = False
        for line in lines:
            stripped = line.strip()
            if ".fk-page-wrapper" in stripped and "{" in stripped:
                in_wrapper = True
                continue
            if in_wrapper:
                if "}" in stripped:
                    in_wrapper = False
                    break
                if "max-width" in stripped:
                    assert "640px" not in stripped, (
                        ".fk-page-wrapper must not use max-width: 640px. "
                        "Portal/list layout needs ~1240px."
                    )

    def test_portal_has_wide_list_layout_class(self):
        """Portal template must use a wide list layout class (fk-applications or applications)."""
        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        # Style-guide uses .applications class for the list container.
        # Must use the exact class name, not just a substring of another class.
        assert re.search(r"\bapplications\b", content) or re.search(r"\bfk-applications\b", content), (
            "parent_portal.html must include a wide list layout class hook "
            "(style-guide: .applications grid container)."
        )

    def test_portal_hero_card_has_rich_structure(self):
        """Portal hero card must expose eyebrow/anton class hooks consistent with list template."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        # Style-guide list template uses .anton class on headings.
        # Portal must expose anton or equivalent heading treatment.
        assert "anton" in content.lower() or "fk-eyebrow" in content, (
            "parent_portal.html must expose anton or fk-eyebrow class hook "
            "(style-guide: anton font on page titles, eyebrow on hero sections)."
        )

    def test_portal_application_card_has_rich_structure(self):
        """Portal application cards must use application-card class, not generic section_card."""
        from pathlib import Path

        tpl = Path(__file__).resolve().parents[2] / "templates" / "registrations" / "parent_portal.html"
        content = tpl.read_text()
        # Style-guide list template uses .application-card class.
        # Portal must expose this class on application cards.
        assert "application-card" in content or "fk-application-card" in content, (
            "parent_portal.html must include application-card class hook "
            "(style-guide: .application-card with avatar, name, status, progress, actions)."
        )

    def test_status_badge_template_has_variant_classes(self):
        """status_badge.html must render variant classes (draft, submitted, fix_requested)."""
        tpl = Path(__file__).resolve().parents[2] / "templates" / "parent_ui" / "includes" / "status_badge.html"
        content = tpl.read_text()
        # Style-guide uses .status-badge.draft, .status-badge.submitted variants.
        # The template must output these variant classes based on status value.
        assert "draft" in content, (
            "status_badge.html must include 'draft' variant class logic."
        )
        assert "submitted" in content, (
            "status_badge.html must include 'submitted' variant class logic."
        )
        assert "fix_requested" in content or "fix-requested" in content or "fixrequested" in content.lower(), (
            "status_badge.html must include fix_requested variant class logic."
        )


class TestPortalRenderedWideLayout:
    """Rendered portal page must contain wide-layout CSS classes."""

    def _setup_portal(self, email="portalwide@example.com"):
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37111111111",
        )
        client = Client()
        _login_via_magic_link(client, acct)
        return client

    def test_rendered_portal_has_fk_parent_page_with_wide_context(self):
        """Rendered portal must include fk-parent-page shell (already tested, re-check for consistency)."""
        client = self._setup_portal()
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "fk-parent-page" in content

    def test_rendered_portal_has_site_header_with_fk_cesis_branding(self):
        """Rendered portal must include FK Cēsis branding in header."""
        client = self._setup_portal()
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "FK Cēsis" in content

    def test_rendered_portal_has_man_i_pieteikumi_heading(self):
        """Rendered portal must contain 'Mani pieteikumi' heading text."""
        client = self._setup_portal()
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Mani pieteikumi" in content


# ===========================================================================
# D. Single hero-card contract — no duplicate or empty hero cards
#    (Task 2 bugfix: pages must render exactly one fk-hero-card)
# ===========================================================================


class TestSingleHeroCard:
    """Register, verify, and portal pages must each render exactly one fk-hero-card.

    Bug: templates include both `hero_card.html` partial AND a standalone
    <section class="fk-hero-card"> block, producing duplicate hero cards.
    Portal hero_card.html include has no hero_title, producing an empty <h1></h1>.
    """

    def _count_hero_cards(self, content):
        """Count fk-hero-card class occurrences in rendered HTML."""
        return content.count('class="fk-hero-card"')

    def test_register_page_has_exactly_one_hero_card(self):
        """GET /register/ must render exactly one fk-hero-card, not two."""
        resp = Client().get("/register/")
        assert resp.status_code == 200
        content = resp.content.decode()
        count = self._count_hero_cards(content)
        assert count == 1, (
            f"Register page must render exactly 1 fk-hero-card. "
            f"Found {count}. Remove duplicate hero-card block or include."
        )

    def test_verify_page_has_exactly_one_hero_card(self):
        """GET /register/verify/ (with pending email session) must render exactly one fk-hero-card."""
        client = Client()
        client.post("/register/", {"email": "verifyhero@example.com"})
        resp = client.get("/register/verify/")
        assert resp.status_code == 200
        content = resp.content.decode()
        count = self._count_hero_cards(content)
        assert count == 1, (
            f"Verify page must render exactly 1 fk-hero-card. "
            f"Found {count}. Remove duplicate hero-card block or include."
        )

    def test_portal_page_has_exactly_one_hero_card(self):
        """GET /portal/ (authenticated) must render exactly one fk-hero-card, not an empty extra one."""
        client, _ = _create_and_login("portalhero@example.com")
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        count = self._count_hero_cards(content)
        assert count == 1, (
            f"Portal page must render exactly 1 fk-hero-card. "
            f"Found {count}. Remove empty or duplicate hero-card include."
        )

    def test_portal_no_empty_hero_heading(self):
        """Portal must not have an empty <h1></h1> from hero_card.html include without hero_title."""
        client, _ = _create_and_login("portalheading@example.com")
        resp = client.get("/portal/")
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "<h1></h1>" not in content, (
            "Portal must not contain an empty <h1></h1> from hero_card.html include "
            "without a hero_title value."
        )

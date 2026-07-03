"""Tests for P4 Slice E — parent portal + shared empty-state primitive polish.

Mobile CSS rules (previously TestParentThemeCssPortalMobile) moved to
tests/registrations/test_visual_contract.py::TestVisualContractSliceD so all
parent_theme.css contract assertions live in one place.
"""

import re

import pytest
from django.template.loader import render_to_string
from django.urls import reverse


class TestEmptyStatePartialAcceptsCta:
    """Shared empty_state.html grows an optional CTA slot for Slice E."""

    def test_renders_title_and_body_without_cta(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {"title": "Nav pieteikumu", "body": "Jums vēl nav neviena pieteikuma."},
        )
        assert "Nav pieteikumu" in html
        assert "Jums vēl nav neviena pieteikuma." in html
        assert "fk-empty-state__cta" not in html
        assert "<a " not in html

    def test_renders_cta_when_url_and_label_provided(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {
                "title": "Nav pieteikumu",
                "body": "Jums vēl nav neviena pieteikuma.",
                "cta_url": "/applications/new/",
                "cta_label": "Sākt jaunu reģistrāciju",
            },
        )
        assert 'href="/applications/new/"' in html
        assert "Sākt jaunu reģistrāciju" in html
        assert "fk-empty-state__cta" in html
        assert "fk-button--primary" in html
        assert "fk-button--full" in html

    def test_does_not_render_cta_when_only_url_is_provided(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {
                "title": "Nav pieteikumu",
                "cta_url": "/applications/new/",
            },
        )
        assert "fk-empty-state__cta" not in html
        assert "<a " not in html

    def test_does_not_render_cta_when_only_label_is_provided(self):
        html = render_to_string(
            "parent_ui/includes/empty_state.html",
            {
                "title": "Nav pieteikumu",
                "cta_label": "Sākt jaunu reģistrāciju",
            },
        )
        assert "fk-empty-state__cta" not in html
        assert "<a " not in html


@pytest.mark.django_db
class TestPortalEmptyState:
    def test_empty_portal_uses_shared_empty_state_partial(self, verified_client):
        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode("utf-8")
        assert "data-empty-state" in html
        assert "fk-empty-state__title" in html
        assert "fk-empty-state__cta" in html
        # The bespoke <h2>Nav pieteikumu</h2> markup is gone.
        assert "<h2>Nav pieteikumu</h2>" not in html

    def test_empty_state_cta_links_to_new_application(self, verified_client):
        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode("utf-8")
        m = re.search(
            r'<a[^>]*class="[^"]*\bfk-empty-state__cta\b[^"]*"[^>]*href="([^"]+)"',
            html,
        )
        # Fall back to the alternate attribute ordering for robustness.
        if m is None:
            m = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*class="[^"]*\bfk-empty-state__cta\b',
                html,
            )
        assert m is not None
        assert m.group(1) == reverse("registrations:new-application")


@pytest.mark.django_db
class TestPortalNoInlineStyles:
    def test_application_card_region_has_no_inline_styles(
        self, verified_client, parent_account
    ):
        from apps.registrations.models import RegistrationApplication

        RegistrationApplication.objects.create(
            parent_account=parent_account,
            status=RegistrationApplication.Status.DRAFT,
            member_full_name="Jānis Bērziņš",
        )
        response = verified_client.get(reverse("registrations:parent-portal"))
        html = response.content.decode("utf-8")

        # Extract <article class="fk-application-card">…</article> regions and
        # assert they (and their direct descendants) carry no style="…" attrs.
        articles = re.findall(
            r'<article[^>]*\bclass="[^"]*\bfk-application-card\b[^"]*"[^>]*>(.*?)</article>',
            html,
            re.DOTALL,
        )
        assert articles, "expected at least one fk-application-card region"
        # Allow ONLY the dynamic progress-bar width inline style — those
        # widths encode content (status progression), not styling chrome,
        # so they legitimately stay inline. Any other style="…" attribute
        # is a layout/spacing leak and must move to CSS.
        allowed_inline_style = re.compile(r'style="width:\d+%"')
        for region in articles:
            stripped = allowed_inline_style.sub("", region)
            assert 'style="' not in stripped, (
                "inline style attribute (other than dynamic width) found "
                "inside fk-application-card region"
            )

"""Tests for P4 Slice E — parent portal + shared empty-state primitive polish."""

from django.template.loader import render_to_string


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

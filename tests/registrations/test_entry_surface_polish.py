"""Tests for P4 Slice E — start_registration and verify_code polish."""

import re
from pathlib import Path

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestStartRegistrationPolish:
    def test_renders_exactly_one_section_card(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        # Regression for the duplicate {% include "section_card.html" %}.
        assert html.count('class="fk-section-card"') == 1

    def test_submit_button_uses_canonical_modifier_class(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        assert "fk-button--primary" in html
        # Regression for the broken "fk-button primary" classname.
        assert re.search(r'class="fk-button primary"', html) is None

    def test_form_is_not_wrapped_in_eyebrow(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        # The form must not be a descendant of an fk-eyebrow block wrapper.
        # (Bug fix: <div class="fk-guidance-section fk-eyebrow"> previously
        # wrapped the <form>. fk-eyebrow is a small-uppercase tagline style
        # and only legitimately appears on inline taglines like
        # <p class="fk-eyebrow">FK Cēsis</p> inside the hero card.)
        match = re.search(
            r'<(?:div|section|form)[^>]*class="[^"]*\bfk-eyebrow\b[^"]*"[^>]*>(?:(?!</(?:div|section|form)>).)*<form',
            html,
            re.DOTALL,
        )
        assert match is None, "fk-eyebrow wraps a <form>; drop the wrapper."

    def test_email_input_has_mobile_input_attrs(self, client):
        response = client.get(reverse("registrations:start-registration"))
        html = response.content.decode("utf-8")
        # Email input gets autocomplete + inputmode for mobile keyboards.
        m = re.search(
            r'<input[^>]*\bname="email"[^>]*>',
            html,
        )
        assert m is not None
        tag = m.group(0)
        assert 'inputmode="email"' in tag
        assert 'autocomplete="email"' in tag


class TestParentThemeCssEntrySurfaces:
    def test_fk_page_intro_class_defined(self):
        css_path = (
            Path(__file__).resolve().parents[2]
            / "static"
            / "css"
            / "parent_theme.css"
        )
        css = css_path.read_text(encoding="utf-8")
        assert re.search(r"\.fk-page-intro\s*\{", css), (
            ".fk-page-intro helper class must be defined in parent_theme.css"
        )


@pytest.mark.django_db
class TestVerifyCodePolish:
    def _get(self, client):
        session = client.session
        session["pending_verification_email"] = "parent@example.com"
        session.save()
        return client.get(reverse("accounts:verify-one-time-code"))

    def test_code_input_uses_mobile_one_time_code_attrs(self, client):
        response = self._get(client)
        html = response.content.decode("utf-8")
        m = re.search(r'<input[^>]*\bname="code"[^>]*>', html)
        assert m is not None
        tag = m.group(0)
        assert 'inputmode="numeric"' in tag
        assert 'autocomplete="one-time-code"' in tag
        assert "autofocus" in tag
        # Existing constraints preserved.
        assert 'maxlength="6"' in tag
        assert 'pattern="[0-9]{6}"' in tag

    def test_pending_email_notice_uses_page_intro_helper(self, client):
        response = self._get(client)
        html = response.content.decode("utf-8")
        # The pending-email paragraph uses .fk-page-intro instead of
        # inline style="..." attributes.
        m = re.search(
            r'<p[^>]*\bclass="[^"]*\bfk-page-intro\b[^"]*"[^>]*>',
            html,
        )
        assert m is not None, "pending-email notice must use fk-page-intro"
        # Inline-style migration: no style="color: var(--fk-muted)" remains.
        assert "style=\"margin: 0 0 16px; color: var(--fk-muted);\"" not in html

    def test_submit_button_is_full_width(self, client):
        response = self._get(client)
        html = response.content.decode("utf-8")
        m = re.search(
            r'<button[^>]*type="submit"[^>]*class="([^"]+)"',
            html,
        )
        assert m is not None
        classes = m.group(1)
        assert "fk-button--primary" in classes
        assert "fk-button--full" in classes

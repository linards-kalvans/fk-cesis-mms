"""P4 Slice C Task 5 — application_workspace template wiring.

Covers (template/markup layer only — no JS, no CSS):
- Required inputs carry ``data-step-required`` keyed to the step container's
  ``data-step`` name (``documents``/``guardian``/``member``/``agreement``).
- Required inputs carry ``data-step-error-empty`` (empty-field copy) and
  ``*_personal_id`` inputs additionally carry ``data-step-error-format``
  (format-error copy). Both sourced from ``apps.registrations.messages``.
- The personal-data consent checkbox renders inside the documents step with
  the consent-version data hook and the right step-required wiring.
- A T&C partial renders Latvian text inside a ``<details>`` element.
- A save-indicator element with ``role="status"`` exists on the page.
- The consent checkbox is pre-checked iff the stored consent version matches
  the current ``PERSONAL_DATA_CONSENT_VERSION`` constant.
"""

from __future__ import annotations

import re

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.messages import (
    CONSENT_REQUIRED,
    STEP_FIELD_FORMAT,
    STEP_FIELD_REQUIRED,
)
from apps.registrations.models import (
    PERSONAL_DATA_CONSENT_VERSION,
    RegistrationApplication,
)
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _ensure_kit_sizes() -> tuple[int, int]:
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


def _make_draft(email: str = "template@example.com") -> tuple[ParentAccount, RegistrationApplication]:
    _ensure_kit_sizes()
    acct = ParentAccount.objects.create(email=email, phone="+37120000099")
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_full_name": "Template Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000099",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Template Child",
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=acct,
    )
    return acct, app


# Expected step name for each submit-required form field.
_FIELD_STEP_MAP = {
    # documents step
    "guardian_identity_document": "documents",
    "member_identity_document": "documents",
    # guardian step
    "guardian_full_name": "guardian",
    "guardian_personal_id": "guardian",
    "guardian_email": "guardian",
    "guardian_phone": "guardian",
    "guardian_declared_address": "guardian",
    # member step
    "member_full_name": "member",
    "member_personal_id": "member",
    "member_birth_date": "member",
    "member_actual_address": "member",
    "member_kit_size_shirt": "member",
    # Note: member_same_address_as_guardian is intentionally absent.
    # Leaving the checkbox unchecked is a valid answer ("no, addresses
    # differ"), so it must not be step-gated. See test_member_same_address_checkbox.py.
    # agreement step
    "preferred_agreement_signing": "agreement",
}

_PERSONAL_ID_FIELDS = ("guardian_personal_id", "member_personal_id")


def _find_input_tag(html: str, field_name: str) -> str:
    """Return the raw <input|select|textarea …> opening tag for a given name attr.

    Matches a self-contained start tag (no nested tags) so attribute extraction
    via a follow-up regex is straightforward. Falls back across input/select/textarea
    so we cover all widget types Django renders for the required fields.
    """
    pattern = re.compile(
        r"<(?:input|select|textarea)\b[^>]*\bname=[\"']" + re.escape(field_name) + r"[\"'][^>]*>",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    assert match, f"No input/select/textarea tag with name={field_name!r} found in rendered HTML"
    return match.group(0)


def _attr_value(tag_html: str, attr: str) -> str | None:
    pattern = re.compile(r"\b" + re.escape(attr) + r"=[\"']([^\"']*)[\"']", re.IGNORECASE)
    match = pattern.search(tag_html)
    return match.group(1) if match else None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_template_renders_data_step_required_on_required_inputs():
    client = Client()
    acct, app = _make_draft("step-required@example.com")
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    for field_name, expected_step in _FIELD_STEP_MAP.items():
        tag = _find_input_tag(html, field_name)
        actual = _attr_value(tag, "data-step-required")
        assert actual == expected_step, (
            f"Field {field_name!r} expected data-step-required={expected_step!r}, "
            f"got {actual!r}. Tag: {tag}"
        )


def test_template_renders_data_step_error_messages_on_required_inputs():
    client = Client()
    acct, app = _make_draft("step-errors@example.com")
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    for field_name in _FIELD_STEP_MAP:
        tag = _find_input_tag(html, field_name)
        empty = _attr_value(tag, "data-step-error-empty")
        assert empty == STEP_FIELD_REQUIRED, (
            f"Field {field_name!r} expected data-step-error-empty={STEP_FIELD_REQUIRED!r}, "
            f"got {empty!r}."
        )

    for field_name in _PERSONAL_ID_FIELDS:
        tag = _find_input_tag(html, field_name)
        fmt = _attr_value(tag, "data-step-error-format")
        assert fmt == STEP_FIELD_FORMAT, (
            f"Field {field_name!r} expected data-step-error-format={STEP_FIELD_FORMAT!r}, "
            f"got {fmt!r}."
        )


def test_template_renders_consent_checkbox():
    client = Client()
    acct, app = _make_draft("consent-hooks@example.com")
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    # Match the <input> carrying the consent hook so we can inspect its other attrs.
    pattern = re.compile(r"<input\b[^>]*\bdata-personal-data-consent\b[^>]*>", re.IGNORECASE)
    match = pattern.search(html)
    assert match, "Expected an <input data-personal-data-consent> on the page."
    tag = match.group(0)

    assert _attr_value(tag, "data-consent-version") == PERSONAL_DATA_CONSENT_VERSION
    assert _attr_value(tag, "data-step-required") == "documents"
    assert _attr_value(tag, "data-step-error-empty") == CONSENT_REQUIRED


def test_template_renders_terms_partial():
    client = Client()
    acct, app = _make_draft("terms@example.com")
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200

    # <details>/<summary> widget present in rendered HTML.
    assert b"<details" in resp.content
    # Latvian content sniff — covers both "personas datu" and "personas dati".
    assert b"personas dat" in resp.content


def test_template_renders_save_indicator():
    client = Client()
    acct, app = _make_draft("save-indicator@example.com")
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    pattern = re.compile(r"<[^>]*\bdata-save-indicator\b[^>]*>", re.IGNORECASE)
    match = pattern.search(html)
    assert match, "Expected an element with data-save-indicator in the rendered HTML."
    tag = match.group(0)
    assert _attr_value(tag, "role") == "status"


def test_template_consent_checkbox_prechecked_when_consent_matches_current_version():
    client = Client()
    acct, app = _make_draft("consent-prechecked@example.com")
    app.personal_data_consent_at = timezone.now()
    app.personal_data_consent_version = PERSONAL_DATA_CONSENT_VERSION
    app.save(update_fields=["personal_data_consent_at", "personal_data_consent_version"])
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    pattern = re.compile(r"<input\b[^>]*\bdata-personal-data-consent\b[^>]*>", re.IGNORECASE)
    match = pattern.search(html)
    assert match, "Consent input must be present."
    tag = match.group(0)
    assert re.search(r"\bchecked\b", tag), (
        f"Consent checkbox should be rendered with `checked`, tag was: {tag}"
    )


def test_template_consent_checkbox_unchecked_when_version_mismatches():
    client = Client()
    acct, app = _make_draft("consent-mismatch@example.com")
    app.personal_data_consent_at = timezone.now()
    app.personal_data_consent_version = "v0-old"
    app.save(update_fields=["personal_data_consent_at", "personal_data_consent_version"])
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    pattern = re.compile(r"<input\b[^>]*\bdata-personal-data-consent\b[^>]*>", re.IGNORECASE)
    match = pattern.search(html)
    assert match, "Consent input must be present."
    tag = match.group(0)
    assert not re.search(r"\bchecked\b", tag), (
        f"Consent checkbox should NOT be checked when version mismatches; tag: {tag}"
    )


def test_save_indicator_renders_message_data_attrs():
    """Save indicator must carry data-save-message-{saving,saved,error} attrs
    sourced from apps.registrations.messages so wizard.js never hardcodes copy.
    """
    from apps.registrations.messages import (
        SAVE_INDICATOR_ERROR,
        SAVE_INDICATOR_SAVED,
        SAVE_INDICATOR_SAVING,
    )

    client = Client()
    acct, app = _make_draft("save-indicator-msgs@example.com")
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    pattern = re.compile(r"<[^>]*\bdata-save-indicator\b[^>]*>", re.IGNORECASE)
    match = pattern.search(html)
    assert match, "Expected an element with data-save-indicator in the rendered HTML."
    tag = match.group(0)

    saving = _attr_value(tag, "data-save-message-saving")
    saved = _attr_value(tag, "data-save-message-saved")
    error = _attr_value(tag, "data-save-message-error")

    assert saving == SAVE_INDICATOR_SAVING, (
        f"Expected data-save-message-saving={SAVE_INDICATOR_SAVING!r}, got {saving!r}"
    )
    assert saved == SAVE_INDICATOR_SAVED, (
        f"Expected data-save-message-saved={SAVE_INDICATOR_SAVED!r}, got {saved!r}"
    )
    assert error == SAVE_INDICATOR_ERROR, (
        f"Expected data-save-message-error={SAVE_INDICATOR_ERROR!r}, got {error!r}"
    )
    # Substring sniff for Latvian copy (mirrors task spec).
    assert "Saglabā" in saving


def test_template_consent_checkbox_unchecked_when_no_consent():
    client = Client()
    acct, app = _make_draft("consent-none@example.com")
    # Fresh draft from _make_draft has no consent stamped.
    assert app.personal_data_consent_at is None
    _login(client, acct)

    resp = client.get(f"/applications/{app.pk}/")
    assert resp.status_code == 200
    html = resp.content.decode()

    pattern = re.compile(r"<input\b[^>]*\bdata-personal-data-consent\b[^>]*>", re.IGNORECASE)
    match = pattern.search(html)
    assert match, "Consent input must be present."
    tag = match.group(0)
    assert not re.search(r"\bchecked\b", tag), (
        f"Consent checkbox should NOT be checked on fresh draft; tag: {tag}"
    )


@pytest.mark.django_db
class TestSliceDWorkspaceTemplate:
    """P4 Slice D — workspace template markers."""

    def _html(self, draft_application, verified_client):
        response = verified_client.get(f"/applications/{draft_application.id}/")
        assert response.status_code == 200
        return response.content.decode()

    def test_per_step_nav_has_sticky_modifier(self, draft_application, verified_client):
        html = self._html(draft_application, verified_client)
        wizard_navs = re.findall(r'<div[^>]*class="[^"]*fk-wizard-nav[^"]*"[^>]*>', html)
        assert len(wizard_navs) >= 2, (
            f"Expected at least 2 wizard nav rows (per-step + review), found {len(wizard_navs)}."
        )
        for nav in wizard_navs:
            assert "fk-wizard-nav--sticky" in nav, (
                f"Wizard nav row is missing the --sticky modifier: {nav}"
            )

    def test_documents_step_renders_no_dropzone_markup(self, draft_application, verified_client):
        # The old fk-dropzone label (from form_field.html's file branch) must
        # not appear anywhere in the documents step body. Upload UI is the
        # partial's job now.
        html = self._html(draft_application, verified_client)
        assert "fk-dropzone" not in html, (
            "fk-dropzone markup must not be rendered in Slice D. "
            "document_card.html owns the file inputs."
        )

    def test_address_sync_row_has_wrapper_class(self, draft_application, verified_client):
        html = self._html(draft_application, verified_client)
        assert "fk-address-row" in html, (
            "Slice D wraps the actual-address + same-as-guardian fields in a "
            ".fk-address-row container so the mobile stack CSS rule can target it."
        )

    def test_no_leaked_django_comment_markers(self, draft_application, verified_client):
        # Django's {# ... #} is single-line only; multi-line forms render as
        # literal text including the {# and #} sequences. Catch the whole
        # class of bug with one substring check on the rendered workspace.
        html = self._html(draft_application, verified_client)
        assert "{#" not in html, (
            "Rendered HTML contains a literal '{#' — a multi-line {# ... #} "
            "comment is leaking into the page. Convert it to {% comment %}...{% endcomment %}."
        )


@pytest.mark.django_db
class TestSliceDViewContext:
    """Slice D — document_bound_fields is passed to the workspace template."""

    def test_workspace_context_includes_document_bound_fields(self, draft_application, verified_client):
        response = verified_client.get(f"/applications/{draft_application.id}/")
        assert response.status_code == 200
        ctx = response.context
        assert "document_bound_fields" in ctx, (
            "View must pass document_bound_fields so the document_card partial "
            "can render the canonical file input via {{ bound_field }}."
        )
        bound_fields = ctx["document_bound_fields"]
        for kind in ("guardian_identity", "member_identity", "member_portrait"):
            assert kind in bound_fields, f"Missing bound field for kind: {kind}"
            assert bound_fields[kind].name.endswith("_document"), (
                f"Bound field for {kind} should be the *_document FileField."
            )

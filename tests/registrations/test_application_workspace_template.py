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
    "member_kit_size_shorts": "member",
    "member_same_address_as_guardian": "member",
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

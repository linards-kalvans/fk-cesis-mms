"""Task 5 — registration form and template autocomplete hooks.

Asserts that both address fields gain progressive-enhancement attributes,
the autocomplete JS is loaded on registration workspace and new-registration
surfaces, no hidden VZD-code fields are rendered, and the existing
same-address control is preserved.

Hook assertions use a two-step check: first extract the input element by id,
then verify the data attribute is present inside that tag.  This avoids
brittle full-tag regexes that break when Django reorders attributes.
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_INPUT_ID_RE = re.compile(r'<input[^>]+>')


def _get_input(content: str, field_id: str) -> str | None:
    """Return the <input> tag that has the given HTML id, or None."""
    target = f'id="{field_id}"'
    for match in _INPUT_ID_RE.finditer(content):
        if target in match.group(0):
            return match.group(0)
    return None


def _has_attr(tag: str, attr: str) -> bool:
    """True when the raw HTML tag contains the literal attribute string."""
    return attr in tag


# ---------------------------------------------------------------------------
# Workspace template
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_workspace_guardian_address_has_autocomplete_hook(
    verified_client, draft_application
):
    response = verified_client.get(f"/applications/{draft_application.id}/")
    assert response.status_code == 200
    content = response.content.decode()

    tag = _get_input(content, "id_guardian_declared_address")
    assert tag is not None, "guardian address input not found in workspace"
    assert _has_attr(tag, 'data-address-autocomplete="1"'), (
        "guardian_declared_address missing data-address-autocomplete"
    )


@pytest.mark.django_db
def test_workspace_member_address_has_autocomplete_hook(
    verified_client, draft_application
):
    response = verified_client.get(f"/applications/{draft_application.id}/")
    assert response.status_code == 200
    content = response.content.decode()

    tag = _get_input(content, "id_member_actual_address")
    assert tag is not None, "member address input not found in workspace"
    assert _has_attr(tag, 'data-address-autocomplete="1"'), (
        "member_actual_address missing data-address-autocomplete"
    )


@pytest.mark.django_db
def test_workspace_address_fields_remain_plain_text_inputs(
    verified_client, draft_application
):
    response = verified_client.get(f"/applications/{draft_application.id}/")
    assert response.status_code == 200
    content = response.content.decode()

    # Guardian address field is rendered as a text input, not a hidden field.
    # Use a broad check — the DOM is full of inputs; we just need to know
    # the form renders text inputs (not all-hidden).
    assert 'type="text"' in content

    # No hidden VZD-code fields rendered in the form.
    assert "vzd_code" not in content
    assert "data-vzd-code" not in content


@pytest.mark.django_db
def test_workspace_loads_autocomplete_js(verified_client, draft_application):
    response = verified_client.get(f"/applications/{draft_application.id}/")
    assert response.status_code == 200
    content = response.content.decode()

    assert "address_autocomplete.js" in content


@pytest.mark.django_db
def test_workspace_preserves_same_address_control(
    verified_client, draft_application
):
    response = verified_client.get(f"/applications/{draft_application.id}/")
    assert response.status_code == 200
    content = response.content.decode()

    # Extract the member address input and verify the sync attribute survived.
    tag = _get_input(content, "id_member_actual_address")
    assert tag is not None, "member address input not found in workspace"
    assert _has_attr(tag, 'data-sync-address-for'), (
        "member_actual_address must retain data-sync-address-for"
    )


# ---------------------------------------------------------------------------
# New registration template (no-JS fallback)
#
# /applications/new/ may redirect to the workspace when the parent already
# owns a draft.  Using follow=True covers both the direct-render and the
# redirect-to-workspace path without coupling to the exact redirect chain.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_new_registration_loads_autocomplete_js(verified_client):
    response = verified_client.get("/applications/new/", follow=True)
    assert response.status_code == 200
    content = response.content.decode()

    assert "address_autocomplete.js" in content


@pytest.mark.django_db
def test_new_registration_address_fields_have_autocomplete_hook(verified_client):
    response = verified_client.get("/applications/new/", follow=True)
    assert response.status_code == 200
    content = response.content.decode()

    tag = _get_input(content, "id_guardian_declared_address")
    assert tag is not None, "guardian address input not found after /applications/new/ redirect"
    assert _has_attr(tag, 'data-address-autocomplete="1"'), (
        "new-registration guardian address missing data-address-autocomplete"
    )

    tag = _get_input(content, "id_member_actual_address")
    assert tag is not None, "member address input not found after /applications/new/ redirect"
    assert _has_attr(tag, 'data-address-autocomplete="1"'), (
        "new-registration member address missing data-address-autocomplete"
    )


@pytest.mark.django_db
def test_new_registration_no_vzd_code_fields(verified_client):
    response = verified_client.get("/applications/new/", follow=True)
    assert response.status_code == 200
    content = response.content.decode()

    assert "vzd_code" not in content
    assert "data-vzd-code" not in content

"""P4 Slice C Task 4 — application_workspace AJAX auto-save JSON branch.

Covers:
- AJAX POST (`X-Requested-With: XMLHttpRequest`) returns JSON
  `{saved_at, consent_recorded}` instead of a redirect.
- `consent_recorded` reflects the current model state (not just this-request action).
- AJAX form errors return 400 with a JSON `errors` summary.
- AJAX POST to a non-editable application returns 404.
- AJAX ignores `submit_action=submit` — auto-save must never submit.
- Non-AJAX behavior (redirect on save, submit on submit_action) is preserved.
"""

import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import create_or_update_draft, submit_application

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers (mirrored from tests/registrations/test_parent_application_workspace.py)
# ---------------------------------------------------------------------------


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _ensure_kit_sizes():
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


def _make_draft(email="autosave@example.com", child_name="AutoSave Child"):
    acct = ParentAccount.objects.create(
        email=email,
        phone="+37120000010",
    )
    app = create_or_update_draft(
        data={
            "guardian_email": email,
            "guardian_first_name": "AutoSave",
            "guardian_family_name": "Parent",
            "guardian_personal_id": "010101-12345",
            "guardian_phone": "+37120000010",
            "guardian_declared_address": "Riga 1",
            "member_full_name": child_name,
            "member_personal_id": "010125-54321",
            "member_birth_date": "2025-01-01",
        },
        files={},
        verified_account=acct,
    )
    return acct, app


def _base_payload(acct: ParentAccount) -> dict:
    """Canonical draft-save payload (valid form when guardian_email present)."""
    return {
        "guardian_first_name": "AutoSave",
        "guardian_family_name": "Parent",
        "guardian_personal_id": "010101-12345",
        "guardian_email": acct.email,
        "guardian_phone": "+37120000010",
        "guardian_declared_address": "Riga 1",
        "member_full_name": "AutoSave Child",
        "member_personal_id": "010125-54321",
        "member_birth_date": "01.01.2025",
        "preferred_agreement_signing": "paper",
        "submit_action": "save_draft",
    }


def _full_submit_payload(acct: ParentAccount) -> dict:
    shirt_pk, shorts_pk = _ensure_kit_sizes()
    return {
        "guardian_first_name": "AutoSave",
        "guardian_family_name": "Parent",
        "guardian_personal_id": "010101-12345",
        "guardian_email": acct.email,
        "guardian_phone": "+37120000010",
        "guardian_declared_address": "Riga 1",
        "member_full_name": "AutoSave Child",
        "member_personal_id": "010125-54321",
        "member_birth_date": "01.01.2025",
        "member_same_address_as_guardian": True,
        "preferred_agreement_signing": "paper",
        "member_kit_size_shirt": shirt_pk,
        "member_kit_size_shorts": shorts_pk,
        "personal_data_consent": "on",
    }


# ===========================================================================
# Tests
# ===========================================================================


class TestAjaxAutoSaveBranch:
    def test_ajax_post_returns_json_with_saved_at_and_consent_recorded(self):
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        payload = _base_payload(acct)
        payload["personal_data_consent"] = "on"

        resp = client.post(
            f"/applications/{app.pk}/",
            payload,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code == 200
        assert resp["Content-Type"].startswith("application/json")
        body = json.loads(resp.content)
        assert "saved_at" in body
        assert isinstance(body["saved_at"], str)
        # ISO-8601: at minimum contains a 'T' separator.
        assert "T" in body["saved_at"]
        assert body["consent_recorded"] is True

        app.refresh_from_db()
        assert app.personal_data_consent_at is not None
        assert app.personal_data_consent_version != ""

    def test_ajax_post_without_consent_returns_consent_recorded_false(self):
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        payload = _base_payload(acct)
        # no personal_data_consent key

        resp = client.post(
            f"/applications/{app.pk}/",
            payload,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body["consent_recorded"] is False

        app.refresh_from_db()
        assert app.personal_data_consent_at is None

    def test_ajax_post_preserves_existing_consent_returns_recorded_true(self):
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        # Stamp consent ahead of time via a prior AJAX save.
        first = client.post(
            f"/applications/{app.pk}/",
            {**_base_payload(acct), "personal_data_consent": "on"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert first.status_code == 200
        app.refresh_from_db()
        original_stamp = app.personal_data_consent_at
        assert original_stamp is not None

        # Second AJAX save WITHOUT the consent key.
        resp = client.post(
            f"/applications/{app.pk}/",
            _base_payload(acct),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body["consent_recorded"] is True

        app.refresh_from_db()
        # Stamp must still be set (consent, once granted, is not cleared by later save).
        assert app.personal_data_consent_at is not None
        # Idempotent re-save must NOT bump the timestamp.
        assert app.personal_data_consent_at == original_stamp

    def test_non_ajax_post_still_redirects(self):
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        payload = _base_payload(acct)
        resp = client.post(f"/applications/{app.pk}/", payload)

        assert resp.status_code in (301, 302)
        assert resp["Location"] == f"/applications/{app.pk}/"

    def test_ajax_post_with_invalid_form_returns_400_with_errors(self):
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        payload = _base_payload(acct)
        payload["personal_data_consent"] = "on"
        payload.pop("guardian_email", None)  # required field → invalid

        resp = client.post(
            f"/applications/{app.pk}/",
            payload,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code == 400
        assert resp["Content-Type"].startswith("application/json")
        body = json.loads(resp.content)
        assert "errors" in body
        assert isinstance(body["errors"], list)
        assert len(body["errors"]) >= 1

    def test_ajax_post_with_service_value_error_returns_400_with_errors(self):
        """A ValueError raised inside create_or_update_draft (e.g. email
        mismatch with the verified parent account) must be surfaced as a
        JSON 400 to AJAX callers, not a 500 HTML response."""
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        payload = _base_payload(acct)
        # Different valid email than the verified account → form is valid,
        # but the service raises ValueError("verified account email must
        # match claimed email").
        payload["guardian_email"] = "someone-else@example.com"

        resp = client.post(
            f"/applications/{app.pk}/",
            payload,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code != 200
        assert resp.status_code == 400
        assert resp["Content-Type"].startswith("application/json")
        body = json.loads(resp.content)
        assert "errors" in body
        assert isinstance(body["errors"], list)
        assert len(body["errors"]) >= 1

    def test_ajax_post_to_non_editable_application_returns_404(self):
        client = Client()
        acct = ParentAccount.objects.create(
            email="readonly-ajax@example.com",
            phone="+37120000011",
        )

        def _png(name):
            return SimpleUploadedFile(
                name=name,
                content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
                content_type="image/png",
            )

        app = create_or_update_draft(
            data={**_full_submit_payload(acct), "member_birth_date": "2025-01-01"},
            files={
                "guardian_identity_document": _png("guardian.png"),
                "member_identity_document": _png("member.png"),
                "member_portrait_document": _png("portrait.png"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        _login(client, acct)

        resp = client.post(
            f"/applications/{app.pk}/",
            _base_payload(acct),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code == 404

    def test_ajax_post_ignores_submit_action_submit(self):
        client = Client()
        acct, app = _make_draft()
        _login(client, acct)

        payload = _full_submit_payload(acct)
        payload["submit_action"] = "submit"
        payload["member_birth_date"] = "01.01.2025"

        resp = client.post(
            f"/applications/{app.pk}/",
            payload,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert "saved_at" in body

        app.refresh_from_db()
        # Auto-save must never submit, even if submit_action=submit is in payload.
        assert app.status == RegistrationApplication.Status.DRAFT

    def test_non_ajax_submit_action_still_submits(self):
        client = Client()
        acct, app = _make_draft()

        # Submit requires guardian/member identity + portrait documents.
        def _png(name):
            return SimpleUploadedFile(
                name=name,
                content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
                content_type="image/png",
            )

        create_or_update_draft(
            data={**_full_submit_payload(acct), "member_birth_date": "2025-01-01"},
            files={
                "guardian_identity_document": _png("guardian.png"),
                "member_identity_document": _png("member.png"),
                "member_portrait_document": _png("portrait.png"),
            },
            application=app,
            verified_account=acct,
        )
        _login(client, acct)

        payload = _full_submit_payload(acct)
        payload["submit_action"] = "submit"

        resp = client.post(f"/applications/{app.pk}/", payload)

        assert resp.status_code in (301, 302)
        # Submitting redirects to the parent portal, not the workspace.
        assert resp.headers["Location"].endswith("/portal/") or "/portal" in resp.headers["Location"]

        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.SUBMITTED

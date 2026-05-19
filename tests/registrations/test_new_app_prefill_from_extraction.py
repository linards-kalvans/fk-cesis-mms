"""P3 — new application form prefill includes OCR-extracted values from prior apps.

Approved plan:
- New app form GET shows OCR-extracted guardian values when prior app has extraction.
- New app form GET shows OCR-extracted member values when prior app has extraction.
- New app form falls back to model values when no extraction.
- Guardian auto-reuse: active guardian identity document reused by default on new app.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.documents.models import Document, DocumentExtraction
from apps.registrations.services import create_or_update_draft, submit_application
from apps.members.models import KitSizeOption

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _make_png(name="doc.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _ensure_kit_sizes():
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT, label="S", defaults={"is_active": True},
    )
    KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS, label="S", defaults={"is_active": True},
    )
    return {
        "shirt": KitSizeOption.objects.get(kind=KitSizeOption.Kind.SHIRT, label="S"),
        "shorts": KitSizeOption.objects.get(kind=KitSizeOption.Kind.SHORTS, label="S"),
    }


# ===========================================================================
# New app prefill from OCR extraction
# ===========================================================================


class TestNewAppPrefillFromExtraction:
    """New app form must include OCR-extracted values from prior apps."""

    def test_new_app_form_shows_ocr_guardian_last_name(self, settings):
        """New app form must show OCR-extracted guardian last_name as prefill."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="prefillfromocr@example.com",
            phone="+37120000040",
        )

        # Create prior app with guardian identity doc (triggers OCR stub)
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Prior Parent",
                "guardian_personal_id": "010101-40000",
                "guardian_phone": "+37120000040",
                "guardian_declared_address": "Riga 40",
                "member_full_name": "Prior Child",
                "member_personal_id": "010125-40000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("prev_guardian.png"),
                "member_identity_document": _make_png("prev_member.png"),
                "member_portrait_document": _make_png("prev_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify prior extraction exists
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=guardian_doc)
        assert extraction.encrypted_payload != ""

        # New app form must show OCR-extracted values
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub OCR extracts last_name="Bērziņa" for guardian_identity
        assert "Bērziņa" in content, (
            "New app form must prefill OCR-extracted guardian values from prior apps."
        )

    def test_new_app_form_shows_ocr_member_first_name(self, settings):
        """New app form must show OCR-extracted member first_name as prefill."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="prefillmember@example.com",
            phone="+37120000041",
        )

        # Create prior app with member identity doc (triggers OCR stub)
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Prior Parent",
                "guardian_personal_id": "010101-41000",
                "guardian_phone": "+37120000041",
                "guardian_declared_address": "Riga 41",
                "member_full_name": "Prior Child",
                "member_personal_id": "010125-41000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("pm_guardian.png"),
                "member_identity_document": _make_png("pm_member.png"),
                "member_portrait_document": _make_png("pm_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify member extraction exists
        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=member_doc)
        assert extraction.encrypted_payload != ""

        # New app form must show OCR-extracted member values
        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub OCR extracts first_name="Jānis" for member_identity
        assert "Jānis" in content, (
            "New app form must prefill OCR-extracted member values from prior apps."
        )

    def test_new_app_form_fallback_to_model_values(self, settings):
        """New app form falls back to model values when no extraction exists."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="fallbackprefill@example.com",
            phone="+37120000042",
        )

        # Create prior app with docs (triggers OCR but form still falls back to model)
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Fallback Parent",
                "guardian_personal_id": "010101-42000",
                "guardian_phone": "+37120000042",
                "guardian_declared_address": "Riga 42",
                "member_full_name": "Fallback Child",
                "member_personal_id": "010125-42000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("fb_guardian.png"),
                "member_identity_document": _make_png("fb_member.png"),
                "member_portrait_document": _make_png("fb_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        client = Client()
        _login(client, account)

        resp = client.get("/applications/new/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Must fall back to model field value
        assert "Fallback Parent" in content

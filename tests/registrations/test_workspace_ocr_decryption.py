"""P3 — workspace view decrypts and renders OCR extraction summaries.

Approved plan:
- Workspace decrypts encrypted_summary and renders content for both
  guardian_identity and member_identity extractions.
- Workspace renders fine when no extraction exists (regression).
- Auth regression: non-owner gets 404 (covered by existing test suite).
- member_portrait stays outside OCR scope (covered by existing test suite).
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
# Workspace decryption — decrypted summary content visible
# ===========================================================================


class TestWorkspaceOcrDecryption:
    """Workspace must decrypt and render extraction summary content."""

    def test_workspace_shows_decrypted_guardian_summary(self, settings):
        """Workspace page must show decrypted guardian identity summary content."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="decryptws@example.com",
            phone="+37120000030",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Decrypt Parent",
                "guardian_personal_id": "010101-30000",
                "guardian_phone": "+37120000030",
                "guardian_declared_address": "Riga 30",
                "member_full_name": "Decrypt Child",
                "member_personal_id": "010125-30000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("ws_guardian.png"),
                "member_identity_document": _make_png("ws_member.png"),
                "member_portrait_document": _make_png("ws_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify extraction exists and is encrypted
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=guardian_doc)
        assert extraction.encrypted_summary != ""

        # Workspace must show decrypted content
        client = Client()
        _login(client, account)

        resp = client.get(f"/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Decrypted guardian summary surfaces the stub provider's "issuer"
        # field — rendered with the Latvian label "Izsniedzējs" via
        # OCR_FIELD_LABELS, and the raw value "MLP" alongside it.
        assert "Izsniedzējs" in content and "MLP" in content, (
            "Workspace must decrypt and render guardian extraction summary content."
        )
        # The raw underscored key must no longer leak into rendered HTML.
        assert "issuer: MLP" not in content

    def test_workspace_shows_decrypted_member_summary(self, settings):
        """Workspace page must show decrypted member identity summary content."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="decryptmember@example.com",
            phone="+37120000031",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Decrypt Parent",
                "guardian_personal_id": "010101-31000",
                "guardian_phone": "+37120000031",
                "guardian_declared_address": "Riga 31",
                "member_full_name": "Decrypt Child",
                "member_personal_id": "010125-31000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("dm_guardian.png"),
                "member_identity_document": _make_png("dm_member.png"),
                "member_portrait_document": _make_png("dm_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify member extraction exists and is encrypted
        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        member_extraction = DocumentExtraction.objects.get(document=member_doc)
        assert member_extraction.encrypted_summary != ""

        # Workspace must show decrypted member content
        client = Client()
        _login(client, account)

        resp = client.get(f"/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub member stub returns first_name="Jānis" in person_fields
        assert "Jānis" in content, (
            "Workspace must decrypt and render member extraction summary content."
        )

    def test_workspace_no_crash_without_extraction(self, settings):
        """Workspace must render fine when no extraction exists."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="novaluews@example.com",
            phone="+37120000032",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "NoValue Parent",
                "guardian_personal_id": "010101-32000",
                "guardian_phone": "+37120000032",
                "guardian_declared_address": "Riga 32",
                "member_full_name": "NoValue Child",
                "member_personal_id": "010125-32000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("nval_guardian.png"),
                "member_identity_document": _make_png("nval_member.png"),
                "member_portrait_document": _make_png("nval_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        client = Client()
        _login(client, account)

        resp = client.get(f"/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Page must still render fine
        assert "NoValue Parent" in content

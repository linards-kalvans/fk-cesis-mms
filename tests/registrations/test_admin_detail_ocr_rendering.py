"""P3 — admin detail page renders decrypted extraction values.

Approved plan:
- Admin detail shows decrypted summary content for both guardian and member docs.
- Admin detail shows inline preview + extracted values.
- Confidence/flags shown only if provider returns them (no separate DB fields required).
- Auth regression: non-staff gets 404 (covered by existing test suite).
"""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.documents.models import Document, DocumentExtraction
from apps.registrations.services import create_or_update_draft, submit_application
from apps.members.models import KitSizeOption

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
# Admin detail — decrypted extraction rendering
# ===========================================================================


class TestAdminDetailOcrDecryption:
    """Admin detail must decrypt and render extraction summary content."""

    def test_admin_detail_shows_decrypted_guardian_summary(self, settings):
        """Admin detail page must show decrypted guardian summary content."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="admintest@example.com",
            phone="+37120000050",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Admin Parent",
                "guardian_personal_id": "010101-50000",
                "guardian_phone": "+37120000050",
                "guardian_declared_address": "Riga 50",
                "member_full_name": "Admin Child",
                "member_personal_id": "010125-50000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("admin_guardian.png"),
                "member_identity_document": _make_png("admin_member.png"),
                "member_portrait_document": _make_png("admin_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify extraction exists
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=guardian_doc)
        assert extraction.encrypted_summary != ""

        # Admin detail must show decrypted content
        staff = User.objects.create_user(
            username="staff", password="staffpass", is_staff=True
        )
        client = Client()
        client.force_login(staff)

        resp = client.get(f"/admin/review/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # P5 Slice A: OCR summary now renders as a labeled <dl class="fk-ocr-readout">
        # rather than a raw <pre> block. "MLP" (stub issuer) must still appear,
        # paired with its Latvian label "Izsniedzējs".
        assert '<dl class="fk-ocr-readout"' in content, (
            "Admin detail must render OCR readout as a labeled <dl> block."
        )
        assert "Izsniedzējs" in content, (
            "Admin detail must render the Latvian label for the issuer field."
        )
        assert "MLP" in content, (
            "Admin detail must render the decrypted issuer value (stub: 'MLP')."
        )

    def test_admin_detail_shows_decrypted_member_summary(self, settings):
        """Admin detail page must show decrypted member summary content."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="admintestmember@example.com",
            phone="+37120000051",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Admin Parent",
                "guardian_personal_id": "010101-51000",
                "guardian_phone": "+37120000051",
                "guardian_declared_address": "Riga 51",
                "member_full_name": "Admin Child",
                "member_personal_id": "010125-51000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("am_guardian.png"),
                "member_identity_document": _make_png("am_member.png"),
                "member_portrait_document": _make_png("am_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        # Verify member extraction exists
        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        member_extraction = DocumentExtraction.objects.get(document=member_doc)
        assert member_extraction.encrypted_summary != ""

        # Admin detail must show decrypted member content
        staff = User.objects.create_user(
            username="staff2", password="staffpass", is_staff=True
        )
        client = Client()
        client.force_login(staff)

        resp = client.get(f"/admin/review/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub member stub returns first_name="Jānis" in person_fields
        assert "Jānis" in content, (
            "Admin detail must decrypt and render member extraction summary content."
        )

    def test_admin_detail_shows_inline_preview_links(self, settings):
        """Admin detail must include inline preview links for active docs."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="previewadmin@example.com",
            phone="+37120000052",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Preview Parent",
                "guardian_personal_id": "010101-52000",
                "guardian_phone": "+37120000052",
                "guardian_declared_address": "Riga 52",
                "member_full_name": "Preview Child",
                "member_personal_id": "010125-52000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("pa_guardian.png"),
                "member_identity_document": _make_png("pa_member.png"),
                "member_portrait_document": _make_png("pa_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        staff = User.objects.create_user(
            username="staff3", password="staffpass", is_staff=True
        )
        client = Client()
        client.force_login(staff)

        resp = client.get(f"/admin/review/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        has_preview = (
            "priekšskatījums" in content.lower()
            or "preview" in content.lower()
            or "/admin/documents/" in content.lower()
        )
        assert has_preview, (
            "Admin detail must show inline document preview links."
        )

    def test_admin_detail_shows_separate_guardian_and_member_preview_links(self, settings):
        """Admin detail must show preview links for both guardian and member identity documents."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="twopreviews@example.com",
            phone="+37120000052",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Preview Parent",
                "guardian_personal_id": "010101-52001",
                "guardian_phone": "+37120000052",
                "guardian_declared_address": "Riga 52",
                "member_full_name": "Preview Child",
                "member_personal_id": "010125-52001",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("two_guardian.png"),
                "member_identity_document": _make_png("two_member.png"),
                "member_portrait_document": _make_png("two_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        staff = User.objects.create_user(
            username="staff3b", password="staffpass", is_staff=True
        )
        client = Client()
        client.force_login(staff)

        resp = client.get(f"/admin/review/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # P5 Slice A: inline embeds (<img> for images) replace the textual
        # "Apskatīt dokumentu (priekšskatījums)" links. The admin-document-preview
        # URL appears once per active doc embed. With three uploaded docs
        # (guardian + member identity + portrait), expect at least three.
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        assert f"/admin/documents/{guardian_doc.id}/preview/" in content, (
            "Admin detail must embed the active guardian doc preview URL."
        )
        assert f"/admin/documents/{member_doc.id}/preview/" in content, (
            "Admin detail must embed the active member doc preview URL."
        )

    def test_admin_detail_shows_confidence_when_provider_returns_it(self, settings):
        """Admin detail shows confidence only if provider returns it."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="confidenceadmin@example.com",
            phone="+37120000053",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Confidence Parent",
                "guardian_personal_id": "010101-53000",
                "guardian_phone": "+37120000053",
                "guardian_declared_address": "Riga 53",
                "member_full_name": "Confidence Child",
                "member_personal_id": "010125-53000",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
            },
            files={
                "guardian_identity_document": _make_png("ca_guardian.png"),
                "member_identity_document": _make_png("ca_member.png"),
                "member_portrait_document": _make_png("ca_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        staff = User.objects.create_user(
            username="staff4", password="staffpass", is_staff=True
        )
        client = Client()
        client.force_login(staff)

        resp = client.get(f"/admin/review/applications/{app.id}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Stub provider returns confidence values — admin detail must render them
        # 0.98 is the stub confidence for first_name
        assert "0.98" in content, (
            "Admin detail must render confidence values when provider returns them."
        )

    def test_admin_detail_no_crash_without_any_ocr(self, settings):
        """Detail page must render fine when no OCR extractions exist.

        (Folded from RED-phase test_p3_remaining_gaps.py.)
        """
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        # Create submitted app WITHOUT identity docs (no OCR possible)
        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="noocrexample@example.com",
            phone="+37120000056",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "noocrexample@example.com",
                "guardian_full_name": "No OCR Parent",
                "guardian_personal_id": "010101-56565",
                "guardian_phone": "+37120000056",
                "guardian_declared_address": "Riga 56",
                "member_full_name": "No OCR Child",
                "member_personal_id": "010125-56565",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
                "preferred_agreement_signing": "paper",
                "member_same_address_as_guardian": True,
            },
            files={},
            verified_account=account,
        )
        # Manually set status to submitted (skip submit validation since no docs)
        app.status = "submitted"
        app.submitted_at = app.created_at
        app.save(update_fields=["status", "submitted_at", "updated_at"])

        staff_user = User.objects.create_superuser(
            username="noocrstaff",
            email="noocrstaff@example.com",
            password="noocrstaffpass",
        )
        client = Client()
        client.force_login(staff_user)

        resp = client.get(f"/admin/review/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Page must render without crashing
        assert "No OCR Parent" in content

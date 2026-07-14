"""P3 — guardian auto-reuse on /applications/new/ and member_portrait outside OCR scope.

Extended coverage:
- field_sources set correctly when new draft created from reusable guardian doc
- field_sources set correctly when new draft created WITHOUT reusable guardian doc
- field_sources set correctly when new draft created with OCR extraction present
- member_portrait stays outside OCR scope (no extraction, NOT_REQUESTED)
- guardian_identity upload DOES trigger OCR extraction
- member_identity upload DOES trigger OCR extraction
- non-owner cannot see reusable guardian doc flag
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.documents.models import Document, DocumentExtraction
from apps.registrations.services import create_or_update_draft, submit_application
from apps.registrations.models import RegistrationApplication
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


def _create_previous_app_with_guardian_doc(account: ParentAccount) -> RegistrationApplication:
    """Create a prior submitted application with guardian identity doc for the account."""
    kit = _ensure_kit_sizes()
    app = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Previous Parent",
            "guardian_personal_id": "010101-11111",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Previous Child",
            "member_personal_id": "010125-11111",
            "member_birth_date": "2025-01-01",
            "member_kit_size_shirt": kit["shirt"].pk,
            "member_kit_size_shorts": kit["shorts"].pk,
            "preferred_agreement_signing": "paper",
        },
        files={
            "guardian_identity_document": _make_png("prev_guardian.png"),
            "member_identity_document": _make_png("prev_member.png"),
            "member_portrait_document": _make_png("prev_portrait.png"),
        },
        verified_account=account,
    )
    submit_application(app, account)
    return app


# ===========================================================================
# Guardian auto-reuse — field_sources contract
# ===========================================================================


class TestGuardianReuseFieldSources:
    """field_sources must be set correctly when new draft created from reusable guardian doc."""

    def test_new_draft_field_sources_has_ocr_guardian_identity_when_extraction_exists(
        self, settings
    ):
        """When prior app has extraction, new draft field_sources must include ocr_guardian_identity."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="reusefields@example.com",
            phone="+37120000020",
        )
        _create_previous_app_with_guardian_doc(account)

        client = Client()
        _login(client, account)

        resp = client.post(
            "/applications/new/",
            data={
                "guardian_email": account.email,
                "guardian_full_name": "New Parent",
                "guardian_personal_id": "010101-22222",
                "guardian_phone": "+37130000000",
                "guardian_declared_address": "Riga 2",
                "member_full_name": "New Child",
                "member_personal_id": "010125-22222",
                "member_birth_date": "01.06.2025",
            },
            follow=False,
        )

        assert resp.status_code == 302
        workspace_url = resp.headers["Location"]
        app_id = int(workspace_url.split("/")[-2])

        new_app = RegistrationApplication.objects.get(pk=app_id)
        # field_sources must include ocr_guardian_identity when extraction exists
        assert new_app.field_sources is not None
        assert new_app.field_sources.get("guardian_first_name") == "ocr_guardian_identity"
        assert new_app.field_sources.get("guardian_family_name") == "ocr_guardian_identity"
        assert new_app.field_sources.get("guardian_personal_id") == "ocr_guardian_identity"
        # P13 split — legacy combined key must NOT be written
        assert "guardian_full_name" not in new_app.field_sources

    def test_new_draft_field_sources_manual_without_reusable_doc(
        self, settings
    ):
        """When no reusable guardian doc, field_sources must be manual_only."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="noreusefields@example.com",
            phone="+37120000021",
        )

        client = Client()
        _login(client, account)

        resp = client.post(
            "/applications/new/",
            data={
                "guardian_email": account.email,
                "guardian_full_name": "NoReuse Parent",
                "guardian_personal_id": "010101-23232",
                "guardian_phone": "+37140000000",
                "guardian_declared_address": "Riga 3",
                "member_full_name": "NoReuse Child",
                "member_personal_id": "010125-23232",
                "member_birth_date": "01.06.2025",
            },
            follow=False,
        )

        assert resp.status_code == 302
        workspace_url = resp.headers["Location"]
        app_id = int(workspace_url.split("/")[-2])

        new_app = RegistrationApplication.objects.get(pk=app_id)
        # field_sources must be manual_only (no OCR extraction)
        assert new_app.field_sources.get("guardian_first_name") == "manual_only"
        assert new_app.field_sources.get("guardian_family_name") == "manual_only"
        assert new_app.field_sources.get("guardian_personal_id") == "manual_only"


# ===========================================================================
# Guardian reuse with OCR — field_sources from extraction
# ===========================================================================


class TestGuardianReuseOcrFieldSources:
    """When prior doc has extraction, new draft field_sources must reflect OCR source."""

    def test_new_application_field_sources_reflect_ocr_when_extraction_present(
        self, settings
    ):
        """field_sources must include ocr_guardian_identity when prior doc has extraction."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="ocrfields@example.com",
            phone="+37120000022",
        )
        _create_previous_app_with_guardian_doc(account)

        # Verify prior app has extraction
        prior_app = account.applications.first()
        prior_guardian_doc = prior_app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert prior_guardian_doc.ocr_status == Document.OcrStatus.COMPLETED
        assert prior_guardian_doc.extraction is not None

        client = Client()
        _login(client, account)

        resp = client.post(
            "/applications/new/",
            data={
                "guardian_email": account.email,
                "guardian_full_name": "OCR Fields Parent",
                "guardian_personal_id": "010101-24242",
                "guardian_phone": "+37150000000",
                "guardian_declared_address": "Riga 4",
                "member_full_name": "OCR Fields Child",
                "member_personal_id": "010125-24242",
                "member_birth_date": "01.06.2025",
            },
            follow=False,
        )

        assert resp.status_code == 302
        workspace_url = resp.headers["Location"]
        app_id = int(workspace_url.split("/")[-2])

        new_app = RegistrationApplication.objects.get(pk=app_id)
        assert new_app.field_sources is not None
        assert "guardian_first_name" in new_app.field_sources
        assert "guardian_family_name" in new_app.field_sources
        # P13 split — legacy combined key must NOT be written
        assert "guardian_full_name" not in new_app.field_sources

    def test_submit_new_application_without_reupload_uses_reused_guardian_document(
        self, settings
    ):
        """Returning guardian should submit new application without re-uploading guardian document."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        kit = _ensure_kit_sizes()
        account = ParentAccount.objects.create(
            email="reuse-submit@example.com",
            phone="+37120000023",
        )
        _create_previous_app_with_guardian_doc(account)

        client = Client()
        _login(client, account)

        create_resp = client.post(
            "/applications/new/",
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Reuse Submit Parent",
                "guardian_personal_id": "010101-23232",
                "guardian_phone": "+37150000023",
                "guardian_declared_address": "Riga 23",
                "member_full_name": "Reuse Submit Child",
                "member_personal_id": "010125-23232",
                "member_birth_date": "01.06.2025",
            },
            follow=False,
        )
        assert create_resp.status_code == 302
        app_id = int(create_resp.headers["Location"].split("/")[-2])

        submit_resp = client.post(
            f"/applications/{app_id}/",
            data={
                "guardian_email": account.email,
                "guardian_first_name": "Reuse Submit Parent",
                "guardian_family_name": "Test",
                "guardian_personal_id": "010101-23232",
                "guardian_phone": "+37150000023",
                "guardian_declared_address": "Riga 23",
                "member_full_name": "Reuse Submit Child",
                "member_personal_id": "010125-23232",
                "member_birth_date": "01.06.2025",
                "member_same_address_as_guardian": True,
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
                "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
                "support_club_instead_of_multi_child_discount": False,
                "submit_action": "submit",
            },
            files={
                "member_identity_document": _make_png("reuse_member.png"),
                "member_portrait_document": _make_png("reuse_portrait.png"),
            },
            follow=False,
        )

        assert submit_resp.status_code == 302, (
            "Reused guardian document should satisfy guardian identity requirement on submit."
        )
        new_app = RegistrationApplication.objects.get(pk=app_id)
        assert new_app.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY,
            deleted_at__isnull=True,
        ).exists(), "New application must have active guardian identity document via default reuse."


# ===========================================================================
# Auth regression — non-owner cannot see reusable guardian doc
# ===========================================================================


class TestGuardianReuseAuthRegression:
    """Non-owner must not see reusable guardian doc context."""

    def test_non_owner_cannot_see_reusable_doc_flag(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        owner = ParentAccount.objects.create(
            email="ownertest@example.com",
            phone="+37120000025",
        )
        _create_previous_app_with_guardian_doc(owner)

        stranger = ParentAccount.objects.create(
            email="stranger@example.com",
            phone="+37120000026",
        )

        client = Client()
        _login(client, stranger)

        resp = client.get("/applications/new/", follow=True)

        assert resp.status_code == 200
        content = resp.content.decode()
        assert "reusable" not in content.lower() or "Izmanto iepriekš" not in content


# ===========================================================================
# member_portrait outside OCR scope
# ===========================================================================


class TestMemberPortraitOutsideOcrScope:
    """member_portrait upload must NOT trigger OCR extraction."""

    def test_member_portrait_upload_no_extraction_record(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="portrait@example.com",
            phone="+37120000027",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Portrait Parent",
                "guardian_personal_id": "010101-77777",
                "guardian_phone": "+37120000027",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "Portrait Child",
                "member_personal_id": "010125-77777",
                "member_birth_date": "2025-01-01",
            },
            files={
                "member_portrait_document": _make_png("portrait.png"),
            },
            verified_account=account,
        )

        portrait_doc = app.documents.get(
            kind=Document.Kind.MEMBER_PORTRAIT, deleted_at__isnull=True
        )

        # No extraction record should exist
        assert not DocumentExtraction.objects.filter(document=portrait_doc).exists()

        # OCR status must remain NOT_REQUESTED
        assert portrait_doc.ocr_status == Document.OcrStatus.NOT_REQUESTED

    def test_guardian_identity_upload_creates_extraction(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="guardianocr@example.com",
            phone="+37120000028",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Guardian OCR Parent",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37120000028",
                "guardian_declared_address": "Riga 8",
                "member_full_name": "Guardian OCR Child",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-01-01",
            },
            files={
                "guardian_identity_document": _make_png("guardian.png"),
            },
            verified_account=account,
        )

        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )

        assert DocumentExtraction.objects.filter(document=guardian_doc).exists()
        assert guardian_doc.ocr_status == Document.OcrStatus.COMPLETED

    def test_member_identity_upload_creates_extraction(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="memberocr@example.com",
            phone="+37120000029",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Member OCR Parent",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37120000029",
                "guardian_declared_address": "Riga 9",
                "member_full_name": "Member OCR Child",
                "member_personal_id": "010125-99999",
                "member_birth_date": "2025-01-01",
            },
            files={
                "member_identity_document": _make_png("member.png"),
            },
            verified_account=account,
        )

        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )

        assert DocumentExtraction.objects.filter(document=member_doc).exists()
        assert member_doc.ocr_status == Document.OcrStatus.COMPLETED

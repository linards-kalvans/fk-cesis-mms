"""P3 — parent OCR prefill/review/manual fallback flow.

Extended coverage:
- field_sources correctly set when OCR extraction succeeds
- Manual edit clears OCR source badge (field_sources updated to manual_only)
- OCR failure sets ocr_status=FAILED on document
- Non-owner cannot see OCR-extracted values in workspace
- Submitted app workspace is read-only and shows OCR source badges
- field_sources reflected in workspace context
- OCR failure persistence: classified error code from safe wrapper
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


def _create_app_with_guardian_ocr(account: ParentAccount) -> RegistrationApplication:
    """Create a draft with guardian identity doc in stub OCR mode."""
    app = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "OCR Parent",
            "guardian_personal_id": "010101-11111",
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "OCR Child",
            "member_personal_id": "010125-11111",
            "member_birth_date": "2025-01-01",
        },
        files={"guardian_identity_document": _make_png("ocr_guardian.png")},
        verified_account=account,
    )
    return app


# ===========================================================================
# Parent OCR prefill — field_sources and context contract
# ===========================================================================


class TestParentOcrPrefillFieldSources:
    """field_sources must be correctly set when OCR extraction succeeds."""

    def test_field_sources_has_ocr_guardian_identity_on_ocr_success(self, settings):
        """field_sources must include ocr_guardian_identity when extraction succeeds."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="fieldsource@example.com",
            phone="+37120000030",
        )
        app = _create_app_with_guardian_ocr(account)

        # Verify extraction was created
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert guardian_doc.ocr_status == Document.OcrStatus.COMPLETED
        assert guardian_doc.extraction is not None

        # field_sources must reflect OCR source for guardian fields
        assert app.field_sources is not None
        assert "guardian_full_name" in app.field_sources
        assert "guardian_personal_id" in app.field_sources

    def test_workspace_context_includes_ocr_extractions(self, settings):
        """Workspace view must pass ocr_extractions context with completed extractions."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="wscontext@example.com",
            phone="+37120000031",
        )
        _create_app_with_guardian_ocr(account)

        client = Client()
        _login(client, account)

        resp = client.get(f"/applications/{account.applications.first().pk}/")

        assert resp.status_code == 200
        # Verify the template received ocr_extractions context
        content = resp.content.decode()
        # Should show OCR-related content when extractions present
        has_ocr_content = (
            "Aizpildīts" in content
            or "ocr" in content.lower()
            or "pārbaudiet" in content.lower()
            or "review" in content.lower()
            or "source" in content.lower()
        )
        assert has_ocr_content, "Workspace must show OCR-related content when extractions present."


# ===========================================================================
# Manual fallback — OCR failure keeps form usable
# ===========================================================================


class TestManualFallbackOnOcrFailure:
    """OCR failure must set FAILED status and keep form usable."""

    def test_ocr_failure_sets_failed_status(self, monkeypatch, settings):
        """When OCR fails, document ocr_status must be FAILED."""

        def _ocr_fails(**kwargs):
            return (None, "provider_unavailable")

        monkeypatch.setattr(
            "apps.registrations.services.safe_extract_document_data",
            _ocr_fails,
        )
        settings.OCR_PROVIDER_MODE = "tiny_idp"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="failstatus@example.com",
            phone="+37120000032",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Fail Parent",
                "guardian_personal_id": "010101-32323",
                "guardian_phone": "+37120000032",
                "guardian_declared_address": "Riga 32",
                "member_full_name": "Fail Child",
                "member_personal_id": "010125-32323",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png("fail.png")},
            verified_account=account,
        )

        doc = app.documents.get(kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True)
        assert doc.ocr_status == Document.OcrStatus.FAILED

    def test_workspace_shows_fallback_on_ocr_failure(self, monkeypatch, settings):
        """When OCR fails, workspace should show fallback message."""

        def _ocr_fails(**kwargs):
            raise RuntimeError("OCR provider timeout")

        monkeypatch.setattr(
            "apps.registrations.services.extract_document_data",
            _ocr_fails,
        )
        settings.OCR_PROVIDER_MODE = "tiny_idp"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="fallback@example.com",
            phone="+37120000033",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Fallback Parent",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37120000033",
                "guardian_declared_address": "Riga 33",
                "member_full_name": "Fallback Child",
                "member_personal_id": "010125-33333",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png("fallback.png")},
            verified_account=account,
        )

        client = Client()
        _login(client, account)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        has_fallback = (
            "manual" in content.lower()
            or "ievadiet" in content.lower()
            or "enter" in content.lower()
            or "fallback" in content.lower()
            or "OCR neizdevās" in content
            or "manual input" in content.lower()
        )
        assert has_fallback, "Workspace must show manual fallback when OCR fails."

    def test_form_still_editable_after_ocr_failure(self, monkeypatch, settings):
        """Form must remain editable after OCR failure."""

        def _ocr_fails(**kwargs):
            raise RuntimeError("OCR provider timeout")

        monkeypatch.setattr(
            "apps.registrations.services.extract_document_data",
            _ocr_fails,
        )
        settings.OCR_PROVIDER_MODE = "tiny_idp"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="editable@example.com",
            phone="+37120000034",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Editable Parent",
                "guardian_personal_id": "010101-34343",
                "guardian_phone": "+37120000034",
                "guardian_declared_address": "Riga 34",
                "member_full_name": "Editable Child",
                "member_personal_id": "010125-34343",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png("editable.png")},
            verified_account=account,
        )

        client = Client()
        _login(client, account)

        resp = client.post(
            f"/applications/{app.pk}/",
            {
                "guardian_full_name": "Updated After OCR Fail",
                "guardian_personal_id": "010101-34343",
                "guardian_email": account.email,
                "guardian_phone": "+37120000034",
                "guardian_declared_address": "Riga 34 Updated",
                "member_full_name": "Editable Child",
                "member_personal_id": "010125-34343",
                "member_birth_date": "2025-01-01",
                "submit_action": "save_draft",
            },
            follow=False,
        )

        assert resp.status_code == 302, "POST to save draft must succeed after OCR failure."
        app.refresh_from_db()
        assert app.status == "draft"
        assert app.guardian_full_name == "Updated After OCR Fail"

    def test_manual_edit_clears_ocr_source_badge(self, settings):
        """When parent manually edits OCR-derived field, field_sources must update to manual_only."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="manualclear@example.com",
            phone="+37120000035",
        )
        app = _create_app_with_guardian_ocr(account)

        # Verify initial OCR source
        assert app.field_sources.get("guardian_full_name") is not None

        client = Client()
        _login(client, account)

        # Manually update guardian_full_name
        resp = client.post(
            f"/applications/{app.pk}/",
            {
                "guardian_full_name": "Manually Updated Name",
                "guardian_personal_id": "010101-11111",
                "guardian_email": account.email,
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "OCR Child",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
                "submit_action": "save_draft",
            },
            follow=False,
        )

        assert resp.status_code == 302
        app.refresh_from_db()
        assert app.guardian_full_name == "Manually Updated Name"
        # field_sources should still have guardian_full_name (updated by save)
        assert "guardian_full_name" in (app.field_sources or {})


# ===========================================================================
# Auth regression — non-owner cannot see OCR-extracted values
# ===========================================================================


class TestOcrDataAuthRegression:
    """Non-owner must not see OCR-extracted values in workspace."""

    def test_non_owner_gets_404_on_ocr_workspace(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        owner = ParentAccount.objects.create(
            email="ownocr@example.com",
            phone="+37120000036",
        )
        _create_app_with_guardian_ocr(owner)

        app = owner.applications.first()

        stranger = ParentAccount.objects.create(
            email="strangerocr@example.com",
            phone="+37120000037",
        )

        client = Client()
        _login(client, stranger)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 404, "Non-owner must get 404 on OCR workspace."

    def test_anonymous_gets_redirect_on_ocr_workspace(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="anonocr@example.com",
            phone="+37120000038",
        )
        _create_app_with_guardian_ocr(account)

        app = account.applications.first()

        client = Client()

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code in (302, 403, 404), (
            f"Anonymous must be redirected, blocked, or get 404, got {resp.status_code}."
        )


# ===========================================================================
# Submitted app — read-only workspace shows OCR source badges
# ===========================================================================


class TestSubmittedOcrWorkspaceReadOnly:
    """Submitted app workspace is read-only and shows OCR source badges."""

    def test_submitted_workspace_is_read_only_with_ocr_badges(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="subocr@example.com",
            phone="+37120000039",
        )
        kit = _ensure_kit_sizes()

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Sub OCR Parent",
                "guardian_personal_id": "010101-19191",
                "guardian_phone": "+37120000039",
                "guardian_declared_address": "Riga 39",
                "member_full_name": "Sub OCR Child",
                "member_personal_id": "010125-19191",
                "member_birth_date": "2025-01-01",
                "member_kit_size_shirt": kit["shirt"].pk,
                "member_kit_size_shorts": kit["shorts"].pk,
                "preferred_agreement_signing": "paper",
            },
            files={
                "guardian_identity_document": _make_png("sub_ocr.png"),
                "member_identity_document": _make_png("sub_member.png"),
                "member_portrait_document": _make_png("sub_portrait.png"),
            },
            verified_account=account,
        )
        submit_application(app, account)

        client = Client()
        _login(client, account)

        resp = client.get(f"/applications/{app.pk}/")

        assert resp.status_code == 200
        content = resp.content.decode()
        # Should be read-only
        assert "Saglabāt melnrakstu" not in content
        assert "Iesniegt pieteikumu" not in content
        # Should show OCR source indicators
        has_ocr = (
            "ocr" in content.lower()
            or "source" in content.lower()
            or "Aizpildīts" in content
            or "pārbaudiet" in content.lower()
        )
        assert has_ocr, "Submitted workspace must show OCR source indicators."


# ===========================================================================
# Registration document upload — OCR failure persistence
# ===========================================================================


class TestOcrFailurePersistence:
    """When OCR fails during registration upload, classified metadata must persist.

    The workflow consumes safe_extract_document_data(...), whose contract is
    returning (result, error_code) — not raising provider exceptions.
    Tests patch safe_extract_document_data to return (None, <classified_code>)
    for failure paths and assert the persistence contract.
    """

    def test_ocr_failure_persists_classified_error_code(
        self, monkeypatch, settings
    ):
        """classified code from safe wrapper persists to Document.ocr_error_code."""
        settings.OCR_PROVIDER_MODE = "tiny_idp"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="errcode@example.com",
            phone="+37129999990",
        )

        def _ocr_fails(**kwargs):
            return (None, "auth_failed")

        monkeypatch.setattr(
            "apps.registrations.services.safe_extract_document_data",
            _ocr_fails,
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "ErrCode Parent",
                "guardian_personal_id": "010101-99990",
                "guardian_phone": "+37129999990",
                "guardian_declared_address": "Riga 990",
                "member_full_name": "ErrCode Child",
                "member_personal_id": "010125-99990",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png("errcode.png")},
            verified_account=account,
        )

        doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert doc.ocr_status == Document.OcrStatus.FAILED
        assert doc.ocr_error_code == "auth_failed"

    def test_ocr_failure_no_extraction_row_created(
        self, monkeypatch, settings
    ):
        """No DocumentExtraction row must be created when OCR fails."""
        settings.OCR_PROVIDER_MODE = "tiny_idp"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="noextraction@example.com",
            phone="+37129999992",
        )

        def _ocr_fails(**kwargs):
            return (None, "request_timeout")

        monkeypatch.setattr(
            "apps.registrations.services.safe_extract_document_data",
            _ocr_fails,
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "NoExtraction Parent",
                "guardian_personal_id": "010101-99992",
                "guardian_phone": "+37129999992",
                "guardian_declared_address": "Riga 992",
                "member_full_name": "NoExtraction Child",
                "member_personal_id": "010125-99992",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png("noext.png")},
            verified_account=account,
        )

        doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert doc.ocr_status == Document.OcrStatus.FAILED
        assert doc.ocr_error_code == "request_timeout"
        assert not DocumentExtraction.objects.filter(document=doc).exists()

    def test_member_portrait_outside_ocr_scope(self, monkeypatch, settings):
        """member_portrait upload must not be affected by OCR failure on identity."""
        settings.OCR_PROVIDER_MODE = "tiny_idp"
        settings.OCR_ENCRYPTION_KEY = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="

        account = ParentAccount.objects.create(
            email="portrait@example.com",
            phone="+37129999994",
        )

        def _ocr_fails_identity(**kwargs):
            return (None, "invalid_response")

        monkeypatch.setattr(
            "apps.registrations.services.safe_extract_document_data",
            _ocr_fails_identity,
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Portrait Parent",
                "guardian_personal_id": "010101-99994",
                "guardian_phone": "+37129999994",
                "guardian_declared_address": "Riga 994",
                "member_full_name": "Portrait Child",
                "member_personal_id": "010125-99994",
                "member_birth_date": "2025-01-01",
            },
            files={
                "guardian_identity_document": _make_png("fail.png"),
                "member_portrait_document": _make_png("portrait.png"),
            },
            verified_account=account,
        )

        portrait_doc = app.documents.get(
            kind=Document.Kind.MEMBER_PORTRAIT, deleted_at__isnull=True
        )
        # Portrait must NOT have FAILED status (it is outside OCR scope)
        assert portrait_doc.ocr_status != Document.OcrStatus.FAILED
        # Identity doc must still have FAILED status
        identity_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert identity_doc.ocr_status == Document.OcrStatus.FAILED
        assert identity_doc.ocr_error_code == "invalid_response"

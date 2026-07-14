"""P3 — field_sources values include `ocr_guardian_identity` when OCR succeeds.

Approved plan:
- field_sources includes `ocr_guardian_identity` for guardian fields when OCR succeeds.
- field_sources includes `review_hint_extracted` when extraction has review hints.
- field_sources does NOT include OCR keys when OCR fails or is not requested.
- Auth regression: non-owner cannot see OCR-derived field sources (covered by existing test suite).
- member_portrait outside OCR scope (covered by existing test suite).
- OCR failure non-blocking (covered by existing test suite).
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.documents.models import Document, DocumentExtraction
from apps.registrations.services import create_or_update_draft

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


# ===========================================================================
# Field sources — OCR extraction source values
# ===========================================================================


class TestOcrFieldSourceValues:
    """field_sources must include OCR source values when extraction exists."""

    def test_field_sources_include_ocr_guardian_identity_when_extraction_exists(
        self, settings
    ):
        """When OCR succeeds, field_sources must include ocr_guardian_identity."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        account = ParentAccount.objects.create(
            email="ocrsource@example.com",
            phone="+37120000060",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "OcrSource Parent",
                "guardian_personal_id": "010101-60000",
                "guardian_phone": "+37120000060",
                "guardian_declared_address": "Riga 60",
                "member_full_name": "OcrSource Child",
                "member_personal_id": "010125-60000",
                "member_birth_date": "2025-01-01",
            },
            files={
                "guardian_identity_document": _make_png("source_guardian.png"),
            },
            verified_account=account,
        )

        # Verify OCR succeeded
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert guardian_doc.ocr_status == Document.OcrStatus.COMPLETED
        assert DocumentExtraction.objects.filter(document=guardian_doc).exists()

        # field_sources must include ocr_guardian_identity for guardian fields
        assert app.field_sources is not None
        assert app.field_sources.get("guardian_first_name") == "ocr_guardian_identity", (
            "field_sources must include ocr_guardian_identity when OCR succeeds."
        )
        assert app.field_sources.get("guardian_family_name") == "ocr_guardian_identity", (
            "field_sources must include ocr_guardian_identity for guardian_family_name."
        )
        assert app.field_sources.get("guardian_personal_id") == "ocr_guardian_identity", (
            "field_sources must include ocr_guardian_identity for guardian_personal_id."
        )
        assert "guardian_full_name" not in (app.field_sources or {}), (
            "field_sources must NOT contain guardian_full_name after P13."
        )

    def test_field_sources_include_ocr_member_identity_when_extraction_exists(
        self, settings
    ):
        """When OCR succeeds on member_identity, field_sources must include ocr_member_identity."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        account = ParentAccount.objects.create(
            email="ocrmemsource@example.com",
            phone="+37120000061",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "OcrMember Parent",
                "guardian_personal_id": "010101-61000",
                "guardian_phone": "+37120000061",
                "guardian_declared_address": "Riga 61",
                "member_full_name": "OcrMember Child",
                "member_personal_id": "010125-61000",
                "member_birth_date": "2025-01-01",
            },
            files={
                "member_identity_document": _make_png("mem_source.png"),
            },
            verified_account=account,
        )

        # Verify OCR succeeded on member_identity
        member_doc = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        assert member_doc.ocr_status == Document.OcrStatus.COMPLETED
        assert DocumentExtraction.objects.filter(document=member_doc).exists()

        # field_sources must include ocr_member_identity for member fields
        assert app.field_sources is not None
        assert app.field_sources.get("member_full_name") == "ocr_member_identity", (
            "field_sources must include ocr_member_identity when member OCR succeeds."
        )
        assert app.field_sources.get("member_personal_id") == "ocr_member_identity", (
            "field_sources must include ocr_member_identity for member_personal_id."
        )

    def test_field_sources_manual_only_when_ocr_not_requested(
        self, settings
    ):
        """When OCR not requested, field_sources must be manual_only."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        account = ParentAccount.objects.create(
            email="manualsource@example.com",
            phone="+37120000062",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "ManualSource Parent",
                "guardian_personal_id": "010101-62000",
                "guardian_phone": "+37120000062",
                "guardian_declared_address": "Riga 62",
                "member_full_name": "ManualSource Child",
                "member_personal_id": "010125-62000",
                "member_birth_date": "2025-01-01",
            },
            files={
                "member_identity_document": _make_png("manual_member.png"),
            },
            verified_account=account,
        )

        # No guardian identity doc uploaded — no OCR
        assert app.field_sources is not None
        assert app.field_sources.get("guardian_first_name") == "manual_only", (
            "field_sources must be manual_only when no guardian doc uploaded."
        )
        assert app.field_sources.get("guardian_family_name") == "manual_only", (
            "field_sources must be manual_only for guardian_family_name when no guardian doc uploaded."
        )
        assert "guardian_full_name" not in (app.field_sources or {}), (
            "field_sources must NOT contain guardian_full_name after P13."
        )

    def test_field_sources_manual_only_when_ocr_failed(
        self, settings, monkeypatch
    ):
        """When OCR fails, field_sources must NOT include OCR keys."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        def _ocr_fails(*args, **kwargs):
            raise RuntimeError("OCR provider down")

        monkeypatch.setattr(
            "apps.integrations.ocr.extract_document_data", _ocr_fails
        )

        account = ParentAccount.objects.create(
            email="failsource@example.com",
            phone="+37120000063",
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "FailSource Parent",
                "guardian_personal_id": "010101-63000",
                "guardian_phone": "+37120000063",
                "guardian_declared_address": "Riga 63",
                "member_full_name": "FailSource Child",
                "member_personal_id": "010125-63000",
                "member_birth_date": "2025-01-01",
            },
            files={
                "guardian_identity_document": _make_png("fail_guardian.png"),
            },
            verified_account=account,
        )

        # Verify OCR failed
        guardian_doc = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        assert guardian_doc.ocr_status == Document.OcrStatus.FAILED

        # field_sources must NOT include OCR keys when OCR failed
        assert app.field_sources is not None
        assert app.field_sources.get("guardian_first_name") == "manual_only", (
            "field_sources must be manual_only when OCR fails."
        )
        assert "guardian_full_name" not in (app.field_sources or {}), (
            "field_sources must NOT contain guardian_full_name after P13."
        )

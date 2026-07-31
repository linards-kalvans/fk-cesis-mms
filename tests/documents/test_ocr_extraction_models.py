"""P3 — encrypted extraction persistence and OCR interface contract.

Tests:
- DocumentExtraction model exists with encrypted_payload and encrypted_summary fields
- Document has OCR process fields (ocr_provider, ocr_last_processed_at, ocr_error_code, ocr_error_detail_redacted)
- Encryption helpers encrypt_json / decrypt_json round-trip
- Extraction records can be decrypted only through service helpers
- Identity document upload in stub mode creates encrypted extraction record
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.documents.models import Document

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(name="guardian.png"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


# ---------------------------------------------------------------------------
# Unit A — encrypted extraction persistence — model fields
# ---------------------------------------------------------------------------


class TestDocumentExtractionModel:
    """Verify DocumentExtraction model exists with required fields."""

    def test_model_class_exists(self):
        from apps.documents.models import DocumentExtraction

        assert DocumentExtraction is not None

    def test_has_document_one_to_one_field(self):
        from apps.documents.models import DocumentExtraction

        field_names = {f.name for f in DocumentExtraction._meta.get_fields()}
        assert "document" in field_names

    def test_has_encrypted_payload_field(self):
        from apps.documents.models import DocumentExtraction

        field_names = {f.name for f in DocumentExtraction._meta.get_fields()}
        assert "encrypted_payload" in field_names

    def test_has_encrypted_summary_field(self):
        from apps.documents.models import DocumentExtraction

        field_names = {f.name for f in DocumentExtraction._meta.get_fields()}
        assert "encrypted_summary" in field_names

    def test_has_provider_field(self):
        from apps.documents.models import DocumentExtraction

        field_names = {f.name for f in DocumentExtraction._meta.get_fields()}
        assert "provider" in field_names

    def test_has_subject_role_field(self):
        from apps.documents.models import DocumentExtraction

        field_names = {f.name for f in DocumentExtraction._meta.get_fields()}
        assert "subject_role" in field_names

    def test_has_extraction_schema_version_field(self):
        from apps.documents.models import DocumentExtraction

        field_names = {f.name for f in DocumentExtraction._meta.get_fields()}
        assert "extraction_schema_version" in field_names


class TestDocumentOcrFields:
    """Verify Document has new OCR process fields."""

    def test_has_ocr_provider_field(self):
        field_names = {f.name for f in Document._meta.get_fields()}
        assert "ocr_provider" in field_names, (
            "Document must have ocr_provider field."
        )

    def test_has_ocr_last_processed_at_field(self):
        field_names = {f.name for f in Document._meta.get_fields()}
        assert "ocr_last_processed_at" in field_names, (
            "Document must have ocr_last_processed_at field."
        )

    def test_has_ocr_error_code_field(self):
        field_names = {f.name for f in Document._meta.get_fields()}
        assert "ocr_error_code" in field_names, (
            "Document must have ocr_error_code field."
        )

    def test_has_ocr_error_detail_redacted_field(self):
        field_names = {f.name for f in Document._meta.get_fields()}
        assert "ocr_error_detail_redacted" in field_names, (
            "Document must have ocr_error_detail_redacted field."
        )


# ---------------------------------------------------------------------------
# Unit A — encryption helpers round-trip
# ---------------------------------------------------------------------------


class TestEncryptionHelpers:
    """encrypt_json / decrypt_json must round-trip correctly."""

    def test_encrypt_decrypt_roundtrip_dict(self):
        from apps.documents.ocr import encrypt_json, decrypt_json

        payload = {"first_name": "Anna", "document_number": "AB1234567"}
        token = encrypt_json(payload)
        assert isinstance(token, str)
        assert token != ""
        result = decrypt_json(token)
        assert result == payload

    def test_encrypt_decrypt_roundtrip_list(self):
        from apps.documents.ocr import encrypt_json, decrypt_json

        payload = [{"field": "a"}, {"field": "b"}]
        token = encrypt_json(payload)
        result = decrypt_json(token)
        assert result == payload

    def test_encrypt_output_is_not_plaintext(self):
        from apps.documents.ocr import encrypt_json

        payload = {"sensitive": "hidden"}
        token = encrypt_json(payload)
        assert "sensitive" not in token
        assert "hidden" not in token

    def test_decrypt_without_key_raises(self, settings):
        from apps.documents.ocr import decrypt_json

        settings.OCR_ENCRYPTION_KEY = ""
        with pytest.raises(ValueError):
            decrypt_json("some-token")


# ---------------------------------------------------------------------------
# Unit A — stub mode creates encrypted extraction record
# ---------------------------------------------------------------------------


class TestIdentityUploadCreatesEncryptedExtraction:
    """Uploading guardian/member identity doc in stub mode must create extraction."""

    def test_identity_upload_creates_encrypted_extraction_record(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import DocumentExtraction

        account = ParentAccount.objects.create(
            email="ocr@example.com", phone="+37120000000"
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_first_name": "Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child",
                "member_personal_id": "010125-12345",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png()},
            verified_account=account,
        )

        document = app.documents.get(
            kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=document)

        assert document.ocr_status == Document.OcrStatus.COMPLETED
        assert extraction.encrypted_payload != ""
        assert extraction.encrypted_summary != ""

    def test_member_identity_upload_creates_encrypted_extraction(self, settings):
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import DocumentExtraction

        account = ParentAccount.objects.create(
            email="memberocr@example.com", phone="+37120000001"
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_first_name": "Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child",
                "member_personal_id": "010125-12345",
                "member_birth_date": "2025-01-01",
            },
            files={"member_identity_document": _make_png("member.png")},
            verified_account=account,
        )

        document = app.documents.get(
            kind=Document.Kind.MEMBER_IDENTITY, deleted_at__isnull=True
        )
        extraction = DocumentExtraction.objects.get(document=document)

        assert document.ocr_status == Document.OcrStatus.COMPLETED
        assert extraction.subject_role == "member"

    def test_member_portrait_does_not_create_extraction(self, settings):
        """member_portrait is outside OCR scope — no extraction record."""
        settings.OCR_PROVIDER_MODE = "stub"
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import DocumentExtraction

        account = ParentAccount.objects.create(
            email="portraitocr@example.com", phone="+37120000002"
        )

        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_first_name": "Parent",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child",
                "member_personal_id": "010125-12345",
                "member_birth_date": "2025-01-01",
            },
            files={"member_portrait_document": _make_png("portrait.png")},
            verified_account=account,
        )

        document = app.documents.get(
            kind=Document.Kind.MEMBER_PORTRAIT, deleted_at__isnull=True
        )
        assert document.ocr_status == Document.OcrStatus.NOT_REQUESTED
        assert not DocumentExtraction.objects.filter(document=document).exists()

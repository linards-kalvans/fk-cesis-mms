"""Phase 5 — submit-while-OCR-pending + late job completion behavior.

P3.5 acceptance: the parent must not be blocked by a slow OCR provider.
Submitting an application while OCR is still running is allowed; the
submitted application records whatever OCR managed to extract by then.

When the OCR job completes *after* submission, the DocumentExtraction
row is still written (so admin review sees the data) but `field_sources`
on the now-frozen submitted application is NOT mutated.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile

from apps.accounts.models import ParentAccount
from apps.documents.models import Document, DocumentExtraction
from apps.integrations.ocr import OCRExtractionResult
from apps.integrations.tasks import ocr_extract_job
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import submit_application

pytestmark = pytest.mark.django_db

_FERNET_KEY_FIXTURE = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _make_account(email: str = "submit@example.com") -> ParentAccount:
    acc: ParentAccount = ParentAccount.objects.create(email=email, phone="+37120000001")
    return acc


def _make_complete_draft(account: ParentAccount) -> RegistrationApplication:
    """Build a draft with all fields + active documents required for submit."""
    from apps.members.models import KitSizeOption
    from apps.registrations.services import create_or_update_draft

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT, label="M", defaults={"is_active": True}
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS, label="M", defaults={"is_active": True}
    )

    app = create_or_update_draft(
        data={
            "guardian_email": account.email,
            "guardian_full_name": "Submit Parent",
            "guardian_personal_id": "010101-99999",
            "guardian_phone": "+37120000001",
            "guardian_declared_address": "Riga 1",
            "member_full_name": "Submit Child",
            "member_personal_id": "010125-99999",
            "member_birth_date": "2025-01-01",
            "member_actual_address": "Riga 1",
            "member_same_address_as_guardian": True,
            "member_kit_size_shirt": shirt.pk,
            "member_kit_size_shorts": shorts.pk,
            "preferred_agreement_signing": RegistrationApplication.AgreementSigning.PAPER,
        },
        files={},
        verified_account=account,
    )
    # Active docs (no extraction yet for guardian/member identity — OCR is pending)
    for kind, status in (
        ("guardian_identity", Document.OcrStatus.PENDING),
        ("member_identity", Document.OcrStatus.PENDING),
        ("member_portrait", Document.OcrStatus.NOT_REQUESTED),
    ):
        Document.objects.create(
            application=app,
            kind=kind,
            file=ContentFile(_png_bytes(), name=f"{kind}.png"),
            original_filename=f"{kind}.png",
            content_type="image/png",
            file_size=64,
            ocr_status=status,
        )
    return app  # type: ignore[no-any-return]


def test_submit_allowed_with_pending_ocr_documents():
    account = _make_account("pending-submit@example.com")
    app = _make_complete_draft(account)

    submitted = submit_application(app, actor_account=account)

    assert submitted.status == RegistrationApplication.Status.SUBMITTED
    # PENDING docs remain pending; submission doesn't touch their OCR status.
    pending = list(
        app.documents.filter(ocr_status=Document.OcrStatus.PENDING).order_by("kind")
    )
    assert len(pending) == 2


def test_late_ocr_completion_writes_extraction_but_freezes_field_sources(settings):
    """OCR job completing after submit must NOT mutate submitted app's field_sources."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = _make_account("late-submit@example.com")
    app = _make_complete_draft(account)

    # Capture pre-submit field_sources (manual_only for guardian/member name).
    pre_sources = dict(app.field_sources) if app.field_sources else {}

    submit_application(app, actor_account=account)
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.SUBMITTED

    # Late OCR job for guardian identity.
    guardian_doc = app.documents.get(kind=Document.Kind.GUARDIAN_IDENTITY)
    fake_result = OCRExtractionResult(
        subject="guardian",
        person_fields={"first_name": "Anna", "last_name": "Bērziņa"},
        document_metadata={},
        confidence={},
        flags=[],
        raw_reference={"provider": "tiny_idp"},
    )
    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        return_value=(fake_result, None),
    ):
        ocr_extract_job(guardian_doc.id)

    # Extraction row exists (admin must see OCR data).
    assert DocumentExtraction.objects.filter(document=guardian_doc).exists()
    guardian_doc.refresh_from_db()
    assert guardian_doc.ocr_status == Document.OcrStatus.COMPLETED

    # field_sources on the submitted application must NOT have been mutated by
    # the late job (submitted-state data is frozen).
    app.refresh_from_db()
    post_sources = dict(app.field_sources) if app.field_sources else {}
    assert post_sources.get("guardian_full_name") == pre_sources.get(
        "guardian_full_name"
    ), (
        "Late OCR completion must not mutate field_sources on submitted apps."
    )
    assert post_sources.get("guardian_full_name") != "ocr_guardian_identity"

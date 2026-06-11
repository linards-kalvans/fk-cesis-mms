"""Background-job runner + OCR job tests.

Phase 0: prove django-q2 enqueues and executes jobs end-to-end.
Phase 1: the OCR extraction job persists results exactly as the
synchronous P3 path did, classifies failures, and is a no-op for
kinds outside OCR_SUPPORTED_KINDS.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django_q.tasks import async_task, result

from apps.accounts.models import ParentAccount
from apps.documents.models import Document, DocumentExtraction
from apps.integrations.ocr import OCRExtractionResult
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Phase 0: django-q2 smoke
# ---------------------------------------------------------------------------


def _smoke_multiply(value: int, factor: int) -> int:
    """Test target — used as the job body by the smoke test."""
    return value * factor


def test_django_q_runs_a_noop_job() -> None:
    task_id = async_task(
        "tests.integrations.test_ocr_tasks._smoke_multiply",
        7,
        6,
        sync=True,
    )
    assert result(task_id) == 42


# ---------------------------------------------------------------------------
# Phase 1: ocr_extract_job persistence contract
# ---------------------------------------------------------------------------


_FERNET_KEY_FIXTURE = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="


def _make_application(email: str = "job-test@example.com") -> RegistrationApplication:
    account = ParentAccount.objects.create(email=email, phone="+37120000001")
    app: RegistrationApplication = RegistrationApplication.objects.create(
        parent_account=account,
        member_full_name="Job Child",
        member_personal_id="010125-00001",
        member_birth_date="2025-01-01",
    )
    return app


def _make_document(
    application: RegistrationApplication,
    kind: str = "guardian_identity",
) -> Document:
    doc: Document = Document.objects.create(
        application=application,
        kind=kind,
        file=ContentFile(b"fake-bytes", name="job-test.png"),
        original_filename="job-test.png",
        content_type="image/png",
        file_size=10,
        ocr_status=Document.OcrStatus.PENDING,
    )
    return doc


def test_ocr_extract_job_persists_extraction_on_success(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    application = _make_application("success@example.com")
    document = _make_document(application)

    fake_result = OCRExtractionResult(
        subject="guardian",
        person_fields={"first_name": "Anna", "last_name": "Bērziņa"},
        document_metadata={"document_number": "LV1234567"},
        confidence={},
        flags=[],
        raw_reference={"provider": "tiny_idp"},
    )

    from apps.integrations import tasks

    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        return_value=(fake_result, None),
    ):
        tasks.ocr_extract_job(document.id)

    document.refresh_from_db()
    assert document.ocr_status == Document.OcrStatus.COMPLETED
    assert document.ocr_provider == "tiny_idp"
    assert document.ocr_last_processed_at is not None

    extraction = DocumentExtraction.objects.get(document=document)
    assert extraction.subject_role == "guardian"
    assert extraction.provider == "tiny_idp"
    assert extraction.encrypted_payload  # non-empty
    assert extraction.encrypted_summary  # non-empty

    application.refresh_from_db()
    assert application.field_sources["guardian_full_name"] == "ocr_guardian_identity"
    assert application.field_sources["guardian_personal_id"] == "ocr_guardian_identity"


def test_ocr_extract_job_persists_failure_with_classified_code(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    application = _make_application("fail@example.com")
    document = _make_document(application)

    from apps.integrations import tasks

    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        return_value=(None, "auth_failed"),
    ):
        tasks.ocr_extract_job(document.id)

    document.refresh_from_db()
    assert document.ocr_status == Document.OcrStatus.FAILED
    assert document.ocr_error_code == "auth_failed"
    assert not DocumentExtraction.objects.filter(document=document).exists()


def test_ocr_extract_job_no_op_for_unsupported_kind(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE

    application = _make_application("portrait@example.com")
    document = _make_document(application, kind="member_portrait")
    document.ocr_status = Document.OcrStatus.NOT_REQUESTED
    document.save(update_fields=["ocr_status"])

    from apps.integrations import tasks

    sentinel = {"called": False}

    def _should_not_be_called(**kwargs):
        sentinel["called"] = True
        return (None, "should not run")

    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        side_effect=_should_not_be_called,
    ):
        tasks.ocr_extract_job(document.id)

    assert sentinel["called"] is False
    document.refresh_from_db()
    assert document.ocr_status == Document.OcrStatus.NOT_REQUESTED
    assert document.ocr_error_code == ""
    assert not DocumentExtraction.objects.filter(document=document).exists()


# ---------------------------------------------------------------------------
# Phase 1: upload enqueues instead of running inline
# ---------------------------------------------------------------------------


def _make_png() -> ContentFile:
    return ContentFile(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
        name="upload.png",
    )


def test_upload_enqueues_ocr_job_instead_of_running_inline(settings):
    """create_or_update_draft must enqueue the OCR job, not run it inline."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = ParentAccount.objects.create(
        email="enqueue@example.com",
        phone="+37120000002",
    )

    from apps.registrations.services import create_or_update_draft

    enqueued_ids: list[int] = []

    def _spy_enqueue(document_id: int) -> None:
        enqueued_ids.append(document_id)

    with patch(
        "apps.registrations.services.enqueue_ocr_job",
        side_effect=_spy_enqueue,
    ):
        app = create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Enqueue Parent",
                "guardian_personal_id": "010101-00002",
                "guardian_phone": "+37120000002",
                "guardian_declared_address": "Riga 2",
                "member_full_name": "Enqueue Child",
                "member_personal_id": "010125-00002",
                "member_birth_date": "2025-01-01",
            },
            files={"guardian_identity_document": _make_png()},
            verified_account=account,
        )

    doc = app.documents.get(
        kind=Document.Kind.GUARDIAN_IDENTITY, deleted_at__isnull=True
    )
    assert doc.ocr_status == Document.OcrStatus.PENDING
    assert enqueued_ids == [doc.id]


_TRANSIENT_CODES = ["request_timeout", "provider_unavailable", "rate_limited"]
_TERMINAL_CODES = ["auth_failed", "invalid_response", "provider_misconfigured"]


@pytest.mark.parametrize("transient_code", _TRANSIENT_CODES)
def test_ocr_extract_job_raises_retryable_for_transient_errors(settings, transient_code):
    """Transient failures persist FAILED and raise so django-q2 retries."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    application = _make_application(f"transient-{transient_code}@example.com")
    document = _make_document(application)

    from apps.integrations import tasks

    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        return_value=(None, transient_code),
    ):
        with pytest.raises(tasks.RetryableOCRError):
            tasks.ocr_extract_job(document.id)

    document.refresh_from_db()
    assert document.ocr_status == Document.OcrStatus.FAILED
    assert document.ocr_error_code == transient_code


@pytest.mark.parametrize("terminal_code", _TERMINAL_CODES)
def test_ocr_extract_job_does_not_retry_terminal_errors(settings, terminal_code):
    """Terminal failures persist FAILED and return normally (no retry)."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    application = _make_application(f"terminal-{terminal_code}@example.com")
    document = _make_document(application)

    from apps.integrations import tasks

    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        return_value=(None, terminal_code),
    ):
        # Must NOT raise — caller treats normal return as "no retry needed".
        tasks.ocr_extract_job(document.id)

    document.refresh_from_db()
    assert document.ocr_status == Document.OcrStatus.FAILED
    assert document.ocr_error_code == terminal_code


def test_upload_does_not_enqueue_for_member_portrait(settings):
    """member_portrait is outside OCR scope; upload must not enqueue."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = ParentAccount.objects.create(
        email="portrait-enqueue@example.com",
        phone="+37120000003",
    )

    from apps.registrations.services import create_or_update_draft

    enqueued_ids: list[int] = []

    def _spy_enqueue(document_id: int) -> None:
        enqueued_ids.append(document_id)

    with patch(
        "apps.registrations.services.enqueue_ocr_job",
        side_effect=_spy_enqueue,
    ):
        create_or_update_draft(
            data={
                "guardian_email": account.email,
                "guardian_full_name": "Portrait Parent",
                "guardian_personal_id": "010101-00003",
                "guardian_phone": "+37120000003",
                "guardian_declared_address": "Riga 3",
                "member_full_name": "Portrait Child",
                "member_personal_id": "010125-00003",
                "member_birth_date": "2025-01-01",
            },
            files={"member_portrait_document": _make_png()},
            verified_account=account,
        )

    assert enqueued_ids == []


def test_ocr_extract_job_normalizes_names_in_summary_but_preserves_raw_payload(settings):
    """encrypted_summary uses title-case names; encrypted_payload preserves raw provider casing."""
    from apps.documents.ocr import decrypt_json

    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    application = _make_application("normalize-summary@example.com")
    document = _make_document(application)

    fake_result = OCRExtractionResult(
        subject="guardian",
        person_fields={
            "first_name": "JĀNIS",
            "last_name": "BĒRZIŅŠ-KALNIŅŠ",
            "personal_id": "010101-12345",
        },
        document_metadata={"document_number": "LV1234567"},
        confidence={},
        flags=[],
        raw_reference={"provider": "tiny_idp"},
    )

    from apps.integrations import tasks

    with patch(
        "apps.integrations.tasks.safe_extract_document_data",
        return_value=(fake_result, None),
    ):
        tasks.ocr_extract_job(document.id)

    extraction = DocumentExtraction.objects.get(document=document)
    summary_text = decrypt_json(extraction.encrypted_summary)
    payload = decrypt_json(extraction.encrypted_payload)

    # Summary shows title-case names.
    assert "first_name: Jānis" in summary_text
    assert "last_name: Bērziņš-Kalniņš" in summary_text
    # Non-name fields untouched.
    assert "personal_id: 010101-12345" in summary_text
    # Raw payload preserves provider casing for audit.
    assert payload["person_fields"]["first_name"] == "JĀNIS"
    assert payload["person_fields"]["last_name"] == "BĒRZIŅŠ-KALNIŅŠ"

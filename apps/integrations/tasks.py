"""Background-job functions for the OCR pipeline.

`ocr_extract_job(document_id)` is the django-q2 job body. It calls the
existing `safe_extract_document_data` wrapper and persists results with
the same contract the synchronous P3 path used — only the call site
moved off the request thread.

`enqueue_ocr_job(document_id)` is the thin enqueue helper used by
`apps.registrations.services._handle_document_upload`. Keeping it
separate makes spying in tests trivial.
"""

from __future__ import annotations

from django.utils import timezone
from django_q.tasks import async_task

from apps.documents.models import Document, DocumentExtraction
from apps.documents.ocr import encrypt_json
from apps.integrations.ocr import OCR_SUPPORTED_KINDS, safe_extract_document_data
from apps.registrations.models import RegistrationApplication


class RetryableOCRError(Exception):
    """Raised by ocr_extract_job for transient classified failures.

    django-q2 retries the job up to `Q_CLUSTER.max_attempts` times when
    the job raises. Terminal failures (auth_failed, invalid_response,
    provider_misconfigured) persist FAILED and return normally so the
    runner does not retry them.
    """


_TRANSIENT_OCR_ERROR_CODES = frozenset(
    {"request_timeout", "provider_unavailable", "rate_limited"}
)


_OCR_FIELD_SOURCE_MAP: dict[str, dict[str, str]] = {
    "guardian_identity": {
        "guardian_full_name": "ocr_guardian_identity",
        "guardian_personal_id": "ocr_guardian_identity",
    },
    "member_identity": {
        "member_full_name": "ocr_member_identity",
        "member_personal_id": "ocr_member_identity",
    },
}


def enqueue_ocr_job(document_id: int) -> None:
    """Hand the OCR job to django-q2.

    In async mode (production cluster) async_task returns immediately and
    the worker handles any RetryableOCRError raised by the job. In sync
    mode (tests / DEBUG sync=True) the job runs in-process and any raise
    bubbles up here — that's a retry signal for the runner, not an error
    for the caller, so swallow it.
    """
    try:
        async_task("apps.integrations.tasks.ocr_extract_job", document_id)
    except RetryableOCRError:
        return


def ocr_extract_job(document_id: int) -> None:
    """Run OCR against a stored Document and persist the result.

    No-op for kinds outside OCR_SUPPORTED_KINDS.
    """
    try:
        document = Document.objects.select_related("application").get(pk=document_id)
    except Document.DoesNotExist:
        return

    if document.kind not in OCR_SUPPORTED_KINDS:
        return

    with document.file.open("rb") as fh:
        content = fh.read()

    result, error_code = safe_extract_document_data(
        kind=document.kind,
        file_name=document.original_filename,
        content=content,
        content_type=document.content_type,
    )

    if result is None:
        classified = error_code or "provider_unavailable"
        document.ocr_status = Document.OcrStatus.FAILED
        document.ocr_error_code = classified
        document.save(update_fields=["ocr_status", "ocr_error_code", "updated_at"])
        if classified in _TRANSIENT_OCR_ERROR_CODES:
            raise RetryableOCRError(classified)
        return

    encrypted_payload = encrypt_json(
        {
            "subject": result.subject,
            "person_fields": result.person_fields,
            "document_metadata": result.document_metadata,
            "confidence": result.confidence,
            "flags": result.flags,
            "raw_reference": result.raw_reference,
        }
    )
    summary_lines: list[str] = []
    for key, value in result.person_fields.items():
        summary_lines.append(f"{key}: {value}")
    for key, value in result.document_metadata.items():
        summary_lines.append(f"{key}: {value}")
    encrypted_summary = encrypt_json("\n".join(summary_lines))

    DocumentExtraction.objects.create(
        document=document,
        subject_role=result.subject,
        provider=str(result.raw_reference.get("provider", "")),
        extraction_schema_version="v1",
        encrypted_payload=encrypted_payload,
        encrypted_summary=encrypted_summary,
    )
    document.ocr_status = Document.OcrStatus.COMPLETED
    document.ocr_provider = str(result.raw_reference.get("provider", ""))
    document.ocr_last_processed_at = timezone.now()
    document.save(
        update_fields=[
            "ocr_status",
            "ocr_provider",
            "ocr_last_processed_at",
            "updated_at",
        ]
    )
    _apply_field_sources(document.application, document.kind)


def _apply_field_sources(application: RegistrationApplication, kind: str) -> None:
    field_map = _OCR_FIELD_SOURCE_MAP.get(kind)
    if not field_map:
        return
    # Submit-while-OCR-pending: once the application leaves DRAFT, its
    # captured data is frozen. Late job completions still write
    # DocumentExtraction (so admin sees the data) but must not mutate
    # field_sources on the submitted record.
    if application.status != RegistrationApplication.Status.DRAFT:
        return
    sources = dict(application.field_sources) if application.field_sources else {}
    sources.update(field_map)
    application.field_sources = sources
    application.save(update_fields=["field_sources", "updated_at"])

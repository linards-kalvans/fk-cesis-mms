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

import logging

from django.utils import timezone
from django_q.tasks import async_task

from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_signed
from apps.documents.models import Document, DocumentExtraction
from apps.documents.ocr import encrypt_json
from apps.integrations import agreement_platform
from apps.integrations import invoice_platform
from apps.integrations.name_normalization import normalize_latvian_name
from apps.integrations.ocr import OCR_SUPPORTED_KINDS, safe_extract_document_data
from apps.registrations.models import RegistrationApplication

logger = logging.getLogger(__name__)


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

# Person-field keys whose values are Latvian person names and therefore
# need title-case normalization when shown in the encrypted_summary. The
# parent registration form intentionally has no middle_name field, so
# middle_name is normalized for summary display only (no prefill read).
_NAME_KEYS = ("first_name", "last_name", "middle_name")


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
        display_value = normalize_latvian_name(value) if key in _NAME_KEYS else value
        summary_lines.append(f"{key}: {display_value}")
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


# ---------------------------------------------------------------------------
# Agreement-platform (DocuSeal) pipeline — P5 Slice D
# ---------------------------------------------------------------------------


class RetryableAgreementError(Exception):
    """Raised for transient agreement-platform failures so django-q2 retries."""


_AGREEMENT_ERROR_CODES: dict[type[Exception], tuple[str, bool]] = {
    agreement_platform.AgreementPlatformTransientError: ("unavailable", True),
    agreement_platform.AgreementPlatformAuthError: ("auth_failed", False),
    agreement_platform.AgreementPlatformConfigError: ("misconfigured", False),
    agreement_platform.AgreementPlatformNotFoundError: ("not_found", False),
}


def _classify_agreement_error(exc: Exception) -> tuple[str, bool]:
    for exc_type, mapping in _AGREEMENT_ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return mapping
    return ("provider_error", False)


def _mark_agreement_failed(agreement: Agreement, code: str) -> None:
    agreement.external_state = "failed"
    agreement.external_error_code = code
    agreement.save(
        update_fields=["external_state", "external_error_code", "updated_at"]
    )


def enqueue_create_agreement_submission(agreement_id: int) -> None:
    try:
        async_task(
            "apps.integrations.tasks.create_agreement_submission", agreement_id
        )
    except RetryableAgreementError:
        return


def enqueue_sync_agreement_submission(agreement_id: int) -> None:
    try:
        async_task(
            "apps.integrations.tasks.sync_agreement_submission", agreement_id
        )
    except RetryableAgreementError:
        return


def enqueue_archive_agreement_submission(external_id: str) -> None:
    async_task(
        "apps.integrations.tasks.archive_agreement_submission", external_id
    )


def create_agreement_submission(agreement_id: int) -> None:
    try:
        agreement = Agreement.objects.select_related("member__guardian").get(
            pk=agreement_id
        )
    except Agreement.DoesNotExist:
        return
    try:
        result = agreement_platform.create_submission(agreement)
    except Exception as exc:
        code, retry = _classify_agreement_error(exc)
        _mark_agreement_failed(agreement, code)
        if retry:
            raise RetryableAgreementError(code) from exc
        return
    agreement.external_provider = "docuseal"
    agreement.external_id = result.external_id
    agreement.external_url = result.external_url
    agreement.external_state = result.external_state
    agreement.external_error_code = ""
    agreement.save(
        update_fields=[
            "external_provider",
            "external_id",
            "external_url",
            "external_state",
            "external_error_code",
            "updated_at",
        ]
    )


def sync_agreement_submission(agreement_id: int) -> None:
    try:
        agreement = Agreement.objects.get(pk=agreement_id)
    except Agreement.DoesNotExist:
        return
    if not agreement.external_id:
        return
    try:
        result = agreement_platform.sync_submission(agreement.external_id)
    except Exception as exc:
        code, retry = _classify_agreement_error(exc)
        _mark_agreement_failed(agreement, code)
        if retry:
            raise RetryableAgreementError(code) from exc
        return
    agreement.external_state = result.external_state
    agreement.external_error_code = ""
    agreement.save(
        update_fields=["external_state", "external_error_code", "updated_at"]
    )
    agreement.refresh_from_db(fields=["state"])
    if result.external_state == "completed" and agreement.state in (
        Agreement.State.GENERATED,
        Agreement.State.SENT,
    ):
        mark_agreement_signed(agreement, actor=None)


def archive_agreement_submission(external_id: str) -> None:
    try:
        agreement_platform.archive_submission(external_id)
    except Exception:
        logger.warning("DocuSeal archive failed for %s", external_id, exc_info=True)


# ---------------------------------------------------------------------------
# Invoicing (Invoice Ninja) push pipeline — P6 Slice B
# ---------------------------------------------------------------------------


class RetryableInvoiceError(Exception):
    """Raised for transient invoicing failures so django-q2 retries."""


_INVOICE_ERROR_CODES: dict[type[Exception], tuple[str, bool]] = {
    invoice_platform.InvoicePlatformTransientError: ("unavailable", True),
    invoice_platform.InvoicePlatformAuthError: ("auth_failed", False),
    invoice_platform.InvoicePlatformConfigError: ("misconfigured", False),
    invoice_platform.InvoicePlatformNotFoundError: ("not_found", False),
}


def _classify_invoice_error(exc: Exception) -> tuple[str, bool]:
    for exc_type, mapping in _INVOICE_ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return mapping
    return ("provider_error", False)


def enqueue_push_billing_record(record_id: int) -> None:
    try:
        async_task("apps.integrations.tasks.push_billing_record", record_id)
    except RetryableInvoiceError:
        return


def push_billing_record(record_id: int) -> None:
    from apps.billing.models import BillingRecord
    from apps.billing.services import materialize_installments

    try:
        record = BillingRecord.objects.select_related(
            "plan", "member__guardian"
        ).get(pk=record_id)
    except BillingRecord.DoesNotExist:
        return
    if record.status != BillingRecord.Status.CONFIRMED:
        return
    if record.external_status == "synced":
        return

    record.external_status = "pending"
    record.external_error_code = ""
    record.save(update_fields=["external_status", "external_error_code", "updated_at"])

    # Steps 1-2: ensure product + client (idempotent via stored external ids).
    try:
        plan = record.plan
        if not plan.external_product_id:
            plan.external_product_id = invoice_platform.ensure_product(plan).external_id
            plan.save(update_fields=["external_product_id", "updated_at"])
        guardian = record.member.guardian
        if not guardian.external_client_id:
            # Guardian has no updated_at — do not include it in update_fields.
            guardian.external_client_id = invoice_platform.ensure_client(guardian).external_id
            guardian.save(update_fields=["external_client_id"])
    except Exception as exc:
        code, retry = _classify_invoice_error(exc)
        record.external_status = "failed"
        record.external_error_code = code
        record.save(update_fields=["external_status", "external_error_code", "updated_at"])
        if retry:
            raise RetryableInvoiceError(code) from exc
        return

    # Step 3: materialize installment rows (idempotent).
    rows = materialize_installments(record)

    # Step 4: create one invoice per row lacking an external id.
    failed_code = ""
    for billing_invoice in rows:
        if billing_invoice.external_invoice_id:
            continue
        try:
            result = invoice_platform.create_invoice(record, billing_invoice)
        except Exception as exc:
            code, retry = _classify_invoice_error(exc)
            billing_invoice.external_status = "failed"
            billing_invoice.external_error_code = code
            billing_invoice.save(
                update_fields=["external_status", "external_error_code", "updated_at"]
            )
            if retry:
                record.external_status = "failed"
                record.external_error_code = code
                record.save(
                    update_fields=["external_status", "external_error_code", "updated_at"]
                )
                raise RetryableInvoiceError(code) from exc
            failed_code = failed_code or code
            continue
        billing_invoice.external_invoice_id = result.external_id
        billing_invoice.external_status = "created"
        billing_invoice.external_error_code = ""
        billing_invoice.save(
            update_fields=[
                "external_invoice_id",
                "external_status",
                "external_error_code",
                "updated_at",
            ]
        )

    # Step 5: roll up.
    if failed_code:
        record.external_status = "failed"
        record.external_error_code = failed_code
    else:
        record.external_status = "synced"
        record.external_error_code = ""
    record.save(update_fields=["external_status", "external_error_code", "updated_at"])


# ---------------------------------------------------------------------------
# Payment sync pipeline — P6 Slice C
# ---------------------------------------------------------------------------


def _sync_invoice_payment(billing_invoice) -> None:
    """Fetch + write the payment projection for one invoice. Raises on
    provider error (caller decides isolation vs. surfacing)."""
    result = invoice_platform.fetch_invoice_payment(billing_invoice.external_invoice_id)
    billing_invoice.payment_status = result.payment_status
    billing_invoice.paid_to_date = result.paid_to_date
    billing_invoice.balance = result.balance
    billing_invoice.last_payment_date = result.last_payment_date
    billing_invoice.last_synced_at = timezone.now()
    billing_invoice.save(
        update_fields=[
            "payment_status",
            "paid_to_date",
            "balance",
            "last_payment_date",
            "last_synced_at",
            "updated_at",
        ]
    )


def sync_billing_payments() -> None:
    """Scheduled nightly sweep: refresh the payment projection for every
    invoice with an external id. Per-row errors are logged and skipped so one
    bad row never aborts the run."""
    from apps.billing.models import BillingInvoice
    from apps.billing.services import roll_up_payment_status

    invoices = BillingInvoice.objects.exclude(external_invoice_id="").select_related(
        "billing_record"
    )
    touched: dict[int, object] = {}
    for billing_invoice in invoices:
        try:
            _sync_invoice_payment(billing_invoice)
        except Exception as exc:  # noqa: BLE001 - batch sweep isolates per-row failures
            logger.warning(
                "payment sync failed for invoice %s: %s", billing_invoice.pk, exc
            )
            continue
        touched[billing_invoice.billing_record_id] = billing_invoice.billing_record
    for record in touched.values():
        roll_up_payment_status(record)


def enqueue_sync_billing_record_payments(record_id: int) -> None:
    try:
        async_task(
            "apps.integrations.tasks.sync_billing_record_payments", record_id
        )
    except RetryableInvoiceError:
        return


def sync_billing_record_payments(record_id: int) -> None:
    """Manual single-record payment sync (admin action). Surfaces a terminal
    error on the record's payment_error_code; re-raises transient errors so
    the cluster retries."""
    from apps.billing.models import BillingRecord
    from apps.billing.services import roll_up_payment_status

    try:
        record = BillingRecord.objects.get(pk=record_id)
    except BillingRecord.DoesNotExist:
        return

    for billing_invoice in record.invoices.exclude(external_invoice_id=""):
        try:
            _sync_invoice_payment(billing_invoice)
        except Exception as exc:
            code, retry = _classify_invoice_error(exc)
            record.payment_error_code = code
            record.save(update_fields=["payment_error_code", "updated_at"])
            if retry:
                raise RetryableInvoiceError(code) from exc
            return

    if record.payment_error_code:
        record.payment_error_code = ""
        record.save(update_fields=["payment_error_code", "updated_at"])
    roll_up_payment_status(record)

"""Isolated worker for locally generated agreement PDFs.

This module imports no signing, notification, billing or provider code. It
renders outside long database locks, publishes exactly one immutable private
file under a row lock and records only generic/redacted error codes.
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django_q.tasks import async_task

from apps.agreements.models import (
    MAX_GENERATED_DOCUMENT_BYTES,
    Agreement,
    GeneratedAgreementDocument,
)
from apps.agreements.pdf_rendering import (
    agreement_renderer_provenance,
    render_agreement_pdf,
)

logger = logging.getLogger(__name__)

ERRORS = GeneratedAgreementDocument.ErrorCode
MAX_PDF_PAGES = 20
_PUBLICATION_STATES = frozenset(
    {Agreement.State.GENERATED, Agreement.State.SENT}
)


def _agreement_can_publish(agreement: Agreement | None) -> bool:
    """Reuse the request/retry eligibility rule at publication time.

    The agreement may have been voided, superseded or replaced while the
    worker rendered outside locks. Terminal/non-current rows must never gain
    a newly published artifact.
    """
    return bool(
        agreement is not None
        and agreement.document_backend == Agreement.DocumentBackend.LOCAL
        and agreement.is_current
        and agreement.state in _PUBLICATION_STATES
    )


def _delete_quietly(storage, name: str) -> None:
    try:
        storage.delete(name)
    except Exception:
        logger.warning("Agreement document file cleanup unavailable")


def enqueue_document_generation(document_id: int) -> None:
    """Single queue boundary (patched by tests and the on-commit caller)."""
    async_task(
        "apps.agreements.document_tasks.generate_agreement_document",
        document_id,
    )


def _fail_if_unchanged(document_id: int, error_code: str, started_at) -> None:
    """Fail only this pending attempt; never clobber a retry or ready row."""
    GeneratedAgreementDocument.objects.filter(
        pk=document_id,
        status=GeneratedAgreementDocument.Status.PENDING,
        updated_at=started_at,
    ).update(
        status=GeneratedAgreementDocument.Status.FAILED,
        error_code=error_code,
        updated_at=timezone.now(),
    )


def _publication_outcome(document_id: int, name: str, sha256: str) -> bool:
    """Fresh DB recheck after an uncertain publish (commit may have won).

    Returns True only when this exact file/hash is the persisted ready
    artifact. A failed query propagates: the caller must not delete bytes it
    cannot prove were never committed.
    """
    return bool(
        GeneratedAgreementDocument.objects.filter(
            pk=document_id,
            status=GeneratedAgreementDocument.Status.READY,
            file=name,
            sha256=sha256,
        ).exists()
    )


def _is_valid_pdf(pdf: object) -> bool:
    """Bound the bytes and require a structurally readable one-page+ PDF.

    A ``%PDF-`` magic prefix alone is insufficient: a text file with a forged
    header must never be published as an agreement.
    """
    if not isinstance(pdf, (bytes, bytearray)):
        return False
    data = bytes(pdf)
    if not data.startswith(b"%PDF-") or len(data) > MAX_GENERATED_DOCUMENT_BYTES:
        return False
    try:
        import pymupdf
    except Exception:
        # A missing/broken native parser must fail closed like any other
        # invalid output rather than escaping the worker as an unhandled job.
        return False

    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            return bool(1 <= document.page_count <= MAX_PDF_PAGES)
    except Exception:
        return False


def generate_agreement_document(document_id: int) -> None:
    """Render and publish one pending document; no-op for any other state."""
    row = GeneratedAgreementDocument.objects.filter(pk=document_id).first()
    if row is None or row.status != GeneratedAgreementDocument.Status.PENDING:
        return
    attempted_at = row.updated_at

    # Version/assets were frozen at request time; a changed renderer fails
    # closed before any render (the template version is immutable per row).
    try:
        current_provenance = agreement_renderer_provenance(
            row.template_version
        )
    except Exception:
        _fail_if_unchanged(document_id, ERRORS.VERSION_MISMATCH, attempted_at)
        return
    if not row.provenance or current_provenance != row.provenance:
        _fail_if_unchanged(document_id, ERRORS.VERSION_MISMATCH, attempted_at)
        return

    # Render outside every database lock.
    try:
        pdf = render_agreement_pdf(
            row.snapshot, template_version=row.template_version
        )
    except ValueError:
        # Renderer-enforced document limits are invalid output, not an
        # infrastructure failure; the frozen input remains retryable.
        _fail_if_unchanged(document_id, ERRORS.INVALID_OUTPUT, attempted_at)
        return
    except Exception:
        _fail_if_unchanged(document_id, ERRORS.RENDER_FAILED, attempted_at)
        return
    if not _is_valid_pdf(pdf):
        _fail_if_unchanged(document_id, ERRORS.INVALID_OUTPUT, attempted_at)
        return
    data = bytes(pdf)
    data_hash = hashlib.sha256(data).hexdigest()

    storage = row.file.storage
    temporary_name = ""
    # Default is to clean our temporary write. It flips only when publication
    # or a fresh DB recheck proves this exact file is the persisted artifact —
    # or when the outcome is unknowable and deleting could destroy a winner.
    keep_temporary = True
    try:
        with transaction.atomic():
            # Same lock order as request/retry: the Agreement row first, then
            # its generated-document row. Rendering already happened outside
            # every lock; only publication is serialised here.
            locked_agreement = (
                Agreement.objects.select_for_update(of=("self",))
                .filter(pk=row.agreement_id)
                .first()
            )
            # A void/superseded/non-current agreement may have changed while
            # the worker rendered. Recheck under the Agreement lock, before
            # taking the document lock, so no new bytes are created for it;
            # record a redacted failure for this attempt only and leave any
            # existing READY artifact untouched.
            if not _agreement_can_publish(locked_agreement):
                _fail_if_unchanged(
                    document_id, ERRORS.GENERATION_UNAVAILABLE, attempted_at
                )
                return
            winner = (
                GeneratedAgreementDocument.objects.select_for_update()
                .filter(pk=document_id)
                .first()
            )
            if (
                winner is None
                or winner.status != GeneratedAgreementDocument.Status.PENDING
                or winner.updated_at != attempted_at
            ):
                return
            temporary_name = storage.save(
                f"agreements/generated/{uuid.uuid4().hex}.pdf",
                ContentFile(data),
            )
            winner.file.name = temporary_name
            winner.size_bytes = len(data)
            winner.sha256 = data_hash
            winner.ready_at = timezone.now()
            winner.snapshot = {}
            winner.status = GeneratedAgreementDocument.Status.READY
            winner.error_code = ""
            winner.save(
                update_fields=[
                    "file",
                    "size_bytes",
                    "sha256",
                    "ready_at",
                    "snapshot",
                    "status",
                    "error_code",
                    "updated_at",
                ]
            )
        keep_temporary = False
    except Exception:
        if not temporary_name:
            _fail_if_unchanged(document_id, ERRORS.RENDER_FAILED, attempted_at)
            return
        try:
            committed = _publication_outcome(
                document_id, temporary_name, data_hash
            )
        except Exception:
            # Commit may have won and the DB is currently unreadable. Deleting
            # the file could destroy the only copy of a published artifact, so
            # leave the orphan for operator reconciliation instead.
            keep_temporary = False
            logger.warning(
                "Agreement document publication outcome unknown; "
                "leaving file for reconciliation"
            )
        else:
            if committed:
                keep_temporary = False
            else:
                _fail_if_unchanged(
                    document_id, ERRORS.RENDER_FAILED, attempted_at
                )
    finally:
        if temporary_name and keep_temporary:
            _delete_quietly(storage, temporary_name)

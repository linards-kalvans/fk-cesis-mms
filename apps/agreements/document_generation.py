"""Explicit local agreement PDF generation: freeze, queue and publish.

The services here never touch signing, mail, billing or a provider. A staff
request freezes the minimum render input under the agreement row lock, queues
one worker job after the surrounding transaction commits, and leaves the
single ``GeneratedAgreementDocument`` row pending until the worker publishes
an immutable private PDF.

The frozen snapshot exists only while the row is pending/failed (so a retry
never reads changed guardian data) and is cleared on publication. It must
never reach admin forms, logs, audit metadata or exports.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from typing import cast

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from apps.agreements.models import (
    MAX_GENERATED_DOCUMENT_BYTES,
    Agreement,
    GeneratedAgreementDocument,
)
from apps.agreements.pdf_rendering import (
    PRODUCTION_TEMPLATE_VERSION,
    agreement_renderer_provenance,
    validate_snapshot,
)
from apps.agreements.document_tasks import enqueue_document_generation

logger = logging.getLogger(__name__)

ERRORS = GeneratedAgreementDocument.ErrorCode

# A pending job older than this is treated as lost and may be retried. Must be
# longer than the worker timeout (60s) so a still-running job is not raced.
STALE_PENDING_AFTER = timedelta(minutes=5)

_REQUEST_STATES = frozenset(
    {Agreement.State.GENERATED, Agreement.State.SENT}
)


def _generation_unavailable() -> ValueError:
    """Generic error without PII or internals for staff surfaces."""
    return ValueError(ERRORS.GENERATION_UNAVAILABLE)


def _ensure_generation_target(agreement: Agreement) -> None:
    """Only an active local agreement may freeze or retry generation."""
    if agreement.document_backend != Agreement.DocumentBackend.LOCAL:
        raise _generation_unavailable()
    if not agreement.is_current:
        raise _generation_unavailable()
    if agreement.state not in _REQUEST_STATES:
        raise _generation_unavailable()


def _format_birth_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _first_text(*values) -> str:
    for value in values:
        text = (value or "").strip()
        if text:
            return text
    return ""


def _frozen_snapshot(agreement: Agreement) -> dict:
    """Capture the exact document contract; never OCR, group or billing data.

    Child values prefer the canonical Member row and fall back to the
    registration application's legacy snapshot when the member field is blank.
    Required identity/address fields fail closed generically when neither
    source has a value. Guardian contact details stay optional: a paper
    agreement may legitimately have no email/phone, and the electronic-path
    guard remains a lifecycle concern, not a freeze-time rewrite.
    """
    member = agreement.member
    guardian = member.guardian
    application = getattr(member, "source_application", None)
    child_address = _first_text(
        getattr(application, "member_actual_address", "")
    )
    if not child_address and getattr(
        application, "member_same_address_as_guardian", False
    ):
        child_address = _first_text(guardian.address)
    fields = {
        "agreement_number": agreement.agreement_number or "",
        "child_name": _first_text(
            member.full_name, getattr(application, "member_full_name", "")
        ),
        "child_personal_id": _first_text(
            member.personal_id, getattr(application, "member_personal_id", "")
        ),
        "child_birth_date": _format_birth_date(
            member.birth_date
            or getattr(application, "member_birth_date", None)
        ),
        "child_address": child_address,
        "guardian_name": _first_text(guardian.display_name),
        "guardian_personal_id": _first_text(guardian.personal_id),
        "guardian_address": _first_text(guardian.address),
        "guardian_email": _first_text(guardian.email),
        "guardian_phone": _first_text(guardian.phone),
    }
    required = (
        "child_name",
        "child_personal_id",
        "child_birth_date",
        "child_address",
        "guardian_name",
        "guardian_personal_id",
        "guardian_address",
    )
    if any(not fields[name] for name in required):
        raise _generation_unavailable()
    return validate_snapshot(
        {"fields": fields, "signing_path": agreement.signing_path}
    )


def _fail_if_unchanged(document_id: int, error_code: str, started_at) -> None:
    """Record a redacted failure only for the same pending attempt.

    A newer retry or a ready publication changes ``updated_at``; a stale worker
    must not overwrite that newer state with its own failure.
    """
    GeneratedAgreementDocument.objects.filter(
        pk=document_id,
        status=GeneratedAgreementDocument.Status.PENDING,
        updated_at=started_at,
    ).update(
        status=GeneratedAgreementDocument.Status.FAILED,
        error_code=error_code,
        updated_at=timezone.now(),
    )


def _enqueue_safely(document_id: int, attempted_at, enqueue) -> None:
    """Queue after commit; a broker failure is visible but never PII-leaking."""
    try:
        enqueue(document_id)
    except Exception:
        _fail_if_unchanged(document_id, ERRORS.QUEUE_FAILED, attempted_at)
        logger.warning("Agreement document generation queue unavailable")


def _delete_quietly(storage, name: str) -> None:
    try:
        storage.delete(name)
    except Exception:
        logger.warning("Agreement document file cleanup unavailable")


def request_document_generation(
    agreement: Agreement,
    actor,  # noqa: ARG001 — reserved for the later staff audit hook
) -> GeneratedAgreementDocument:
    """Freeze and queue generation for an active local agreement.

    Idempotent: an existing document row (pending, failed or ready) is
    returned unchanged; retries use :func:`retry_document_generation`.
    """
    with transaction.atomic():
        locked = (
            Agreement.objects.select_for_update(of=("self",))
            .select_related(
                "member__guardian__parent_account",
                "member__source_application",
            )
            .get(pk=agreement.pk)
        )
        _ensure_generation_target(locked)
        existing = GeneratedAgreementDocument.objects.filter(
            agreement=locked
        ).first()
        if existing is not None:
            return cast(GeneratedAgreementDocument, existing)

        try:
            snapshot = _frozen_snapshot(locked)
            provenance = agreement_renderer_provenance(
                PRODUCTION_TEMPLATE_VERSION
            )
        except ValueError:
            raise _generation_unavailable() from None
        except Exception:
            # Asset/version probing can expose internal paths or digests; the
            # staff-facing contract is the same generic fail-closed error.
            raise _generation_unavailable() from None

        document = GeneratedAgreementDocument.objects.create(
            agreement=locked,
            status=GeneratedAgreementDocument.Status.PENDING,
            template_version=PRODUCTION_TEMPLATE_VERSION,
            signing_path=locked.signing_path,
            snapshot=snapshot,
            provenance=provenance,
        )
        transaction.on_commit(
            lambda pk=document.pk, at=document.updated_at, enqueue=enqueue_document_generation: (
                _enqueue_safely(pk, at, enqueue)
            )
        )
    return cast(GeneratedAgreementDocument, document)


def _can_retry(document: GeneratedAgreementDocument) -> bool:
    if not document.snapshot:
        return False
    if document.status == GeneratedAgreementDocument.Status.FAILED:
        return True
    return bool(
        document.status == GeneratedAgreementDocument.Status.PENDING
        and document.updated_at < timezone.now() - STALE_PENDING_AFTER
    )


def local_document_control_state(
    agreement: Agreement | None,
    document: GeneratedAgreementDocument | None,
) -> dict[str, bool]:
    """Single presentation policy shared by every staff surface.

    Mirrors this module's own request/retry eligibility so the registration
    admin, the family hub and the Admin Hub cannot drift apart or offer a
    control the service would refuse:

    * **generate** — an active local agreement in ``generated``/``sent`` with
      no existing document row (explicit request only);
    * **retry** — an existing failed document, or a pending one older than
      the worker-reclaim window, with its frozen snapshot still present.

    Ready files and fresh pending jobs stay read-only. Terminal lifecycle
    states (signed/void/superseded/discontinued) expose neither control.
    """
    eligible = (
        agreement is not None
        and agreement.document_backend == Agreement.DocumentBackend.LOCAL
        and agreement.is_current
        and agreement.state in _REQUEST_STATES
    )
    if not eligible:
        return {"generate": False, "retry": False}
    if document is None:
        return {"generate": True, "retry": False}
    return {"generate": False, "retry": _can_retry(document)}


def retry_document_generation(
    agreement: Agreement,
    actor,  # noqa: ARG001 — reserved for the later staff audit hook
) -> GeneratedAgreementDocument:
    """Re-queue an agreement's failed/stale document with its frozen input.

    The agreement PK and the generated-document PK live in separate tables and
    are not interchangeable. Resolve by ``agreement_id`` while holding the
    agreement row lock so two retries cannot compete on different rows.
    """
    with transaction.atomic():
        locked_agreement = (
            Agreement.objects.select_for_update(of=("self",))
            .get(pk=agreement.pk)
        )
        _ensure_generation_target(locked_agreement)
        document = (
            GeneratedAgreementDocument.objects.select_for_update()
            .filter(agreement_id=locked_agreement.pk)
            .first()
        )
        if document is None:
            raise ValueError(ERRORS.NOT_RETRYABLE)
        if not _can_retry(document):
            raise ValueError(ERRORS.NOT_RETRYABLE)
        document.status = GeneratedAgreementDocument.Status.PENDING
        document.error_code = ""
        document.save(update_fields=["status", "error_code", "updated_at"])
        transaction.on_commit(
            lambda pk=document.pk, at=document.updated_at, enqueue=enqueue_document_generation: (
                _enqueue_safely(pk, at, enqueue)
            )
        )
    return cast(GeneratedAgreementDocument, document)


def get_ready_document(agreement: Agreement) -> GeneratedAgreementDocument:
    """Return the agreement's ready document or fail closed.

    Used by upcoming lifecycle guards and document routes; a missing row,
    pending/failed state or missing stored name is never a ready artifact.
    Queried fresh by ``agreement_id`` so a stale cached reverse relation can
    never make a pending row look ready (or vice versa).
    """
    document = GeneratedAgreementDocument.objects.filter(
        agreement_id=agreement.pk
    ).first()
    if (
        document is None
        or document.status != GeneratedAgreementDocument.Status.READY
        or not document.file.name
    ):
        raise ValueError(ERRORS.NOT_READY)
    return cast(GeneratedAgreementDocument, document)


def read_ready_document_bytes(
    document: GeneratedAgreementDocument,
) -> bytes:
    """Read a ready document with bounded size and SHA-256 verification.

    The reader never falls back to rendering or a provider. A missing file,
    stale size/hash or unexpected bytes fail closed with a generic error.
    """
    if (
        document.status != GeneratedAgreementDocument.Status.READY
        or not document.file.name
    ):
        raise ValueError(ERRORS.NOT_READY)
    expected_size = int(document.size_bytes or 0)
    if expected_size <= 0 or expected_size > MAX_GENERATED_DOCUMENT_BYTES:
        raise ValueError(ERRORS.UNAVAILABLE)
    try:
        with document.file.storage.open(document.file.name, "rb") as handle:
            data = handle.read(MAX_GENERATED_DOCUMENT_BYTES + 1)
    except Exception:
        raise ValueError(ERRORS.UNAVAILABLE) from None
    if (
        len(data) != expected_size
        or len(data) > MAX_GENERATED_DOCUMENT_BYTES
        or hashlib.sha256(data).hexdigest() != document.sha256
        or not data.startswith(b"%PDF-")
    ):
        raise ValueError(ERRORS.INTEGRITY)
    return cast(bytes, data)


def read_agreement_document_bytes(agreement: Agreement) -> bytes:
    """Convenience reader for route/lifecycle callers holding an Agreement."""
    return read_ready_document_bytes(get_ready_document(agreement))


@receiver(post_delete, sender=GeneratedAgreementDocument)
def _remove_generated_document_file(sender, instance, **kwargs) -> None:
    """Delete published bytes only after the database row deletion commits."""
    if instance.file.name:
        storage, name = instance.file.storage, instance.file.name
        transaction.on_commit(lambda: _delete_quietly(storage, name))

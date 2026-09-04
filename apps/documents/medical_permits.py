"""P23 — MedicalPermit service layer.

Validity rule: an upload or staff confirmation recorded in calendar year N is
valid through 30 September of N+1. A staff confirmation represents club-held
evidence: it never stores a file.

Safety rule for replacement: the candidate is validated first, written to
private storage, and the new metadata persisted — only then is the prior
stored file deleted. Any failure before the persistence step leaves the old
file and row reference untouched; an orphan candidate is removed when
practical without masking the original failure.

Audit contract: every mutation records a redacted ``AuditEvent`` — never a
filename, personal/medical value, or file byte.
"""

import datetime
from typing import cast

from django.utils import timezone

from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent
from apps.documents.models import MedicalPermit, medical_permit_upload_to

MAX_MEDICAL_PERMIT_BYTES = 25 * 1024 * 1024

_ALLOWED_PAIRS = (
    ("pdf", "application/pdf"),
    ("jpg", "image/jpeg"),
    ("jpeg", "image/jpeg"),
    ("png", "image/png"),
    ("heic", "image/heic"),
)

MEDICAL_PERMIT_STATUS_LABELS = {
    "missing": "Vēl nav iesniegta",
    "current": "Derīga",
    "expiring": "Darbības termiņš drīz beigsies",
    "expired": "Darbības termiņš beidzies",
}


def _valid_until_for(year: int) -> datetime.date:
    """Fixed validity endpoint: 30 September of the year after ``year``."""
    return datetime.date(year + 1, 9, 30)


def medical_permit_status(permit, *, on: datetime.date | None = None) -> str:
    """Classify a permit as ``missing`` / ``current`` / ``expiring`` / ``expired``.

    ``missing`` covers no-permit rows and records with neither a stored file
    nor a staff confirmation. ``expiring`` is inclusive of 1 August through
    30 September of the validity year; ``expired`` starts 1 October.
    """
    if on is None:
        on = timezone.localdate()
    if permit is None:
        return "missing"
    if not permit.file and not permit.confirmed_by_id:
        return "missing"
    if on < permit.valid_until.replace(month=8, day=1):
        return "current"
    if on <= permit.valid_until:
        return "expiring"
    return "expired"


def medical_permit_status_label(status: str) -> str:
    return MEDICAL_PERMIT_STATUS_LABELS.get(status, status)


def validate_medical_permit_upload(upload) -> None:
    """Validate an upload against the allowed format/size contract.

    Returns ``None`` when acceptable; raises ``ValueError`` otherwise. Both
    the filename extension and the declared MIME type must be an allowed,
    matching pair (PDF, JPG/JPEG, PNG, HEIC), and the size must not exceed
    25 MiB.
    """
    if upload is None:
        raise ValueError("Fails nav izvēlēts.")
    if upload.size > MAX_MEDICAL_PERMIT_BYTES:
        raise ValueError("Fails pārsniedz 25 MB lieluma ierobežojumu.")
    name = str(getattr(upload, "name", "") or "")
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    content_type = str(getattr(upload, "content_type", "") or "").lower()
    if (extension, content_type) not in _ALLOWED_PAIRS:
        raise ValueError("Neatbalstīts faila formāts vai satura tips.")
    return None


def _write_permit_file(
    permit: MedicalPermit, upload, *, source: str
) -> MedicalPermit:
    """Persist a validated upload onto the permit row (safe replacement).

    The candidate is written to private storage first, then the row metadata
    is updated; only after a successful database write is the prior stored
    file deleted. On any failure before persistence the old row reference and
    old file remain untouched; an orphan candidate is best-effort removed
    without masking the original exception.
    """
    storage = permit.file.storage
    candidate_name = None
    old_name = permit.file.name or ""
    try:
        candidate_name = storage.save(medical_permit_upload_to(permit, upload.name), upload)
        permit.file.name = candidate_name
        permit.original_filename = upload.name
        permit.content_type = upload.content_type
        permit.file_size = upload.size
        permit.source = source
        permit.valid_until = _valid_until_for(timezone.localdate().year)
        permit.confirmed_by = None
        permit.confirmed_at = None
        permit.save(
            update_fields=[
                "file",
                "original_filename",
                "content_type",
                "file_size",
                "source",
                "valid_until",
                "confirmed_by",
                "confirmed_at",
                "updated_at",
            ]
        )
    except Exception:
        if candidate_name:
            try:
                storage.delete(candidate_name)
            except Exception:  # noqa: BLE001 — cleanup must not mask the failure
                pass
        raise
    if old_name:
        try:
            storage.delete(old_name)
        except Exception:  # noqa: BLE001 — cleanup must not mask a successful write
            pass
    return permit


def replace_medical_permit(
    permit: MedicalPermit,
    upload,
    *,
    actor_label: str,
    actor=None,
) -> MedicalPermit:
    """Replace the permit's stored file with a validated upload.

    The source is ``staff_upload`` when an actor is supplied, else
    ``parent_upload``. A prior staff confirmation is cleared. Emits
    ``medical_permit_replaced``.
    """
    validate_medical_permit_upload(upload)
    source = (
        str(MedicalPermit.Source.STAFF_UPLOAD)
        if actor is not None
        else str(MedicalPermit.Source.PARENT_UPLOAD)
    )
    _write_permit_file(permit, upload, source=source)
    record_audit_event(
        action=str(AuditEvent.Action.MEDICAL_PERMIT_REPLACED),
        actor=actor,
        actor_label=actor_label,
        target=permit,
        metadata={"source": permit.source},
    )
    return permit


def upload_application_medical_permit(
    application,
    upload,
    *,
    actor_label: str,
    actor=None,
) -> MedicalPermit:
    """First material upload for an application permit — create or fill.

    A record with no stored file yet (or no record at all) is classified as
    an upload (``medical_permit_uploaded``); a later upload replaces the
    stored file (``medical_permit_replaced``).
    """
    validate_medical_permit_upload(upload)
    permit = cast("MedicalPermit | None", getattr(application, "medical_permit", None))
    if permit is not None and permit.file:
        return replace_medical_permit(
            permit, upload, actor_label=actor_label, actor=actor
        )
    if permit is None:
        permit = MedicalPermit.objects.create(
            application=application,
            source=(
                str(MedicalPermit.Source.STAFF_UPLOAD)
                if actor is not None
                else str(MedicalPermit.Source.PARENT_UPLOAD)
            ),
            valid_until=_valid_until_for(timezone.localdate().year),
        )
    _write_permit_file(
        permit,
        upload,
        source=(
            str(MedicalPermit.Source.STAFF_UPLOAD)
            if actor is not None
            else str(MedicalPermit.Source.PARENT_UPLOAD)
        ),
    )
    record_audit_event(
        action=str(AuditEvent.Action.MEDICAL_PERMIT_UPLOADED),
        actor=actor,
        actor_label=actor_label,
        target=permit,
        metadata={"source": permit.source},
    )
    return permit


def upload_member_medical_permit(
    member,
    upload,
    *,
    actor_label: str,
    actor=None,
) -> MedicalPermit:
    """Upload, create, or replace a member-linked permit.

    A member without a permit row gets one created, linked to both the
    member and its source approved application so traceability is retained.
    A member without a source application cannot receive a traceable permit
    and fails with ``ValueError``. The first material write is audited as
    ``medical_permit_uploaded``; later writes as ``medical_permit_replaced``.
    """
    validate_medical_permit_upload(upload)
    permit = cast("MedicalPermit | None", getattr(member, "medical_permit", None))
    source = (
        str(MedicalPermit.Source.STAFF_UPLOAD)
        if actor is not None
        else str(MedicalPermit.Source.PARENT_UPLOAD)
    )
    if permit is None:
        application = getattr(member, "source_application", None)
        if application is None:
            raise ValueError(
                "Veselības apliecību nevar izveidot bez pieteikuma."
            )
        permit = MedicalPermit.objects.create(
            application=application,
            member=member,
            source=source,
            valid_until=_valid_until_for(timezone.localdate().year),
        )
    if permit.file:
        return replace_medical_permit(
            permit, upload, actor_label=actor_label, actor=actor
        )
    _write_permit_file(permit, upload, source=source)
    record_audit_event(
        action=str(AuditEvent.Action.MEDICAL_PERMIT_UPLOADED),
        actor=actor,
        actor_label=actor_label,
        target=permit,
        metadata={"source": permit.source},
    )
    return permit


def confirm_medical_permit(permit: MedicalPermit, *, actor) -> MedicalPermit:
    """Record a staff confirmation (club-held evidence, no stored file).

    The database row is persisted as confirmation-only first (file cleared,
    source ``staff_confirmation``, validity reset to 30 September N+1 for a
    confirmation in year N); the prior private file is then deleted
    best-effort. A DB failure leaves the original row reference and file
    bytes intact; a later storage-delete failure may leave an orphan file on
    disk but never contradicts the persisted state. The stored metadata
    (filename/type/size) is retained as history of the held evidence. Emits
    ``medical_permit_confirmed``.
    """
    storage = permit.file.storage
    old_name = permit.file.name or ""
    permit.file = ""
    permit.source = str(MedicalPermit.Source.STAFF_CONFIRMATION)
    permit.valid_until = _valid_until_for(timezone.localdate().year)
    permit.confirmed_by = actor
    permit.confirmed_at = timezone.now()
    permit.save(
        update_fields=[
            "file",
            "source",
            "valid_until",
            "confirmed_by",
            "confirmed_at",
            "updated_at",
        ]
    )
    if old_name:
        try:
            storage.delete(old_name)
        except Exception:  # noqa: BLE001 — orphan file must not contradict persisted state
            pass
    record_audit_event(
        action=str(AuditEvent.Action.MEDICAL_PERMIT_CONFIRMED),
        actor=actor,
        target=permit,
        metadata={"source": permit.source},
    )
    return permit


def clear_medical_permit_confirmation(permit: MedicalPermit, *, actor) -> MedicalPermit:
    """Remove a staff confirmation.

    A stored file is never touched; when no file remains the record returns
    to the ``missing`` state. Emits ``medical_permit_confirmation_cleared``.
    """
    permit.confirmed_by = None
    permit.confirmed_at = None
    if permit.file:
        permit.source = str(MedicalPermit.Source.PARENT_UPLOAD)
    permit.save(
        update_fields=["confirmed_by", "confirmed_at", "source", "updated_at"]
    )
    record_audit_event(
        action=str(AuditEvent.Action.MEDICAL_PERMIT_CONFIRMATION_CLEARED),
        actor=actor,
        target=permit,
        metadata={"source": permit.source},
    )
    return permit


def attach_application_medical_permit(application, member) -> MedicalPermit | None:
    """Link the application's permit to the approved member (idempotent).

    Returns the permit when the application has one, else ``None``. A permit
    already linked to another member is never repointed.
    """
    permit = cast("MedicalPermit | None", getattr(application, "medical_permit", None))
    if permit is None:
        return None
    if permit.member_id is not None and permit.member_id != member.pk:
        return permit
    if permit.member_id == member.pk:
        return permit
    permit.member = member
    permit.save(update_fields=["member", "updated_at"])
    return permit
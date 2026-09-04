"""Document model — private child identity document uploads."""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.documents.storage import PrivateDocumentStorage

private_document_storage = PrivateDocumentStorage()


def medical_permit_upload_to(instance, filename) -> str:
    """Opaque, non-PII storage path for a stored medical permit.

    The stored name carries no personal data — only a random hex token plus
    the (validated) file extension so content sniffing stays deterministic.
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in {".pdf", ".jpg", ".jpeg", ".png", ".heic"}:
        ext = ""
    return f"private/medical-permits/{uuid.uuid4().hex}{ext}"


class Document(TimeStampedModel):
    """A private document attached to a registration application."""

    class Kind(models.TextChoices):
        GUARDIAN_IDENTITY = "guardian_identity", "Guardian identity"
        MEMBER_IDENTITY = "member_identity", "Member identity"
        MEMBER_IDENTITY_BACK = "member_identity_back", "Bērna ID kartes aizmugure"
        MEMBER_PORTRAIT = "member_portrait", "Member portrait"

    class OcrStatus(models.TextChoices):
        NOT_REQUESTED = "not_requested", "Not requested"
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    application = models.ForeignKey(
        "registrations.RegistrationApplication",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    kind = models.CharField(max_length=32, choices=Kind.choices)
    file = models.FileField(
        upload_to="private/documents/",
        storage=private_document_storage,
    )
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField(default=0)
    ocr_status = models.CharField(
        max_length=32,
        choices=OcrStatus.choices,
        default=OcrStatus.NOT_REQUESTED,
    )
    ocr_provider = models.CharField(max_length=64, default="", blank=True)
    ocr_last_processed_at = models.DateTimeField(null=True, blank=True)
    ocr_error_code = models.CharField(max_length=64, default="", blank=True)
    ocr_error_detail_redacted = models.TextField(default="", blank=True)
    uploaded_by_parent_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None

    def __str__(self):
        return f"{self.kind} — {self.original_filename}"


class DocumentExtraction(TimeStampedModel):
    """Encrypted OCR extraction result for a single document."""

    class SubjectRole(models.TextChoices):
        GUARDIAN = "guardian", "Guardian"
        MEMBER = "member", "Member"

    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name="extraction",
    )
    subject_role = models.CharField(max_length=32, default="", blank=True)
    provider = models.CharField(max_length=64, default="", blank=True)
    extraction_schema_version = models.CharField(max_length=32, default="v1", blank=True)
    encrypted_payload = models.TextField(default="", blank=True)
    encrypted_summary = models.TextField(default="", blank=True)

    def __str__(self):
        return f"Extraction — {self.subject_role} — {self.document}"


class MedicalPermit(TimeStampedModel):
    """A child's health-certificate permit (P23).

    One permit begins on a registration application (one-to-one) and gains a
    nullable one-to-one Member link when the application is approved. The
    stored file — when present — lives in private storage under an opaque
    non-PII path. ``staff_confirmation`` records club-held evidence and never
    stores a file.
    """

    class Source(models.TextChoices):
        PARENT_UPLOAD = "parent_upload", "Parent upload"
        STAFF_UPLOAD = "staff_upload", "Staff upload"
        STAFF_CONFIRMATION = "staff_confirmation", "Staff confirmation"

    application = models.OneToOneField(
        "registrations.RegistrationApplication",
        on_delete=models.CASCADE,
        related_name="medical_permit",
    )
    member = models.OneToOneField(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="medical_permit",
    )
    file = models.FileField(
        upload_to=medical_permit_upload_to,
        storage=private_document_storage,
        blank=True,
    )
    original_filename = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=255, blank=True, default="")
    file_size = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=32, choices=Source.choices)
    valid_until = models.DateField()
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_medical_permits",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Veselības apliecība #{self.pk}"

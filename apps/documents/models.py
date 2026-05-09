"""Document model — private child identity document uploads."""

from django.db import models

from apps.core.models import TimeStampedModel
from apps.documents.storage import PrivateDocumentStorage

private_document_storage = PrivateDocumentStorage()


class Document(TimeStampedModel):
    """A private document attached to a registration application."""

    class Kind(models.TextChoices):
        GUARDIAN_IDENTITY = "guardian_identity", "Guardian identity"
        MEMBER_IDENTITY = "member_identity", "Member identity"
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
    uploaded_by_parent_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_active(self) -> bool:
        return self.deleted_at is None

    def __str__(self):
        return f"{self.kind} — {self.original_filename}"

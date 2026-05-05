"""RegistrationApplication model — parent registration workflow."""

from django.db import models

from apps.core.models import TimeStampedModel


class RegistrationApplication(TimeStampedModel):
    """A parent's registration application for a child."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        FIX_REQUESTED = "fix_requested", "Fix requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    parent_account = models.ForeignKey(
        "accounts.ParentAccount",
        on_delete=models.CASCADE,
        related_name="applications",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)
    guardian_full_name = models.CharField(max_length=255, blank=True)
    guardian_personal_id = models.CharField(max_length=32, blank=True)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=32, blank=True)
    guardian_address = models.CharField(max_length=255, blank=True)
    child_full_name = models.CharField(max_length=255, blank=True)
    child_personal_id = models.CharField(max_length=32, blank=True)
    child_birth_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    def is_draft(self) -> bool:
        result: bool = self.status == self.Status.DRAFT
        return result

    def is_editable_by(self, parent_account):
        result: bool = bool(parent_account and self.parent_account_id == parent_account.id and self.is_draft())
        return result

    def __str__(self):
        return f"{self.guardian_email} — {self.child_full_name or 'draft'}"

"""RegistrationApplication model — parent registration workflow."""

import uuid

from django.db import models

from apps.core.models import TimeStampedModel


class RegistrationApplication(TimeStampedModel):
    """A parent's registration application for a child.

    Two-layer identity model:
    - claimed_email: typed email on draft save (a claim, not proof).
    - parent_account: nullable FK set after email verification.
    - draft_session_key: opaque token for same-browser draft continuity.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Melnraksts"
        SUBMITTED = "submitted", "Iesniegts"
        FIX_REQUESTED = "fix_requested", "Jālabo"
        APPROVED = "approved", "Apstiprināts"
        REJECTED = "rejected", "Noraidīts"

    parent_account = models.ForeignKey(
        "accounts.ParentAccount",
        on_delete=models.CASCADE,
        related_name="applications",
        null=True,
        blank=True,
    )
    claimed_email = models.EmailField(blank=True, default="")
    draft_session_key = models.UUIDField(default=uuid.uuid4, editable=False)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)

    # Guardian snapshot fields (P1 names)
    guardian_full_name = models.CharField(max_length=255, blank=True)
    guardian_personal_id = models.CharField(max_length=32, blank=True)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=32, blank=True)
    guardian_declared_address = models.CharField(max_length=255, blank=True)

    # Member (child/player) snapshot fields (P1 names)
    member_full_name = models.CharField(max_length=255, blank=True)
    member_personal_id = models.CharField(max_length=32, blank=True)
    member_birth_date = models.DateField(null=True, blank=True)
    member_actual_address = models.CharField(max_length=255, blank=True)
    member_same_address_as_guardian = models.BooleanField(default=False)

    # Kit sizes — FK to KitSizeOption
    member_kit_size_shirt = models.ForeignKey(
        "members.KitSizeOption",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shirt_applications",
    )
    member_kit_size_shorts = models.ForeignKey(
        "members.KitSizeOption",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shorts_applications",
    )

    class AgreementSigning(models.TextChoices):
        ELECTRONIC = "electronic", "Elektroniski"
        PAPER = "paper", "Ar roku, papīra dokuments"

    # Application-level fields
    preferred_agreement_signing = models.CharField(
        max_length=16,
        choices=AgreementSigning.choices,
        blank=True,
    )
    support_club_instead_of_multi_child_discount = models.BooleanField(
        null=True,
        blank=True,
        default=None,
    )

    # Field source classification (JSON)
    field_sources = models.JSONField(default=dict, blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)

    # Review metadata
    review_message = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Approval link — one-to-one via unique FK
    approved_member = models.OneToOneField(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_application",
    )

    def is_draft(self) -> bool:
        result: bool = self.status == self.Status.DRAFT
        return result

    def is_editable_by(self, parent_account):
        """Editable when parent owns it AND status is draft or fix_requested."""
        if not parent_account or self.parent_account_id != parent_account.id:
            result: bool = False
            return result
        if self.status in (self.Status.DRAFT, self.Status.FIX_REQUESTED):
            result = True
        else:
            result = False
        return result

    def __str__(self):
        return f"{self.guardian_email} — {self.member_full_name or 'draft'}"

"""RegistrationApplication model — parent registration workflow."""

import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel

PERSONAL_DATA_CONSENT_VERSION = "v1-2026-05"
"""Current version identifier for the personal-data-consent text.

Bump this string (and ship a new T&C template partial) whenever the consent
content materially changes. The version persisted on
`RegistrationApplication.personal_data_consent_version` records which text
the user agreed to.
"""


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

    class PaymentMode(models.TextChoices):
        UPFRONT = "upfront", "Vienā maksājumā"
        INSTALLMENTS = "installments", "Pa daļām"

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
    preferred_payment_mode = models.CharField(
        max_length=16,
        choices=PaymentMode.choices,
        blank=True,
    )
    referral_code = models.CharField(max_length=64, blank=True, default="")

    # Field source classification (JSON)
    field_sources = models.JSONField(default=dict, blank=True)

    # Personal-data-consent (P4 — gate UX lands in slice C)
    personal_data_consent_at = models.DateTimeField(null=True, blank=True)
    personal_data_consent_version = models.CharField(
        max_length=32, null=True, blank=True
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    # Marks one specific submission event delivered by the daily digest job (P19).
    # Not a status — it is a per-event delivery flag, cleared on the next submit.
    submission_digest_sent_at = models.DateTimeField(null=True, blank=True)

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

    # Canonical guardian (1:1 with ParentAccount), resolved at initiation.
    guardian = models.ForeignKey(
        "members.Guardian",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="applications",
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
        return f"{self.guardian_contact_email or self.claimed_email} — {self.member_full_name or 'draft'}"

    # --- Guardian-read accessors (Slice B2). No fallback to legacy columns. ---
    @property
    def guardian_name(self) -> str:
        return str(self.guardian.display_name) if self.guardian_id is not None else ""

    @property
    def guardian_first_name(self) -> str:
        return str(self.guardian.first_name) if self.guardian_id is not None else ""

    @property
    def guardian_family_name(self) -> str:
        return str(self.guardian.family_name) if self.guardian_id is not None else ""

    @property
    def guardian_pid(self) -> str:
        return str(self.guardian.personal_id) if self.guardian_id is not None else ""

    @property
    def guardian_contact_phone(self) -> str:
        return str(self.guardian.phone) if self.guardian_id is not None else ""

    @property
    def guardian_address(self) -> str:
        return str(self.guardian.address) if self.guardian_id is not None else ""

    @property
    def guardian_contact_email(self) -> str:
        return str(self.parent_account.email) if self.parent_account_id is not None else ""

    @property
    def guardian_profile_populated(self) -> bool:
        """True when this application's canonical Guardian profile is already
        filled (returning parent). Drives the locked-profile UX in Slice C."""
        if self.guardian_id is None:
            return False
        return bool(self.guardian.first_name.strip() and self.guardian.family_name.strip())


class RegistrationSubmissionDigestSettings(models.Model):
    """Singleton model for the daily submitted-registration digest job (P19).

    Configured recipients (active staff Users) receive a Bcc digest each
    morning summarising every application that has been submitted since the
    last successful run. ``last_successful_at`` is stamped on each successful
    delivery; ``submission_digest_sent_at`` on each included application is
    the per-row equivalent.
    """

    recipients = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="registration_submission_digest_settings",
        limit_choices_to=models.Q(is_active=True, is_staff=True),
    )
    last_successful_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Pēdējā veiksmīgā nosūtīšana"
    )

    class Meta:
        verbose_name = "Iesniegto pieteikumu kopsavilkuma iestatījumi"
        verbose_name_plural = "Iesniegto pieteikumu kopsavilkuma iestatījumi"

    def __str__(self) -> str:
        return "Iesniegto pieteikumu kopsavilkuma iestatījumi"

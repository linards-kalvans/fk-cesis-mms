"""Agreement domain model — internal state machine + DocuSeal reservations."""

from __future__ import annotations

from django.db import models

from apps.core.models import TimeStampedModel


class Agreement(TimeStampedModel):
    """Per-member membership agreement.

    Member→Agreement is many-to-one via FK + a partial UniqueConstraint on
    ``is_current``. At most one row per member can carry ``is_current=True``.
    Voiding keeps ``is_current=True`` so the void state stays visible until
    a regenerate explicitly archives it (flips ``is_current=False``) and
    creates a fresh row.
    """

    class State(models.TextChoices):
        GENERATED = "generated", "Sagatavots"
        SENT = "sent", "Nosūtīts parakstīšanai"
        SIGNED = "signed", "Parakstīts"
        VOID = "void", "Atcelts"
        SUPERSEDED = "superseded", "Aizvietots"
        DISCONTINUED = "discontinued", "Pārtraukts"

    class SigningPath(models.TextChoices):
        ELECTRONIC = "electronic", "Elektroniski"
        PAPER = "paper", "Ar roku, papīra dokuments"

    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="agreements",
    )
    is_current = models.BooleanField(default=True)
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.GENERATED,
    )
    signing_path = models.CharField(
        max_length=16,
        choices=SigningPath.choices,
        default=SigningPath.ELECTRONIC,
    )
    agreement_number = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
    )

    # Lifecycle timestamps
    generated_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True, default="")

    # Slice D reservations — DocuSeal adapter populates these; Slice C ignores.
    external_provider = models.CharField(max_length=32, blank=True, default="")
    external_id = models.CharField(max_length=128, blank=True, default="")
    external_state = models.CharField(max_length=64, blank=True, default="")
    external_url = models.URLField(blank=True, default="")
    external_error_code = models.CharField(max_length=64, blank=True, default="")

    # P9: agreement owns the billing intent that the signed transition will
    # realise. Staff sets these on the review detail; create_agreement_for_member
    # preselects the default plan + derived month when one is available.
    billing_plan = models.ForeignKey(
        "billing.MembershipPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agreements",
    )
    first_billing_month = models.CharField(max_length=7, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["member"],
                condition=models.Q(is_current=True),
                name="one_current_agreement_per_member",
            ),
        ]

    def __str__(self) -> str:
        return f"Agreement(member={self.member_id}, state={self.state})"

    def get_absolute_url(self) -> str:
        """Return the admin change-page URL for the application that
        approved this agreement's member, or an empty string when the
        member has no source application (defensive). Django admin uses
        this for the VIEW ON SITE button — staff transitions happen on
        the application change page (review panels), which is the entry
        point now that the bespoke review detail view is gone.
        """
        from django.urls import reverse

        application = getattr(self.member, "source_application", None)
        if application is None:
            return ""
        url: str = reverse(
            "admin:registrations_registrationapplication_change",
            args=[application.id],
        )
        return url


class AgreementLifecycleEvent(models.Model):
    """Parent-visible business history for an agreement.

    Distinct from AuditEvent: this is domain state, not the operator/forensic
    trail. It survives as readable history and is shown in the parent portal.
    """

    class EventType(models.TextChoices):
        MINOR_AMENDMENT = "minor_amendment", "Neliels labojums"
        MATERIAL_AMENDMENT_STARTED = (
            "material_amendment_started",
            "Sākta būtiska izmaiņu procedūra",
        )
        SUPERSEDED = "superseded", "Aizvietots ar jaunu līgumu"
        DISCONTINUED = "discontinued", "Dalība pārtraukta"
        CREDIT_NOTE_CREATED = "credit_note_created", "Izveidots kredītrēķins"
        CREDIT_NOTE_APPLIED = "credit_note_applied", "Kredīts piemērots rēķinam"
        CREDIT_NOTE_FAILED = "credit_note_failed", "Kredītrēķina izveide neizdevās"

    agreement = models.ForeignKey(
        Agreement,
        on_delete=models.CASCADE,
        related_name="lifecycle_events",
    )
    event_type = models.CharField(
        max_length=32,
        choices=EventType.choices,
    )
    note = models.TextField(blank=True, default="")
    effective_date = models.DateField(null=True, blank=True)
    actor_label = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.get_event_type_display()} @ {self.agreement_id}"

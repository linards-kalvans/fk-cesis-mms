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
        """Return the admin review-detail URL for the application that
        approved this agreement's member, or an empty string when the
        member has no source application (defensive). Django admin uses
        this for the VIEW ON SITE button — staff transitions happen on
        the review detail page, not in Django admin's read-only view.
        """
        from django.urls import reverse

        application = getattr(self.member, "source_application", None)
        if application is None:
            return ""
        url: str = reverse(
            "registrations:admin-review-detail", args=[application.id]
        )
        return url

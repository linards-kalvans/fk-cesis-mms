"""Abstract base model — auto-timestamps."""

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract model with ``created_at`` and ``updated_at``."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditEvent(models.Model):
    """Append-only audit record of a sensitive staff/system action.

    Immutable by design — no updated_at. The target is a denormalized string
    snapshot so the row survives the target's deletion (we audit deletions).
    """

    class Action(models.TextChoices):
        APPLICATION_APPROVED = "application_approved", "Application approved"
        APPLICATION_REJECTED = "application_rejected", "Application rejected"
        APPLICATION_FIX_REQUESTED = "application_fix_requested", "Application fix requested"
        TRAINING_GROUP_ASSIGNED = "training_group_assigned", "Training group assigned"
        TRAINING_GROUP_CLEARED = "training_group_cleared", "Training group cleared"
        DOCUMENT_PREVIEWED = "document_previewed", "Document previewed"
        DOCUMENT_DOWNLOADED = "document_downloaded", "Document downloaded"
        DOCUMENT_DELETED = "document_deleted", "Document deleted"
        AGREEMENT_SENT = "agreement_sent", "Agreement sent"
        AGREEMENT_SIGNED = "agreement_signed", "Agreement signed"
        AGREEMENT_VOIDED = "agreement_voided", "Agreement voided"
        AGREEMENT_SYNC_FAILED = "agreement_sync_failed", "Agreement sync failed"
        BILLING_PUSH_TRIGGERED = "billing_push_triggered", "Billing push triggered"
        PAYMENT_SYNC_TRIGGERED = "payment_sync_triggered", "Payment sync triggered"
        INVOICE_PUSH_FAILED = "invoice_push_failed", "Invoice push failed"
        INVOICE_SEND_FAILED = "invoice_send_failed", "Invoice send failed"
        PAYMENT_SYNC_FAILED = "payment_sync_failed", "Payment sync failed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor_label = models.CharField(max_length=255, blank=True, default="")
    action = models.CharField(max_length=64, choices=Action.choices)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_repr = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self) -> str:
        ts = self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else "unsaved"
        return f"{ts} {self.action} {self.target_repr}".strip()

"""Member-domain models: Guardian, TrainingGroup, Member, KitSizeOption,
MemberExportTemplate (P17)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import TimeStampedModel


_KIT_SIZE_ORDER = {
    "XXS": 0,
    "XS": 1,
    "S": 2,
    "M": 3,
    "L": 4,
    "XL": 5,
    "2XL": 6,
    "3XL": 7,
    "4XL": 8,
    "5XL": 9,
}


def kit_size_sort_key(label: str) -> tuple[int, int | str]:
    """Sort key for kit-size labels: numeric child sizes, then t-shirt sizes."""
    normalized = label.strip().upper()
    if normalized.isdecimal():
        return (0, int(normalized))
    known = _KIT_SIZE_ORDER.get(normalized)
    if known is not None:
        return (1, known)
    return (2, normalized)


class KitSizeOption(models.Model):
    """Admin-managed kit size lookup model."""

    class Kind(models.TextChoices):
        SHIRT = "shirt", "Shirt"
        SHORTS = "shorts", "Shorts"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    label = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.kind}: {self.label}"

    class Meta:
        ordering = ["kind", "label"]


class Guardian(models.Model):
    """Canonical parent/guardian record, 1:1 with ParentAccount, resolved at registration initiation and reused at approval."""

    first_name = models.CharField(max_length=255, blank=True, default="")
    family_name = models.CharField(max_length=255, blank=True, default="")
    personal_id = models.CharField(max_length=32, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    external_client_id = models.CharField(max_length=64, blank=True, default="")
    parent_account = models.OneToOneField(
        "accounts.ParentAccount",
        on_delete=models.PROTECT,
        blank=True,
        related_name="guardian",
    )

    @property
    def email(self) -> str:
        return self.parent_account.email if self.parent_account_id else ""

    @property
    def phone(self) -> str:
        return self.parent_account.phone if self.parent_account_id else ""

    @property
    def display_name(self) -> str:
        """Derived parent display name. P13 cleanup: replaces the removed
        ``full_name`` mirror column.
        """
        return " ".join(
            part for part in (self.first_name.strip(), self.family_name.strip()) if part
        )

    def __str__(self):
        return self.display_name or str(self.pk)

    class Meta:
        verbose_name = "Vecāks"
        verbose_name_plural = "Vecāki"


class TrainingGroup(models.Model):
    """A training group (e.g. U10 A)."""

    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), name="uniq_training_group_name_ci"
            )
        ]

    def clean(self):
        super().clean()
        clash = TrainingGroup.objects.filter(name__iexact=self.name)
        if self.pk is not None:
            clash = clash.exclude(pk=self.pk)
        if clash.exists():
            raise ValidationError(
                {"name": "Treniņu grupa ar šādu nosaukumu jau pastāv."}
            )

    def __str__(self):
        return self.name


class Member(models.Model):
    """A registered youth member."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Aktīvs"
        DISCONTINUED = "discontinued", "Pārtraukts"

    full_name = models.CharField(max_length=255)
    personal_id = models.CharField(max_length=32, blank=True, default="")
    birth_date = models.DateField(null=True, blank=True)
    guardian = models.ForeignKey(
        Guardian,
        on_delete=models.CASCADE,
        related_name="members",
    )
    training_group = models.ForeignKey(
        TrainingGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    discontinued_effective_date = models.DateField(null=True, blank=True)
    discontinuation_reason = models.TextField(blank=True, default="")
    discontinued_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.full_name or str(self.pk)


class MemberExportTemplate(TimeStampedModel):
    """A saved, configurable member-export configuration.

    Staff selects a list of column keys (from
    :data:`apps.members.exports.COLUMN_REGISTRY`), optionally narrows by
    agreement state(s) and/or training group(s), then runs the export — which
    streams a CSV/XLSX attachment straight from the admin run page. Templates
    are configuration only: the export itself never persists to disk.
    """

    name = models.CharField(max_length=128)
    column_keys = models.JSONField()
    agreement_status_filters = models.JSONField(default=list, blank=True)
    training_groups = models.ManyToManyField(
        TrainingGroup,
        blank=True,
        related_name="export_templates",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="member_export_templates_created",
    )

    class Meta:
        ordering = ("name", "pk")

    def __str__(self) -> str:
        name = self.name
        return str(name)

    def clean(self):
        super().clean()
        # Local import keeps models.py ↔ exports.py acyclic.
        from apps.members.exports import (
            validate_agreement_status_filters,
            validate_column_keys,
        )

        validate_column_keys(self.column_keys)
        validate_agreement_status_filters(self.agreement_status_filters)

"""Member-domain models: Guardian, TrainingGroup, Member, KitSizeOption."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


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


def split_guardian_full_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (first_name, family_name) using the last-token rule.

    Blank input -> both empty. Single token -> first only, family empty. Multiple
    tokens -> earlier tokens joined as first, last token as family. The split
    also collapses runs of internal whitespace, so a messy legacy "  Anna   Marija
    Ozola  " lands cleanly on ("Anna Marija", "Ozola").
    """
    parts = str(full_name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


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
    full_name = models.CharField(max_length=255)
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

    def sync_full_name(self) -> None:
        """Rebuild the ``full_name`` mirror from the explicit name parts.

        Centralises mirror construction so services, admin, and tests do not
        duplicate string assembly. Empty parts are skipped, so a single-token
        first name renders correctly without a stray double space.
        """
        self.first_name = (self.first_name or "").strip()
        self.family_name = (self.family_name or "").strip()
        self.full_name = " ".join(
            part for part in (self.first_name, self.family_name) if part
        )

    def __str__(self):
        return self.full_name or str(self.pk)

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

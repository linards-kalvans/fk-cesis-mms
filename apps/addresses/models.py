"""Local index of VZD address register data for assist-only autocomplete."""

from __future__ import annotations

from django.db import models


class AddressImportRun(models.Model):
    """Tracks one attempt to refresh the local address index."""

    class Status(models.TextChoices):
        RUNNING = "running", "running"
        SUCCEEDED = "succeeded", "succeeded"
        FAILED = "failed", "failed"

    source = models.CharField(max_length=64)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    region_codes = models.TextField(blank=True)
    group_count = models.PositiveIntegerField(default=0)
    entry_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    source_modified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.source}: {self.status}"


class AddressGroup(models.Model):
    """A searchable street/locality grouping such as 'Raiņa iela, Cēsis'."""

    label = models.CharField(max_length=255)
    normalized_label = models.CharField(max_length=255, db_index=True)
    street_code = models.CharField(max_length=32, blank=True)
    street_name = models.CharField(max_length=255, blank=True)
    locality_code = models.CharField(max_length=32, blank=True)
    locality_name = models.CharField(max_length=255, blank=True)
    region_code = models.CharField(max_length=32, blank=True, db_index=True)
    region_name = models.CharField(max_length=255, blank=True)
    entry_count = models.PositiveIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["street_code"]),
            models.Index(fields=["region_code", "locality_code"]),
        ]

    def __str__(self) -> str:
        return str(self.label)


class AddressEntry(models.Model):
    """One selectable building or land-unit address from AW_EKA."""

    vzd_code = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=255)
    normalized_label = models.CharField(max_length=255, db_index=True)
    group = models.ForeignKey(
        AddressGroup,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="entries",
    )
    postal_code = models.CharField(max_length=16, blank=True)
    region_code = models.CharField(max_length=32, blank=True, db_index=True)
    region_name = models.CharField(max_length=255, blank=True)
    koord_x = models.CharField(max_length=32, blank=True)
    koord_y = models.CharField(max_length=32, blank=True)
    dd_n = models.CharField(max_length=32, blank=True)
    dd_e = models.CharField(max_length=32, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["normalized_label"]),
            models.Index(fields=["group", "normalized_label"]),
            models.Index(fields=["region_code"]),
        ]

    def __str__(self) -> str:
        return str(self.label)

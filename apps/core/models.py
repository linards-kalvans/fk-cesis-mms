"""Abstract base model — auto-timestamps."""

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract model with ``created_at`` and ``updated_at``."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

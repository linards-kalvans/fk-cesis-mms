"""Member-domain models: Guardian, TrainingGroup, Member."""

from django.db import models


class Guardian(models.Model):
    """A parent/guardian record created on application approval."""

    full_name = models.CharField(max_length=255)
    personal_id = models.CharField(max_length=32, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return self.full_name or str(self.pk)


class TrainingGroup(models.Model):
    """A training group (e.g. U10 A)."""

    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Member(models.Model):
    """A registered youth member."""

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

    def __str__(self):
        return self.full_name or str(self.pk)

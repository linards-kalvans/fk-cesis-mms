"""TrainingGroup names are unique case-insensitively."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.members.models import TrainingGroup

pytestmark = pytest.mark.django_db


def test_duplicate_name_case_insensitive_raises_integrity_error():
    TrainingGroup.objects.create(name="U10 A")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TrainingGroup.objects.create(name="u10 a")


def test_distinct_names_allowed():
    TrainingGroup.objects.create(name="U10 A")
    TrainingGroup.objects.create(name="U12 B")
    assert TrainingGroup.objects.count() == 2


def test_clean_raises_validation_error_on_case_insensitive_clash():
    TrainingGroup.objects.create(name="U10 A")
    dup = TrainingGroup(name="u10 a")
    with pytest.raises(ValidationError):
        dup.clean()


def test_clean_allows_saving_same_instance():
    g = TrainingGroup.objects.create(name="U10 A")
    g.name = "U10 A"
    g.clean()  # editing the same row must not raise

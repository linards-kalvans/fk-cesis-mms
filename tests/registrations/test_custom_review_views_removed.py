"""The bespoke review queue/detail are gone; the admin is the entry point."""

import pytest
from django.urls import NoReverseMatch, reverse

pytestmark = pytest.mark.django_db


def test_old_review_routes_are_gone():
    with pytest.raises(NoReverseMatch):
        reverse("registrations:admin-review-queue")
    with pytest.raises(NoReverseMatch):
        reverse("registrations:admin-review-detail", args=[1])

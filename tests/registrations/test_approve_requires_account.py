"""Approval requires a parent account (no bare-Guardian fallback)."""

import pytest
from django.contrib.auth.models import User

from apps.registrations.models import RegistrationApplication
from apps.registrations.services import approve_application

pytestmark = pytest.mark.django_db


def test_approve_without_parent_account_raises():
    reviewer = User.objects.create_user("staff", "s@example.com", "pw", is_staff=True)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        member_full_name="Bērns",
        parent_account=None,  # no account → guardian cannot be resolved
    )
    with pytest.raises(ValueError):
        approve_application(app, reviewer)
    app.refresh_from_db()
    assert app.status == RegistrationApplication.Status.SUBMITTED  # unchanged

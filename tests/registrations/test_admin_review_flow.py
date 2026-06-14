"""Service-level review notifications + admin readonly guard.

The bespoke staff review queue/detail views were removed in P7 C-i (the
Django admin is the entry point now); the view-driven tests that lived here
moved to the admin test modules (test_admin_review_actions.py,
test_admin_changelist_quick_actions.py, test_admin_review_agreement_ui.py,
test_admin_review_group_assignment_ui.py). What remains here exercises the
underlying services (email on fix/reject/approve) and the admin readonly
contract — neither of which depended on the deleted views.
"""

import pytest
from django.contrib.auth.models import User
from unittest.mock import patch

from apps.registrations.services import (
    request_application_fix,
    reject_application,
    approve_application,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Email notifications on review actions (service-level)
# ---------------------------------------------------------------------------


class TestEmailOnReviewActions:
    """Review actions (fix, reject, approve) must send email to the parent."""

    def test_request_fix_sends_email(self, submitted_application):
        """request_application_fix must send an email to the parent."""
        staff_user = User.objects.create_superuser(
            username="fixstaff",
            email="fixstaff@example.com",
            password="fixstaffpass",
        )
        with patch("apps.registrations.services.send_mail") as mock_send:
            request_application_fix(submitted_application, staff_user, "Please fix the address.")
            assert mock_send.call_count >= 1

    def test_reject_sends_email(self, submitted_application):
        """reject_application must send an email to the parent."""
        staff_user = User.objects.create_superuser(
            username="rejectstaff",
            email="rejectstaff@example.com",
            password="rejectstaffpass",
        )
        with patch("apps.registrations.services.send_mail") as mock_send:
            reject_application(submitted_application, staff_user, "Does not meet requirements.")
            assert mock_send.call_count >= 1

    def test_approve_sends_email(self, submitted_application):
        """approve_application must send an approval email to the parent."""
        staff_user = User.objects.create_superuser(
            username="approvestaff",
            email="approvestaff@example.com",
            password="approvestaffpass",
        )
        with patch("apps.registrations.services.send_mail") as mock_send:
            approve_application(submitted_application, staff_user)
            assert mock_send.call_count >= 1


# ---------------------------------------------------------------------------
# Admin readonly — consent stamp fields must not be editable
# ---------------------------------------------------------------------------


def test_admin_consent_fields_are_readonly():
    """Admin must not allow staff to edit consent timestamps directly."""
    from apps.registrations.admin import RegistrationApplicationAdmin

    readonly = set(RegistrationApplicationAdmin.readonly_fields)
    assert "personal_data_consent_at" in readonly
    assert "personal_data_consent_version" in readonly

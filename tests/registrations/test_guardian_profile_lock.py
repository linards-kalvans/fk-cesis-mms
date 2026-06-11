"""Slice C — guardian-profile lock signal + form/view locking."""

import pytest

from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


class TestGuardianProfilePopulated:
    def test_false_when_no_guardian_linked(self):
        app = RegistrationApplication.objects.create(claimed_email="p@example.com")
        assert app.guardian_profile_populated is False

    def test_false_when_guardian_has_empty_full_name(self, parent_account, make_guardian):
        guardian = make_guardian(parent_account)  # full_name="" by default
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian
        )
        assert app.guardian_profile_populated is False

    def test_true_when_guardian_full_name_set(self, parent_account, make_guardian):
        guardian = make_guardian(parent_account, full_name="Anna Ozola")
        app = RegistrationApplication.objects.create(
            parent_account=parent_account, guardian=guardian
        )
        assert app.guardian_profile_populated is True

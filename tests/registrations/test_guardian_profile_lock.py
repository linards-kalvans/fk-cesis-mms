"""Slice C — guardian-profile lock signal + form/view locking."""

import pytest

from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db

GUARDIAN_PROFILE_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_phone",
    "guardian_declared_address",
)


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


class TestFormReadonlyLocking:
    def test_email_always_readonly(self):
        form = RegistrationApplicationForm()
        assert form.fields["guardian_email"].widget.attrs.get("readonly") == "readonly"

    def test_profile_fields_readonly_when_locked(self):
        form = RegistrationApplicationForm(guardian_profile_locked=True)
        for name in GUARDIAN_PROFILE_FIELDS:
            assert form.fields[name].widget.attrs.get("readonly") == "readonly", name

    def test_profile_fields_editable_when_unlocked(self):
        form = RegistrationApplicationForm(guardian_profile_locked=False)
        for name in GUARDIAN_PROFILE_FIELDS:
            assert "readonly" not in form.fields[name].widget.attrs, name

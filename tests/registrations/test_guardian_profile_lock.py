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


class TestWorkspaceLockWiring:
    def test_returning_parent_sees_locked_profile(self, verified_client, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)
        guardian.full_name = "Anna Ozola"
        guardian.save(update_fields=["full_name"])

        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )
        resp = verified_client.get(f"/applications/{app.id}/")
        assert resp.status_code == 200
        assert resp.context["guardian_profile_locked"] is True
        assert resp.context["form"].fields["guardian_full_name"].widget.attrs.get("readonly") == "readonly"

    def test_first_registration_profile_unlocked(self, verified_client, parent_account):
        from apps.members.services import resolve_guardian_for_account
        from apps.registrations.models import RegistrationApplication

        guardian = resolve_guardian_for_account(parent_account)  # empty profile
        app = RegistrationApplication.objects.create(
            parent_account=parent_account,
            guardian=guardian,
            claimed_email=parent_account.email,
        )
        resp = verified_client.get(f"/applications/{app.id}/")
        assert resp.status_code == 200
        assert resp.context["guardian_profile_locked"] is False
        assert "readonly" not in resp.context["form"].fields["guardian_full_name"].widget.attrs

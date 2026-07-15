"""P13 — registration form uses explicit guardian_first_name / guardian_family_name fields."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Form field contract
# ---------------------------------------------------------------------------


class TestGuardianNameFormFields:
    def test_form_has_explicit_name_fields(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        assert "guardian_first_name" in form.fields
        assert "guardian_family_name" in form.fields

    def test_form_does_not_have_guardian_full_name(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        assert "guardian_full_name" not in form.fields

    def test_labels_are_latvian(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm()
        assert form.fields["guardian_first_name"].label == "Vecāka vārds"
        assert form.fields["guardian_family_name"].label == "Vecāka uzvārds"

    def test_submit_required_fields_use_explicit_names(self):
        from apps.registrations.forms import RegistrationApplicationForm

        assert "guardian_first_name" in RegistrationApplicationForm.submit_required_fields
        assert "guardian_family_name" in RegistrationApplicationForm.submit_required_fields
        assert "guardian_full_name" not in RegistrationApplicationForm.submit_required_fields


# ---------------------------------------------------------------------------
# Service — draft save writes explicit fields and mirror
# ---------------------------------------------------------------------------


class TestDraftSaveGuardianNameParts:
    def test_draft_save_writes_explicit_fields_and_mirror(self, parent_account):
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": parent_account.email,
                "guardian_first_name": "Anna Marija",
                "guardian_family_name": "Ozola",
                "guardian_personal_id": "010180-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Cēsis",
            },
            files={},
            verified_account=parent_account,
        )
        guardian = app.guardian
        guardian.refresh_from_db()
        assert guardian.first_name == "Anna Marija"
        assert guardian.family_name == "Ozola"
        assert guardian.full_name == "Anna Marija Ozola"

    def test_draft_save_accepts_legacy_guardian_full_name_alias(self, parent_account):
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": parent_account.email,
                "guardian_full_name": "Jānis Kalniņš",
            },
            files={},
            verified_account=parent_account,
        )
        app.guardian.refresh_from_db()
        assert app.guardian.first_name == "Jānis"
        assert app.guardian.family_name == "Kalniņš"
        assert app.guardian.full_name == "Jānis Kalniņš"


# ---------------------------------------------------------------------------
# Display accessor — canonical parent display name
# ---------------------------------------------------------------------------


class TestGuardianDisplayName:
    def test_application_guardian_name_uses_parts(self, parent_account):
        from apps.members.models import Guardian
        from apps.registrations.models import RegistrationApplication

        g = Guardian(first_name="Anna", family_name="Ozola", parent_account=parent_account)
        g.sync_full_name()
        g.save()
        app = RegistrationApplication.objects.create(
            guardian=g, parent_account=parent_account, status=RegistrationApplication.Status.DRAFT,
        )
        assert app.guardian_name == "Anna Ozola"

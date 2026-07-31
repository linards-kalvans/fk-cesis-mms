"""P13 cleanup — Guardian.display_name derived property, __str__, and migration state."""

from __future__ import annotations

import pytest

from apps.members.models import Guardian

pytestmark = pytest.mark.django_db


class TestGuardianDisplayName:
    def test_display_name_joins_first_and_family_name(self, parent_account):
        guardian = Guardian(
            parent_account=parent_account,
            first_name="Anna Marija",
            family_name="Ozola",
        )
        assert guardian.display_name == "Anna Marija Ozola"

    def test_display_name_skips_blank_family_name(self, parent_account):
        guardian = Guardian(
            parent_account=parent_account,
            first_name="Jānis",
            family_name="",
        )
        assert guardian.display_name == "Jānis"

    def test_display_name_skips_blank_first_name(self, parent_account):
        guardian = Guardian(
            parent_account=parent_account,
            first_name="",
            family_name="Ozola",
        )
        assert guardian.display_name == "Ozola"

    def test_display_name_both_empty_gives_empty(self, parent_account):
        guardian = Guardian(
            parent_account=parent_account,
            first_name="",
            family_name="",
        )
        assert guardian.display_name == ""

    def test_display_name_strips_whitespace(self, parent_account):
        guardian = Guardian(
            parent_account=parent_account,
            first_name="  Anna  ",
            family_name="  Ozola  ",
        )
        assert guardian.display_name == "Anna Ozola"


class TestGuardianStr:
    def test_str_uses_display_name(self, parent_account):
        guardian = Guardian.objects.create(
            parent_account=parent_account,
            first_name="Anna",
            family_name="Ozola",
        )
        assert str(guardian) == "Anna Ozola"

    def test_str_falls_back_to_pk_when_display_name_empty(self, parent_account):
        guardian = Guardian.objects.create(
            parent_account=parent_account,
            first_name="",
            family_name="",
        )
        assert str(guardian) == str(guardian.pk)


class TestGuardianMigrationState:
    def test_latest_guardian_model_has_no_full_name_field(self):
        field_names = {field.name for field in Guardian._meta.fields}
        assert "full_name" not in field_names

    def test_migration_0011_removes_full_name(self):
        """Migration 0011 must exist and remove Guardian.full_name."""
        from importlib import import_module

        module = import_module(
            "apps.members.migrations.0011_remove_guardian_full_name"
        )
        ops = module.Migration.operations
        remove_ops = [
            op
            for op in ops
            if hasattr(op, "name")
            and op.name == "full_name"
            and getattr(op, "model_name", "") == "guardian"
        ]
        assert len(remove_ops) == 1


class TestProductionCleanup:
    def test_no_sync_full_name_method(self):
        assert not hasattr(Guardian, "sync_full_name")

    def test_no_split_guardian_full_name_in_models(self):
        import apps.members.models as mod

        assert not hasattr(mod, "split_guardian_full_name")

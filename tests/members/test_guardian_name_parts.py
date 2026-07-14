"""P13 — Guardian first_name / family_name fields, split helper, mirror helper, and backfill migration."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Pure helper — split_guardian_full_name
# ---------------------------------------------------------------------------


class TestSplitGuardianFullName:
    """split_guardian_full_name(last-token-is-family-name rule)."""

    @pytest.mark.parametrize(
        ("full_name", "expected"),
        [
            ("", ("", "")),
            ("   ", ("", "")),
            ("Jānis", ("Jānis", "")),
            ("Jānis Kalniņš", ("Jānis", "Kalniņš")),
            ("Anna Marija Ozola", ("Anna Marija", "Ozola")),
            ("  Anna   Marija   Ozola  ", ("Anna Marija", "Ozola")),
        ],
    )
    def test_split_last_token_is_family_name(self, full_name, expected):
        from apps.members.models import split_guardian_full_name

        assert split_guardian_full_name(full_name) == expected


# ---------------------------------------------------------------------------
# Guardian.sync_full_name()
# ---------------------------------------------------------------------------


class TestGuardianSyncFullName:
    def test_sync_full_name_joins_explicit_fields(self, parent_account):
        from apps.members.models import Guardian

        guardian = Guardian(
            parent_account=parent_account,
            first_name="Anna Marija",
            family_name="Ozola",
        )
        guardian.sync_full_name()
        assert guardian.full_name == "Anna Marija Ozola"

    def test_sync_full_name_strips_blank_parts(self, parent_account):
        from apps.members.models import Guardian

        guardian = Guardian(
            parent_account=parent_account, first_name="Jānis", family_name=""
        )
        guardian.sync_full_name()
        assert guardian.full_name == "Jānis"

    def test_sync_full_name_both_empty_gives_empty(self, parent_account):
        from apps.members.models import Guardian

        guardian = Guardian(
            parent_account=parent_account, first_name="", family_name=""
        )
        guardian.sync_full_name()
        assert guardian.full_name == ""


# ---------------------------------------------------------------------------
# Migration backfill
# ---------------------------------------------------------------------------


class TestBackfillGuardianNameParts:
    """Migration 0010 backfill: existing full_name → first_name / family_name."""

    def test_backfill_splits_two_token_name(self, parent_account):
        from importlib import import_module

        from apps.members.models import Guardian

        g = Guardian.objects.create(
            parent_account=parent_account, full_name="Jānis Kalniņš"
        )

        module = import_module(
            "apps.members.migrations.0010_guardian_name_parts"
        )
        from django.apps import apps

        module.backfill_guardian_name_parts(apps, None)

        g.refresh_from_db()
        assert g.first_name == "Jānis"
        assert g.family_name == "Kalniņš"

    def test_backfill_splits_multi_token_first_name(self, parent_account):
        from importlib import import_module

        from apps.members.models import Guardian

        Guardian.objects.create(
            parent_account=parent_account, full_name="Anna Marija Ozola"
        )

        module = import_module(
            "apps.members.migrations.0010_guardian_name_parts"
        )
        from django.apps import apps

        module.backfill_guardian_name_parts(apps, None)

        g = Guardian.objects.get(parent_account=parent_account)
        assert g.first_name == "Anna Marija"
        assert g.family_name == "Ozola"

    def test_backfill_single_token_goes_to_first_name(self, parent_account):
        from importlib import import_module

        from apps.members.models import Guardian

        Guardian.objects.create(
            parent_account=parent_account, full_name="Jānis"
        )

        module = import_module(
            "apps.members.migrations.0010_guardian_name_parts"
        )
        from django.apps import apps

        module.backfill_guardian_name_parts(apps, None)

        g = Guardian.objects.get(parent_account=parent_account)
        assert g.first_name == "Jānis"
        assert g.family_name == ""

    def test_backfill_blank_full_name_gives_empty_parts(self, parent_account):
        from importlib import import_module

        from apps.members.models import Guardian

        Guardian.objects.create(
            parent_account=parent_account, full_name=""
        )

        module = import_module(
            "apps.members.migrations.0010_guardian_name_parts"
        )
        from django.apps import apps

        module.backfill_guardian_name_parts(apps, None)

        g = Guardian.objects.get(parent_account=parent_account)
        assert g.first_name == ""
        assert g.family_name == ""

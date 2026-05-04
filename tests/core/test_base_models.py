"""Tests for Task 3 — Core apps skeleton and base models.

Verifies:
  - apps.core, apps.accounts, apps.registrations, apps.members,
    apps.billing, apps.documents, apps.integrations are registered in
    Django settings.
  - apps.core.models.TimeStampedModel is an abstract model exposing
    created_at and updated_at fields.
"""

import importlib
from types import ModuleType
from typing import cast

import pytest
from django.apps import AppConfig
from django.conf import settings


# ---------------------------------------------------------------------------
# App registration
# ---------------------------------------------------------------------------

REQUIRED_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.registrations",
    "apps.members",
    "apps.billing",
    "apps.documents",
    "apps.integrations",
]


class TestAppRegistration:
    """Every required domain app must be listed in INSTALLED_APPS."""

    @pytest.mark.parametrize("app_label", REQUIRED_APPS)
    def test_app_in_installed_apps(self, app_label: str) -> None:
        """app_label appears in settings.INSTALLED_APPS."""
        assert app_label in settings.INSTALLED_APPS, (
            f"{app_label!r} not found in settings.INSTALLED_APPS"
        )

    @pytest.mark.parametrize("app_label", REQUIRED_APPS)
    def test_app_config_module_has_appconfig_subclass(
        self, app_label: str
    ) -> None:
        """The app's 'apps' module defines an AppConfig subclass whose
        ``name`` attribute matches the dotted app path."""
        try:
            apps_mod = importlib.import_module(app_label + ".apps")
        except ModuleNotFoundError as exc:
            pytest.fail(
                f"Cannot import {app_label!r}.apps module: {exc}"
            )
        assert isinstance(apps_mod, ModuleType), (
            f"{app_label!r}.apps is not a module"
        )
        for attr_name in dir(apps_mod):
            attr = getattr(apps_mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, AppConfig)
                and attr is not AppConfig
            ):
                cfg = cast(type[AppConfig], attr)
                assert cfg.name == app_label, (
                    f"AppConfig.name ({cfg.name!r}) != "
                    f"expected {app_label!r}"
                )
                return
        pytest.fail(
            f"{app_label!r}.apps has no AppConfig subclass"
        )


# ---------------------------------------------------------------------------
# TimeStampedModel
# ---------------------------------------------------------------------------


class TestTimeStampedModel:
    """apps.core.models.TimeStampedModel behaviour."""

    @pytest.fixture(autouse=True)
    def _load_module(self) -> None:
        import apps.core.models  # noqa: F401

    def test_model_class_exists(self) -> None:
        """apps.core.models.TimeStampedModel is importable."""
        from apps.core.models import TimeStampedModel

        assert TimeStampedModel is not None

    def test_is_abstract(self) -> None:
        """TimeStampedModel.Meta.abstract is True."""
        from apps.core.models import TimeStampedModel

        assert TimeStampedModel._meta.abstract is True, (
            f"TimeStampedModel._meta.abstract = {TimeStampedModel._meta.abstract}"
        )

    def test_created_at_field_exists(self) -> None:
        """TimeStampedModel exposes a created_at field."""
        from apps.core.models import TimeStampedModel

        field_names = {f.name for f in TimeStampedModel._meta.get_fields()}
        assert "created_at" in field_names, (
            f"created_at not in TimeStampedModel fields: {field_names}"
        )

    def test_updated_at_field_exists(self) -> None:
        """TimeStampedModel exposes an updated_at field."""
        from apps.core.models import TimeStampedModel

        field_names = {f.name for f in TimeStampedModel._meta.get_fields()}
        assert "updated_at" in field_names, (
            f"updated_at not in TimeStampedModel fields: {field_names}"
        )

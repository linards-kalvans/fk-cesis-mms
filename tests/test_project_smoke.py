"""Smoke tests for Task 1: project bootstrap and repo metadata.

These tests verify that the Django project package and settings module
can be imported. They are expected to FAIL until Task 1 implementation
creates the `fk_cesis_mms/` package with a `settings.py`.
"""

import importlib


def test_django_settings_module_imports():
    """fk_cesis_mms.settings is importable and defines a non-empty SECRET_KEY."""
    module = importlib.import_module("fk_cesis_mms.settings")
    assert module.SECRET_KEY is not None
    assert len(str(module.SECRET_KEY)) > 0

"""pytest-django configuration — point to the project settings module."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fk_cesis_mms.settings")


def pytest_configure(config):
    import django

    django.setup()

"""Task 4 — ensure_admin_user management command RED tests.

Env vars used:
  DJANGO_SUPERUSER_EMAIL
  DJANGO_SUPERUSER_PASSWORD
  DJANGO_SUPERUSER_USERNAME (optional, defaults to email)
"""

import os
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

User = get_user_model()

pytestmark = pytest.mark.django_db


class TestEnsureAdminUser:

    def setup_method(self):
        os.environ["DJANGO_SUPERUSER_EMAIL"] = "admin@example.com"
        os.environ["DJANGO_SUPERUSER_PASSWORD"] = "securepass123"
        os.environ.pop("DJANGO_SUPERUSER_USERNAME", None)

    def teardown_method(self):
        os.environ.pop("DJANGO_SUPERUSER_EMAIL", None)
        os.environ.pop("DJANGO_SUPERUSER_PASSWORD", None)
        os.environ.pop("DJANGO_SUPERUSER_USERNAME", None)

    def test_creates_superuser(self):
        call_command("ensure_admin_user")
        assert User.objects.filter(
            username="admin@example.com",
            is_superuser=True,
            is_staff=True,
        ).exists()

    def test_creates_user_with_correct_email(self):
        call_command("ensure_admin_user")
        user = User.objects.get(username="admin@example.com")
        assert user.email == "admin@example.com"

    def test_rerun_updates_password(self):
        call_command("ensure_admin_user")
        os.environ["DJANGO_SUPERUSER_PASSWORD"] = "newpass456"
        call_command("ensure_admin_user")
        user = User.objects.get(username="admin@example.com")
        assert user.check_password("newpass456") is True

    def test_rerun_preserves_single_admin(self):
        call_command("ensure_admin_user")
        call_command("ensure_admin_user")
        assert User.objects.filter(
            username="admin@example.com",
            is_superuser=True,
        ).count() == 1

    def test_missing_env_no_create(self):
        os.environ.pop("DJANGO_SUPERUSER_PASSWORD", None)
        call_command("ensure_admin_user")
        assert not User.objects.filter(
            username="admin@example.com"
        ).exists()

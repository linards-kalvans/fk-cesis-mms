"""pytest-django configuration — point to the project settings module."""

import os

import pytest
from django.test import Client

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fk_cesis_mms.settings")
# Run django-q2 jobs in-process during tests so OCR-after-upload tests
# (which used to exercise a synchronous code path) keep their existing
# observable behavior under the Phase 1 async refactor.
os.environ.setdefault("Q_CLUSTER_SYNC", "1")
# Tests must never hit live external providers from a developer's .env.
# settings.py loads .env with override=False, so these defaults (set before
# settings import) win over any real-provider values in .env. Tests that need a
# real-provider code path opt in explicitly via @override_settings(...).
os.environ.setdefault("INVOICE_PROVIDER_MODE", "stub")
os.environ.setdefault("AGREEMENT_PROVIDER_MODE", "stub")
os.environ.setdefault("OCR_PROVIDER_MODE", "stub")


def pytest_configure(config):
    import django

    django.setup()

    # Patch Django 6.0 test client file upload regression.
    # Client.post passes `files` via **extra but RequestFactory.post
    # (the parent class) ignores it — files never get encoded into
    # the multipart request body.  Merge files into data before the
    # parent processes the request.
    from django.test.client import RequestFactory, MULTIPART_CONTENT

    _original_rf_post = RequestFactory.post

    def _patched_rf_post(
        self,
        path,
        data=None,
        content_type=MULTIPART_CONTENT,
        secure=False,
        *,
        headers=None,
        query_params=None,
        **extra,
    ):
        files = extra.pop("files", None)
        if data is None:
            data = {}
        if files and isinstance(data, dict):
            data = dict(data)
            data.update(files)
        post_data = self._encode_data(data, content_type)
        return self.generic(
            "POST",
            path,
            post_data,
            content_type,
            secure=secure,
            headers=headers,
            query_params=query_params,
            **extra,
        )

    RequestFactory.post = _patched_rf_post


# ---------------------------------------------------------------------------
# Shared fixtures — added 2026-05-24 during test-suite consolidation.
# These replace per-test bootstrap repeated across tests/registrations/.
# ---------------------------------------------------------------------------


@pytest.fixture
def parent_account(db):
    """A fresh ParentAccount with a deterministic email."""
    from apps.accounts.models import ParentAccount

    return ParentAccount.objects.create(email="parent@example.com")


@pytest.fixture
def other_parent_account(db):
    """A second ParentAccount for cross-account isolation tests."""
    from apps.accounts.models import ParentAccount

    return ParentAccount.objects.create(email="other@example.com")


@pytest.fixture
def verified_client(parent_account):
    """A django test Client logged in via magic link as parent_account."""
    from apps.accounts.services import issue_magic_link

    client = Client()
    raw = issue_magic_link(parent_account)
    client.get(f"/accounts/verify/{raw}/")
    return client


@pytest.fixture
def other_verified_client(other_parent_account):
    """A second logged-in Client for cross-account assertions."""
    from apps.accounts.services import issue_magic_link

    client = Client()
    raw = issue_magic_link(other_parent_account)
    client.get(f"/accounts/verify/{raw}/")
    return client


@pytest.fixture
def staff_client(db):
    """A django test Client logged in as a staff superuser."""
    from django.contrib.auth.models import User

    User.objects.create_superuser(
        username="staff", email="staff@example.com", password="pw"
    )
    client = Client()
    client.login(username="staff", password="pw")
    return client


@pytest.fixture
def make_guardian(db):
    """Create a Guardian linked to a ParentAccount with a populated profile.

    Use in tests that previously set guardian_* columns on RegistrationApplication
    and assert guardian values through the read accessors.
    """
    from tests.support import make_guardian as _support_make_guardian

    def _make(account, *, full_name="", personal_id="", phone="", address=""):
        return _support_make_guardian(
            account=account,
            full_name=full_name,
            personal_id=personal_id,
            phone=phone,
            address=address,
        )

    return _make

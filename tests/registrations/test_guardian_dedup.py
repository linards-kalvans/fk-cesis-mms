"""Slice A — guardian resolved at initiation; approval reuses it; sibling discount."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import ParentAccount
from apps.documents.models import Document
from apps.members.models import Guardian
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    create_or_update_draft,
    submit_application,
)

pytestmark = pytest.mark.django_db


def test_application_has_guardian_fk():
    account = ParentAccount.objects.create(email="fk@example.com")
    guardian = Guardian.objects.create(parent_account=account)
    app = RegistrationApplication.objects.create(
        guardian_email=account.email, parent_account=account, guardian=guardian
    )
    assert app.guardian == guardian
    assert list(guardian.applications.all()) == [app]

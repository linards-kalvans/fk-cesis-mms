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


def test_two_initiations_same_account_share_one_guardian():
    account = ParentAccount.objects.create(email="siblings@example.com")

    app1 = create_or_update_draft(
        data={"guardian_email": account.email},
        files={},
        verified_account=account,
    )
    app2 = create_or_update_draft(
        data={"guardian_email": account.email},
        files={},
        verified_account=account,
    )

    assert app1.guardian_id is not None
    assert app1.guardian_id == app2.guardian_id
    assert Guardian.objects.filter(parent_account=account).count() == 1

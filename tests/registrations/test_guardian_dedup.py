"""Slice A — guardian resolved at initiation; approval reuses it; sibling discount."""

from __future__ import annotations


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
        parent_account=account, guardian=guardian
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


_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _build_submitted_application(account, child_name, child_pid, kit_shirt, kit_shorts, *, opt_out=False):
    """Create a fully-populated submitted application for `account`."""
    app = create_or_update_draft(
        data={
            "guardian_first_name": "Sibling",
            "guardian_family_name": "Guardian",
            "guardian_personal_id": "010101-12345",
            "guardian_email": account.email,
            "guardian_phone": "+37120000000",
            "guardian_declared_address": "Riga, Brivibas 1",
            "member_full_name": child_name,
            "member_personal_id": child_pid,
            "member_birth_date": "2025-01-01",
            "member_same_address_as_guardian": True,
            "member_kit_size_shirt": kit_shirt,
            "member_kit_size_shorts": kit_shorts,
            "preferred_agreement_signing": "paper",
            "support_club_instead_of_multi_child_discount": opt_out,
        },
        files={},
        verified_account=account,
    )
    for kind in (
        Document.Kind.GUARDIAN_IDENTITY,
        Document.Kind.MEMBER_IDENTITY,
        Document.Kind.MEMBER_PORTRAIT,
    ):
        Document.objects.create(
            application=app,
            kind=kind,
            file=SimpleUploadedFile(f"{kind}.png", _PNG, content_type="image/png"),
            original_filename=f"{kind}.png",
            content_type="image/png",
            file_size=len(_PNG),
        )
    return submit_application(app, account)


@pytest.fixture
def kit_pks(db):
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT, label="S", defaults={"is_active": True}
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS, label="S", defaults={"is_active": True}
    )
    return shirt.pk, shorts.pk


@pytest.fixture
def staff_reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="rev", is_staff=True)


def test_approval_reuses_guardian_no_duplicates(kit_pks, staff_reviewer):
    shirt, shorts = kit_pks
    account = ParentAccount.objects.create(email="reuse@example.com")

    app1 = _build_submitted_application(account, "Child One", "010120-11111", shirt, shorts)
    app2 = _build_submitted_application(account, "Child Two", "010122-22222", shirt, shorts)

    approve_application(app1, staff_reviewer)
    approve_application(app2, staff_reviewer)
    app1.refresh_from_db()
    app2.refresh_from_db()

    # Exactly one Guardian for the account; both Members hang off it.
    assert Guardian.objects.filter(parent_account=account).count() == 1
    guardian = Guardian.objects.get(parent_account=account)
    assert app1.approved_member.guardian_id == guardian.id
    assert app2.approved_member.guardian_id == guardian.id
    assert guardian.members.count() == 2
    # Profile populated from the application snapshot.
    assert guardian.display_name == "Sibling Guardian"

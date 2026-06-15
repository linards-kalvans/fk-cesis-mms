"""consolidate_guardians links orphans, creates missing accounts, merges dups."""

import pytest

from apps.accounts.models import ParentAccount
from apps.members.models import Guardian, Member
from apps.members.services import consolidate_guardians
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def test_merge_repoints_applications_before_deleting_loser():
    # RegistrationApplication.guardian is on_delete=PROTECT — the loser's
    # applications must be repointed to the survivor before deletion, else
    # consolidate would raise ProtectedError.
    acc = ParentAccount.objects.create(email="ap@example.com")
    keep = Guardian.objects.create(full_name="K", email="ap@example.com", external_client_id="IN-1")
    drop = Guardian.objects.create(full_name="K dup", email="ap@example.com")
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns", guardian=drop
    )
    consolidate_guardians()
    app.refresh_from_db()
    assert app.guardian_id == keep.pk
    assert not Guardian.objects.filter(pk=drop.pk).exists()


def test_orphan_guardian_linked_to_existing_account_by_email():
    acc = ParentAccount.objects.create(email="p@example.com", phone="+371")
    g = Guardian.objects.create(full_name="P", email="p@example.com")  # orphan
    consolidate_guardians()
    g.refresh_from_db()
    assert g.parent_account_id == acc.pk


def test_orphan_with_no_account_gets_one_created():
    g = Guardian.objects.create(full_name="Q", email="q@example.com", phone="+37122")
    consolidate_guardians()
    g.refresh_from_db()
    assert g.parent_account is not None
    assert g.parent_account.email == "q@example.com"
    assert g.parent_account.phone == "+37122"


def test_account_phone_backfilled_from_guardian_when_empty():
    acc = ParentAccount.objects.create(email="r@example.com", phone="")
    Guardian.objects.create(full_name="R", email="r@example.com", phone="+37133")
    consolidate_guardians()
    acc.refresh_from_db()
    assert acc.phone == "+37133"


def test_duplicate_guardians_merge_to_survivor_with_external_client_id():
    acc = ParentAccount.objects.create(email="s@example.com")
    keep = Guardian.objects.create(full_name="S", email="s@example.com", external_client_id="IN-9")
    drop = Guardian.objects.create(full_name="S dup", email="s@example.com")
    m = Member.objects.create(full_name="Child", guardian=drop)
    consolidate_guardians()
    m.refresh_from_db()
    assert m.guardian_id == keep.pk
    assert not Guardian.objects.filter(pk=drop.pk).exists()
    assert Guardian.objects.get(pk=keep.pk).external_client_id == "IN-9"


def test_idempotent_on_clean_data():
    acc = ParentAccount.objects.create(email="t@example.com")
    Guardian.objects.create(full_name="T", parent_account=acc, email="t@example.com")
    consolidate_guardians()
    consolidate_guardians()
    assert Guardian.objects.count() == 1

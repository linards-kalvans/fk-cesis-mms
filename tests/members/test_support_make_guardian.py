"""The make_guardian helper links a guardian to a parent account."""

import pytest

from apps.accounts.models import ParentAccount
from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def test_make_guardian_creates_linked_account():
    g = make_guardian(full_name="Anna", email="anna@example.com", phone="+371200")
    assert g.parent_account is not None
    assert g.parent_account.email == "anna@example.com"
    assert g.parent_account.phone == "+371200"
    assert g.full_name == "Anna"


def test_make_guardian_generates_unique_emails():
    a = make_guardian(full_name="A")
    b = make_guardian(full_name="B")
    assert a.parent_account_id != b.parent_account_id
    assert ParentAccount.objects.count() == 2


def test_make_guardian_uses_provided_account():
    # parent_account is OneToOne (1:1), so account= attaches a single guardian
    # to a pre-existing account.
    acc = ParentAccount.objects.create(email="shared@example.com")
    g = make_guardian(full_name="A", account=acc)
    assert g.parent_account_id == acc.pk

"""Slice C — ParentAccount admin email-change routing."""

import pytest
from django.contrib.admin.sites import AdminSite

from apps.accounts.admin import ParentAccountAdmin
from apps.accounts.models import ParentAccount
from apps.members.services import resolve_guardian_for_account

pytestmark = pytest.mark.django_db


class _StubForm:
    """Minimal stand-in for the admin ModelForm in save_model."""

    def __init__(self, changed_data, initial):
        self.changed_data = changed_data
        self.initial = initial


def test_registered_in_admin():
    from django.contrib import admin

    assert ParentAccount in admin.site._registry


def test_save_model_routes_email_change_through_service():
    account = ParentAccount.objects.create(email="old@example.com")
    guardian = resolve_guardian_for_account(account)
    assert guardian.email == "old@example.com"

    admin_obj = ParentAccountAdmin(ParentAccount, AdminSite())
    account.email = "new@example.com"  # mimic the admin form mutating the instance
    form = _StubForm(changed_data=["email"], initial={"email": "old@example.com"})
    admin_obj.save_model(request=None, obj=account, form=form, change=True)

    account.refresh_from_db()
    guardian.refresh_from_db()
    assert account.email == "new@example.com"
    assert guardian.email == "new@example.com"


def test_save_model_plain_save_when_email_unchanged():
    account = ParentAccount.objects.create(email="stable@example.com", phone="111")
    admin_obj = ParentAccountAdmin(ParentAccount, AdminSite())
    account.phone = "222"
    form = _StubForm(changed_data=["phone"], initial={"phone": "111"})
    admin_obj.save_model(request=None, obj=account, form=form, change=True)

    account.refresh_from_db()
    assert account.email == "stable@example.com"
    assert account.phone == "222"

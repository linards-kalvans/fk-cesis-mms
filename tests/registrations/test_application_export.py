"""Registration applications CSV export — column sets, gating, audit."""

import csv
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.accounts.models import ParentAccount
from apps.core.models import AuditEvent
from apps.members.services import resolve_guardian_for_account
from apps.registrations.admin import RegistrationApplicationAdmin
from apps.registrations.exports import application_columns, application_row
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _application():
    acct = ParentAccount.objects.create(email="parent@example.com", phone="+37129999999")
    g = resolve_guardian_for_account(acct)
    g.full_name = "Anna Ozola"
    g.personal_id = "010180-12345"
    g.phone = "+37129999999"
    g.address = "Rīga"
    g.save()
    return RegistrationApplication.objects.create(
        parent_account=acct, guardian=g, claimed_email=acct.email,
        member_full_name="Jānis Ozols", member_personal_id="010110-22222",
        member_actual_address="Cēsis", status=RegistrationApplication.Status.SUBMITTED,
    )


def _request(user):
    req = RequestFactory().post("/admin/")
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def test_safe_row_excludes_sensitive():
    a = _application()
    assert len(application_row(a, sensitive=False)) == len(application_columns(sensitive=False))
    flat = " ".join(str(c) for c in application_row(a, sensitive=False))
    assert "010110-22222" not in flat
    assert "parent@example.com" not in flat
    assert "Cēsis" not in flat


def test_sensitive_row_includes_sensitive():
    a = _application()
    assert len(application_row(a, sensitive=True)) == len(application_columns(sensitive=True))
    flat = " ".join(str(c) for c in application_row(a, sensitive=True))
    assert "010110-22222" in flat
    assert "parent@example.com" in flat
    assert "Cēsis" in flat


def test_safe_export_audits_non_sensitive():
    _application()
    admin_obj = RegistrationApplicationAdmin(RegistrationApplication, AdminSite())
    staff = User.objects.create_user(username="staff", email="s@example.com", is_staff=True)
    resp = admin_obj.export_csv(_request(staff), RegistrationApplication.objects.all())
    body = resp.content.decode("utf-8")[1:]
    header = next(csv.reader(io.StringIO(body), delimiter=";"))
    assert header == application_columns(sensitive=False)
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.metadata["sensitive"] is False
    assert e.metadata["count"] == 1


def test_sensitive_hidden_and_refused_for_non_superuser():
    _application()
    admin_obj = RegistrationApplicationAdmin(RegistrationApplication, AdminSite())
    staff = User.objects.create_user(username="staff2", email="s2@example.com", is_staff=True)
    assert "export_csv_with_sensitive" not in admin_obj.get_actions(_request(staff))
    assert admin_obj.export_csv_with_sensitive(_request(staff), RegistrationApplication.objects.all()) is None
    assert not AuditEvent.objects.filter(action=str(AuditEvent.Action.DATA_EXPORTED)).exists()


def test_sensitive_export_for_superuser_includes_sensitive_and_audits():
    _application()
    admin_obj = RegistrationApplicationAdmin(RegistrationApplication, AdminSite())
    su = User.objects.create_superuser(username="su", email="su@example.com", password="pw")
    resp = admin_obj.export_csv_with_sensitive(_request(su), RegistrationApplication.objects.all())
    assert "010110-22222" in resp.content.decode("utf-8")
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.metadata["sensitive"] is True
    assert e.metadata["count"] == 1

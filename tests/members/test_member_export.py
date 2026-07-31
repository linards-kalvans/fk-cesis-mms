"""Members CSV export — column sets, gating, audit.

After P13 cleanup: export uses guardian.display_name (not full_name).
"""

import csv
import io

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from apps.core.models import AuditEvent
from apps.members.admin import MemberAdmin
from apps.members.exports import member_columns, member_row
from apps.members.models import Member, TrainingGroup

from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def _member():
    g = make_guardian(
        full_name="Anna Ozola",
        email="a@example.com",
        phone="+37120000000",
        address="Rīga",
        personal_id="010180-12345",
    )
    grp = TrainingGroup.objects.create(name="U-12", is_active=True)
    return Member.objects.create(
        full_name="Jānis Ozols",
        personal_id="010110-22222",
        guardian=g,
        training_group=grp,
    )


def _request(user):
    req = RequestFactory().post("/admin/")
    req.user = user
    req.session = {}
    req._messages = FallbackStorage(req)
    return req


def test_member_row_safe_excludes_personal_id():
    m = _member()
    cols = member_columns(sensitive=False)
    row = member_row(m, sensitive=False)
    assert len(row) == len(cols)
    flat = " ".join(str(c) for c in row)
    assert "010110-22222" not in flat
    assert "a@example.com" not in flat


def test_member_row_guardian_name_uses_display_name():
    m = _member()
    row = member_row(m, sensitive=False)
    # Guardian column (index 3) should be "Anna Ozola" via display_name.
    assert row[3] == "Anna Ozola"


def test_member_row_sensitive_includes_personal_id_and_contact():
    m = _member()
    row = member_row(m, sensitive=True)
    assert len(row) == len(member_columns(sensitive=True))
    flat = " ".join(str(c) for c in row)
    assert "010110-22222" in flat
    assert "a@example.com" in flat


def test_safe_export_action_returns_csv_and_audits():
    _member()
    admin_obj = MemberAdmin(Member, AdminSite())
    staff = User.objects.create_user(
        username="staff", email="s@example.com", is_staff=True
    )
    resp = admin_obj.export_csv(_request(staff), Member.objects.all())
    body = resp.content.decode("utf-8")[1:]  # strip BOM
    header = next(csv.reader(io.StringIO(body), delimiter=";"))
    assert header == member_columns(sensitive=False)
    assert "010110-22222" not in resp.content.decode("utf-8")
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.actor == staff
    assert e.metadata["sensitive"] is False
    assert e.metadata["count"] == 1


def test_sensitive_action_hidden_from_non_superuser():
    admin_obj = MemberAdmin(Member, AdminSite())
    staff = User.objects.create_user(
        username="staff2", email="s2@example.com", is_staff=True
    )
    assert "export_csv_with_sensitive" not in admin_obj.get_actions(_request(staff))
    su = User.objects.create_superuser(
        username="su0", email="su0@example.com", password="pw"
    )
    assert "export_csv_with_sensitive" in admin_obj.get_actions(_request(su))


def test_sensitive_action_refuses_non_superuser_and_no_audit():
    _member()
    admin_obj = MemberAdmin(Member, AdminSite())
    staff = User.objects.create_user(
        username="staff3", email="s3@example.com", is_staff=True
    )
    result = admin_obj.export_csv_with_sensitive(_request(staff), Member.objects.all())
    assert result is None
    assert not AuditEvent.objects.filter(
        action=str(AuditEvent.Action.DATA_EXPORTED)
    ).exists()


def test_sensitive_action_for_superuser_exports_and_audits():
    _member()
    admin_obj = MemberAdmin(Member, AdminSite())
    su = User.objects.create_superuser(
        username="su", email="su@example.com", password="pw"
    )
    resp = admin_obj.export_csv_with_sensitive(_request(su), Member.objects.all())
    assert "010110-22222" in resp.content.decode("utf-8")
    e = AuditEvent.objects.get(action=str(AuditEvent.Action.DATA_EXPORTED))
    assert e.metadata["sensitive"] is True
    assert e.metadata["count"] == 1
    assert e.metadata["format"] == "csv"

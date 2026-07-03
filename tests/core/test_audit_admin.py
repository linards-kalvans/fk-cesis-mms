"""AuditEventAdmin is read-only and registered."""

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite

from apps.core.admin import AuditEventAdmin
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_registered():
    assert AuditEvent in admin.site._registry


def test_read_only_permissions():
    a = AuditEventAdmin(AuditEvent, AdminSite())
    assert a.has_add_permission(request=None) is False
    assert a.has_change_permission(request=None) is False
    assert a.has_delete_permission(request=None) is False

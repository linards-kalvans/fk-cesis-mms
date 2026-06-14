"""The Registrations app is listed first in the admin (custom AdminSite)."""

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory

pytestmark = pytest.mark.django_db


def test_registrations_app_listed_first():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff", "s@example.com", "pw")
    app_list = admin.site.get_app_list(req)
    assert app_list, "admin app list is empty"
    assert app_list[0]["app_label"] == "registrations"


def test_all_apps_still_present():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff2", "s2@example.com", "pw")
    labels = {app["app_label"] for app in admin.site.get_app_list(req)}
    # core (AuditEvent), billing, members, agreements all still registered.
    assert {"registrations", "billing", "members", "agreements", "core"} <= labels

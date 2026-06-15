"""The Registrations app is listed first in the admin (custom AdminSite)."""

import pytest
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory

from apps.core.admin_site import FkAdminSite

pytestmark = pytest.mark.django_db


def test_registrations_app_listed_first():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff", "s@example.com", "pw")
    # Fails clearly if the INSTALLED_APPS swap regresses (plain AdminSite).
    assert isinstance(admin.site, FkAdminSite), type(admin.site)
    app_list = admin.site.get_app_list(req)
    assert app_list, "admin app list is empty"
    assert app_list[0]["app_label"] == "registrations"


def test_all_apps_still_present():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff2", "s2@example.com", "pw")
    labels = {app["app_label"] for app in admin.site.get_app_list(req)}
    # core (AuditEvent), billing, members, agreements all still registered.
    assert {"registrations", "billing", "members", "agreements", "core"} <= labels


def test_parent_account_hidden_from_menu_but_registered():
    from django.urls import reverse
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff_pa", "spa@example.com", "pw")
    labels_models = {
        (app["app_label"], m["object_name"])
        for app in admin.site.get_app_list(req)
        for m in app["models"]
    }
    assert ("accounts", "ParentAccount") not in labels_models  # absent from menu
    # still registered → change/changelist URLs resolve
    assert reverse("admin:accounts_parentaccount_changelist")


def test_menu_follows_the_fixed_order():
    req = RequestFactory().get("/admin/")
    req.user = User.objects.create_superuser("staff_ord", "sord@example.com", "pw")
    labels = [app["app_label"] for app in admin.site.get_app_list(req)]
    expected = [
        "registrations", "agreements", "billing", "members",
        "auth", "documents", "core", "django_q",
    ]
    # Every expected app present, in exactly this relative order (filtered to
    # whatever is registered, so the assertion is robust to optional apps).
    present_expected = [label for label in expected if label in labels]
    assert [label for label in labels if label in expected] == present_expected
    assert labels[0] == "registrations"

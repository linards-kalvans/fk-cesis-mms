"""Task 8 — Admin visibility: read-only AddressImportRun registration."""

from __future__ import annotations

import pytest
from django.contrib import admin
from django.urls import reverse


@pytest.mark.django_db
def test_address_import_run_registered_in_admin():
    from apps.addresses.models import AddressImportRun

    assert AddressImportRun in admin.site._registry


@pytest.mark.django_db
def test_address_import_run_admin_is_read_only(staff_client):
    from apps.addresses.models import AddressImportRun

    run = AddressImportRun.objects.create(source="vzd_varis", status=AddressImportRun.Status.FAILED)

    response = staff_client.get(reverse("admin:addresses_addressimportrun_change", args=[run.id]))

    assert response.status_code == 200
    assert b"Save" not in response.content

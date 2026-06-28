"""Task 1 — model basics: app registration and __str__ output."""

from __future__ import annotations

import pytest
from django.apps import apps


@pytest.mark.django_db
def test_addresses_app_is_installed():
    assert apps.get_app_config("addresses").name == "apps.addresses"


@pytest.mark.django_db
def test_import_run_str_includes_source_and_status():
    from apps.addresses.models import AddressImportRun

    run = AddressImportRun.objects.create(
        source="vzd_varis", status=AddressImportRun.Status.SUCCEEDED
    )
    assert str(run) == "vzd_varis: succeeded"


@pytest.mark.django_db
def test_address_group_str_returns_label():
    from apps.addresses.models import AddressGroup

    group = AddressGroup.objects.create(
        label="Raiņa iela, Cēsis",
        normalized_label="raina iela cesis",
        street_code="100",
        street_name="Raiņa iela",
        locality_code="200",
        locality_name="Cēsis",
        region_code="300",
        region_name="Cēsu nov.",
    )
    assert str(group) == "Raiņa iela, Cēsis"


@pytest.mark.django_db
def test_address_entry_str_returns_label():
    from apps.addresses.models import AddressEntry

    entry = AddressEntry.objects.create(
        vzd_code="400",
        label="Raiņa iela 1, Cēsis, Cēsu nov.",
        normalized_label="raina iela 1 cesis cesu nov",
        postal_code="LV-4101",
        region_code="300",
        region_name="Cēsu nov.",
    )
    assert str(entry) == "Raiņa iela 1, Cēsis, Cēsu nov."

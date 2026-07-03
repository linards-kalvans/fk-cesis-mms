"""Task 5+6 — URL download, drop guard, scheduled task, schedule migration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import override_settings


def _write_response(url: str, target: Path) -> None:
    target.write_text("KODS,STATUSS,NOSAUKUMS,VKUR_CD\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


def test_address_import_url_defaults_exist(settings):
    assert settings.ADDRESS_IMPORT_AW_NOVADS_URL.endswith("/aw_novads.csv")
    assert settings.ADDRESS_IMPORT_AW_PAGASTS_URL.endswith("/aw_pagasts.csv")
    assert settings.ADDRESS_IMPORT_AW_PILSETA_URL.endswith("/aw_pilseta.csv")
    assert settings.ADDRESS_IMPORT_AW_CIEMS_URL.endswith("/aw_ciems.csv")
    assert settings.ADDRESS_IMPORT_AW_IELA_URL.endswith("/aw_iela.csv")
    assert settings.ADDRESS_IMPORT_AW_EKA_URL.endswith("/aw_eka.csv")
    assert settings.ADDRESS_IMPORT_AW_DZIV_URL.endswith("/aw_dziv.csv")
    assert settings.ADDRESS_IMPORT_WEEKDAY == 6
    assert settings.ADDRESS_IMPORT_HOUR == 1
    assert settings.ADDRESS_IMPORT_MAX_DROP_RATIO == 0.50


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------


@override_settings(
    ADDRESS_IMPORT_AW_NOVADS_URL="https://example.test/novads.csv",
    ADDRESS_IMPORT_AW_PAGASTS_URL="https://example.test/pagasts.csv",
    ADDRESS_IMPORT_AW_PILSETA_URL="https://example.test/pilseta.csv",
    ADDRESS_IMPORT_AW_CIEMS_URL="https://example.test/ciems.csv",
    ADDRESS_IMPORT_AW_IELA_URL="https://example.test/iela.csv",
    ADDRESS_IMPORT_AW_EKA_URL="https://example.test/eka.csv",
    ADDRESS_IMPORT_AW_DZIV_URL="https://example.test/dziv.csv",
)
def test_download_vzd_address_files_writes_all_files(tmp_path):
    from apps.addresses.services import download_vzd_address_files

    with patch("apps.addresses.services._download_file", side_effect=_write_response) as mocked:
        files = download_vzd_address_files(tmp_path)

    assert mocked.call_count == 7
    assert files.novads.exists()
    assert files.pagasts.exists()
    assert files.pilseta.exists()
    assert files.ciems.exists()
    assert files.iela.exists()
    assert files.eka.exists()
    assert files.dziv and files.dziv.exists()


# ---------------------------------------------------------------------------
# Drop guard
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(ADDRESS_IMPORT_MAX_DROP_RATIO=0.50)
def test_suspicious_drop_blocks_replacement(vzd_files, tmp_path):
    from apps.addresses.models import AddressEntry, AddressImportRun
    from apps.addresses.services import VzdAddressFiles, import_vzd_addresses

    # write_csv imported from test_import_addresses.py
    from tests.addresses.test_import_addresses import write_csv

    first = import_vzd_addresses(vzd_files, region_codes=["300"])
    assert first.status == AddressImportRun.Status.SUCCEEDED
    assert first.entry_count == 3

    empty_eka = write_csv(
        tmp_path / "EMPTY_EKA.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
        [],
    )
    second_files = VzdAddressFiles(
        novads=vzd_files.novads,
        pagasts=vzd_files.pagasts,
        pilseta=vzd_files.pilseta,
        ciems=vzd_files.ciems,
        iela=vzd_files.iela,
        eka=empty_eka,
        dziv=vzd_files.dziv,
    )

    second = import_vzd_addresses(second_files, region_codes=["300"])

    assert second.status == AddressImportRun.Status.FAILED
    assert "suspicious" in second.error_message.lower()
    assert AddressEntry.objects.count() == 2


@pytest.mark.django_db
@override_settings(ADDRESS_IMPORT_MAX_DROP_RATIO=0.50)
def test_drop_guard_skips_when_no_previous_success(vzd_files):
    from apps.addresses.models import AddressImportRun
    from apps.addresses.services import import_vzd_addresses

    run = import_vzd_addresses(vzd_files, region_codes=["999"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.entry_count == 0


# ---------------------------------------------------------------------------
# Scheduled task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=[])
def test_scheduled_import_skips_without_region_codes(caplog):
    from apps.addresses.models import AddressImportRun
    from apps.addresses.tasks import import_vzd_addresses_from_urls

    import_vzd_addresses_from_urls()

    assert AddressImportRun.objects.count() == 0


@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=["300"])
def test_scheduled_import_calls_url_import(vzd_files):
    from apps.addresses.tasks import import_vzd_addresses_from_urls

    with patch("apps.addresses.tasks.import_vzd_addresses_from_urls_service") as mocked:
        import_vzd_addresses_from_urls()

    mocked.assert_called_once_with(region_codes=["300"])


@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=["300"])
def test_scheduled_import_records_failed_run_on_download_error():
    """Task/service wrapper must not crash qcluster; failed run recorded."""
    from apps.addresses.models import AddressImportRun
    from apps.addresses.tasks import import_vzd_addresses_from_urls

    with patch(
        "apps.addresses.services.download_vzd_address_files",
        side_effect=RuntimeError("download failed"),
    ):
        import_vzd_addresses_from_urls()

    failed_run = AddressImportRun.objects.filter(
        status=AddressImportRun.Status.FAILED,
        source="vzd_varis",
    ).first()
    assert failed_run is not None
    assert failed_run.region_codes == "300"
    assert "download failed" in failed_run.error_message


# ---------------------------------------------------------------------------
# Download failure preserves previous index
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=["300"])
def test_download_failure_preserves_previous_index(vzd_files):
    """Failed download/import leaves AddressEntry + AddressApartment rows intact."""
    from apps.addresses.models import AddressApartment, AddressEntry, AddressImportRun
    from apps.addresses.services import import_vzd_addresses
    from django.core.management import CommandError, call_command

    # First import succeeds for region 300.
    run1 = import_vzd_addresses(vzd_files, region_codes=["300"])
    assert run1.status == AddressImportRun.Status.SUCCEEDED
    entry_pks = set(AddressEntry.objects.values_list("pk", flat=True))
    apartment_pks = set(AddressApartment.objects.values_list("pk", flat=True))
    assert len(entry_pks) == 2
    assert len(apartment_pks) == 1

    # Simulate download failure on a no-arg import.
    with patch(
        "apps.addresses.management.commands.import_addresses.download_vzd_address_files",
        side_effect=RuntimeError("download failed"),
    ):
        with pytest.raises(CommandError, match="Address import failed"):
            call_command("import_addresses")

    # Previous rows preserved — nothing deleted.
    assert set(AddressEntry.objects.values_list("pk", flat=True)) == entry_pks
    assert set(AddressApartment.objects.values_list("pk", flat=True)) == apartment_pks

    # A failed AddressImportRun recorded the error.
    failed_run = AddressImportRun.objects.filter(
        status=AddressImportRun.Status.FAILED,
    ).order_by("-started_at").first()
    assert failed_run is not None
    assert "download failed" in failed_run.error_message


# ---------------------------------------------------------------------------
# Schedule migration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_weekly_address_import_schedule_exists():
    from django_q.models import Schedule

    schedule = Schedule.objects.get(name="address-vzd-weekly-import")
    assert schedule.func == "apps.addresses.tasks.import_vzd_addresses_from_urls"
    assert schedule.schedule_type == Schedule.WEEKLY

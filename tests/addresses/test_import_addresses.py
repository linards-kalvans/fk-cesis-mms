"""Task 2 — CSV parser, import service, and management command behavior.

Most fixtures use ASCII-safe ISO-8859-1 bytes; one fixture uses UTF-8 BOM,
matching the current downloaded VZD files. These tests verify parsing,
filtering, grouping, normalization, and the management-command contract.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings


def write_csv(path: Path, header: str, rows: list[str]) -> Path:
    """Write a minimal VZD-like CSV encoded as ISO-8859-1 (ASCII-safe rows)."""
    path.write_bytes((header + "\n" + "\n".join(rows) + "\n").encode("ISO-8859-1"))
    return path


def write_utf8_csv(path: Path, header: str, rows: list[str]) -> Path:
    """Write a VZD-like CSV encoded like the current downloaded files."""
    path.write_bytes(("\ufeff" + header + "\n" + "\n".join(rows) + "\n").encode())
    return path


@pytest.fixture
def vzd_files(tmp_path):
    """Minimal Cesis-area fixture: one novads (300), one pilseta (200 under 300),
    one street (100 under 200), two active building rows + one DEL row.

    All strings are ASCII-safe so the ISO-8859-1 encoder never fails.
    """
    from apps.addresses.services import VzdAddressFiles

    novads = write_csv(
        tmp_path / "AW_NOVADS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["300,EKS,Cesu nov.,"],
    )
    pagasts = write_csv(
        tmp_path / "AW_PAGASTS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        [],
    )
    pilseta = write_csv(
        tmp_path / "AW_PILSETA.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["200,EKS,Cesis,300"],
    )
    ciems = write_csv(
        tmp_path / "AW_CIEMS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        [],
    )
    iela = write_csv(
        tmp_path / "AW_IELA.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["100,EKS,Raina iela,200"],
    )
    eka = write_csv(
        tmp_path / "AW_EKA.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
        [
            '401,EKS,100,1,"Raina iela 1, Cesis, Cesu nov.",LV-4101,,,,',
            '402,EKS,100,2,"Raina iela 2, Cesis, Cesu nov.",LV-4101,,,,',
            '403,DEL,100,3,"Raina iela 3, Cesis, Cesu nov.",LV-4101,,,,',
        ],
    )
    return VzdAddressFiles(
        novads=novads, pagasts=pagasts, pilseta=pilseta, ciems=ciems, iela=iela, eka=eka,
    )


# ---------------------------------------------------------------------------
# Service-level import
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_vzd_addresses_creates_group_and_active_entries(vzd_files):
    from apps.addresses.models import AddressEntry, AddressGroup, AddressImportRun
    from apps.addresses.services import import_vzd_addresses

    run = import_vzd_addresses(vzd_files, region_codes=["300"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.group_count == 1
    assert run.entry_count == 2
    assert AddressGroup.objects.get().label == "Raina iela, Cesis"
    assert (
        list(AddressEntry.objects.order_by("vzd_code").values_list("vzd_code", flat=True))
        == ["401", "402"]
    )


@pytest.mark.django_db
def test_import_vzd_addresses_excludes_regions_not_configured(vzd_files):
    from apps.addresses.models import AddressEntry, AddressImportRun
    from apps.addresses.services import import_vzd_addresses

    run = import_vzd_addresses(vzd_files, region_codes=["999"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.group_count == 0
    assert run.entry_count == 0
    assert AddressEntry.objects.count() == 0


@pytest.mark.django_db
def test_import_vzd_addresses_supports_top_level_city_region_codes(tmp_path):
    from apps.addresses.models import AddressEntry, AddressGroup
    from apps.addresses.services import VzdAddressFiles, import_vzd_addresses

    files = VzdAddressFiles(
        novads=write_utf8_csv(tmp_path / "AW_NOVADS.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", []),
        pagasts=write_utf8_csv(tmp_path / "AW_PAGASTS.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", []),
        pilseta=write_utf8_csv(
            tmp_path / "AW_PILSETA.CSV",
            "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
            ["900,EKS,Rīga,100000000"],
        ),
        ciems=write_utf8_csv(tmp_path / "AW_CIEMS.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", []),
        iela=write_utf8_csv(
            tmp_path / "AW_IELA.CSV",
            "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
            ["100,EKS,Raiņa bulvāris,900"],
        ),
        eka=write_utf8_csv(
            tmp_path / "AW_EKA.CSV",
            "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
            ['401,EKS,100,1,"Raiņa bulvāris 1, Rīga",LV-1050,,,,'],
        ),
    )

    run = import_vzd_addresses(files, region_codes=["900"])

    assert run.entry_count == 1
    group = AddressGroup.objects.get()
    assert group.label == "Raiņa bulvāris, Rīga"
    assert group.region_code == "900"
    assert group.region_name == "Rīga"
    assert AddressEntry.objects.get().label == "Raiņa bulvāris 1, Rīga"


def test_normalize_address_query_collapses_case_spaces_and_diacritics():
    from apps.addresses.services import normalize_address_query

    # Pure Python string — no encoding concern. Latvian diacritics are legal
    # in a str and the normalizer must collapse them to ASCII.
    assert normalize_address_query("  Raina   IELA  ") == "raina iela"

    # Diacritic-heavy variant — separate assertion to keep the Latin-1
    # encoding concern isolated from the normalizer contract.
    assert normalize_address_query("Raiņa") == "raina"


# ---------------------------------------------------------------------------
# Management command contract
#
# The plan requires:
#   uv run python manage.py import_addresses \
#     --novads AW_NOVADS.CSV \
#     --pagasts AW_PAGASTS.CSV \
#     --pilseta AW_PILSETA.CSV \
#     --ciems AW_CIEMS.CSV \
#     --iela AW_IELA.CSV \
#     --eka AW_EKA.CSV \
#     --region-code 300
#
# call_command passes kwargs that argparse maps to the corresponding flags.
# Output must include "Imported N address groups and M address entries."
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_import_command_creates_group_and_entries_from_local_csv(vzd_files):
    from apps.addresses.models import AddressEntry, AddressGroup

    out = io.StringIO()
    call_command(
        "import_addresses",
        novads=str(vzd_files.novads),
        pagasts=str(vzd_files.pagasts),
        pilseta=str(vzd_files.pilseta),
        ciems=str(vzd_files.ciems),
        iela=str(vzd_files.iela),
        eka=str(vzd_files.eka),
        region_code=["300"],
        stdout=out,
    )

    output = out.getvalue()
    # Must report the expected counts.
    assert "Imported 1 address groups and 2 address entries." in output, (
        f"unexpected command output: {output}"
    )
    # Must produce the right number of rows.
    assert AddressGroup.objects.count() == 1
    assert AddressEntry.objects.count() == 2


@pytest.mark.django_db
def test_import_command_excludes_other_regions(vzd_files):
    from apps.addresses.models import AddressEntry

    out = io.StringIO()
    call_command(
        "import_addresses",
        novads=str(vzd_files.novads),
        pagasts=str(vzd_files.pagasts),
        pilseta=str(vzd_files.pilseta),
        ciems=str(vzd_files.ciems),
        iela=str(vzd_files.iela),
        eka=str(vzd_files.eka),
        region_code=["999"],
        stdout=out,
    )

    output = out.getvalue()
    assert "Imported 0 address groups and 0 address entries." in output, (
        f"unexpected command output: {output}"
    )
    assert AddressEntry.objects.count() == 0


@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=["300"])
def test_import_command_uses_setting_region_codes_when_flag_omitted(vzd_files):
    from apps.addresses.models import AddressEntry, AddressGroup

    out = io.StringIO()
    call_command(
        "import_addresses",
        novads=str(vzd_files.novads),
        pagasts=str(vzd_files.pagasts),
        pilseta=str(vzd_files.pilseta),
        ciems=str(vzd_files.ciems),
        iela=str(vzd_files.iela),
        eka=str(vzd_files.eka),
        stdout=out,
    )

    output = out.getvalue()
    assert "Imported 1 address groups and 2 address entries." in output, (
        f"unexpected command output: {output}"
    )
    assert AddressGroup.objects.count() == 1
    assert AddressEntry.objects.count() == 2


@pytest.mark.django_db
def test_import_command_raises_on_failed_import(vzd_files):
    with pytest.raises(CommandError, match="Address import failed"):
        call_command(
            "import_addresses",
            novads="/nonexistent/AW_NOVADS.CSV",
            pagasts=str(vzd_files.pagasts),
            pilseta=str(vzd_files.pilseta),
            ciems=str(vzd_files.ciems),
            iela=str(vzd_files.iela),
            eka=str(vzd_files.eka),
            region_code=["300"],
        )


# ---------------------------------------------------------------------------
# Locality-level AW_EKA parent (refinement)
# ---------------------------------------------------------------------------


@pytest.fixture
def vzd_files_priekuli(tmp_path):
    """Minimal Priekuļi locality fixture: AW_EKA parent is AW_CIEMS, not AW_IELA.

    VZD hierarchy:
      AW_NOVADS:  300  → Cēsu nov.
      AW_PAGASTS: 250  → Priekuļu pag. (under 300)
      AW_CIEMS:   240  → Priekuļi (under 250)
      AW_IELA:    empty
      AW_EKA:     501  → parent 240 (the village), not a street

    Expected importer behavior:
      - Create AddressGroup with label "Priekuļi, Priekuļu pag."
      - group.street_code == "", group.street_name == ""
      - group.locality_code == "240", group.locality_name == "Priekuļi"
      - group.region_code == "300", group.region_name == "Cēsu nov."
      - Create AddressEntry with the full STD label.
    """
    from apps.addresses.services import VzdAddressFiles

    novads = write_csv(
        tmp_path / "AW_NOVADS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["300,EKS,Cesu nov.,"],
    )
    pagasts = write_csv(
        tmp_path / "AW_PAGASTS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["250,EKS,Priekulu pag.,300"],
    )
    pilseta = write_csv(
        tmp_path / "AW_PILSETA.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        [],
    )
    ciems = write_csv(
        tmp_path / "AW_CIEMS.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        ["240,EKS,Priekuli,250"],
    )
    iela = write_csv(
        tmp_path / "AW_IELA.CSV",
        "KODS,STATUSS,NOSAUKUMS,VKUR_CD",
        [],
    )
    eka = write_csv(
        tmp_path / "AW_EKA.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
        ['501,EKS,240,Saules 1,"Saules 1, Priekuli, Priekulu pag., Cesu nov.",LV-4126,,,,'],
    )
    return VzdAddressFiles(
        novads=novads, pagasts=pagasts, pilseta=pilseta, ciems=ciems, iela=iela, eka=eka,
    )


@pytest.mark.django_db
def test_import_creates_locality_group_for_non_street_parent(vzd_files_priekuli):
    """AW_EKA whose VKUR_CD is a locality (not a street) must produce a group."""
    from apps.addresses.models import AddressEntry, AddressGroup, AddressImportRun
    from apps.addresses.services import import_vzd_addresses

    run = import_vzd_addresses(vzd_files_priekuli, region_codes=["300"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.group_count == 1
    assert run.entry_count == 1

    group = AddressGroup.objects.get()
    assert group.label == "Priekuli, Priekulu pag."
    assert group.street_code == ""
    assert group.street_name == ""
    assert group.locality_code == "240"
    assert group.locality_name == "Priekuli"
    assert group.region_code == "300"
    assert group.region_name == "Cesu nov."
    assert group.entry_count == 1

    entry = AddressEntry.objects.get()
    assert entry.label == "Saules 1, Priekuli, Priekulu pag., Cesu nov."
    assert entry.group == group
    assert entry.vzd_code == "501"
    assert entry.postal_code == "LV-4126"

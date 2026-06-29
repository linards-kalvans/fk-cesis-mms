# VZD Scheduled Address Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build weekly URL-backed VZD address import with apartment suggestions, failure-safe replacement, and admin import-run visibility.

**Architecture:** Reuse `apps.addresses` as the only address boundary. Add URL download + weekly django-q task around the existing importer, extend the local search index with `AddressApartment`, and keep registration/domain address persistence as plain text only. Keep the current atomic replace strategy; no staging tables.

**Tech Stack:** Django 5, django-q2 `Schedule`, pytest/pytest-django, stdlib `urllib.request`, existing parent autocomplete JavaScript.

---

## Design Decisions

1. **URL import lives in `apps.addresses`, not `apps.integrations`.**
   - Why: VZD data is address-search reference data, not a business integration with retries/state like OCR/Invoice Ninja. Keeping it in `apps.addresses` preserves the existing boundary.

2. **Use stdlib `urllib.request` for downloads.**
   - Why: avoids adding a dependency for seven public CSV GETs. Existing project already has `requests`, but this task does not need sessions/auth/provider adapters.

3. **Keep current atomic delete+insert replacement.**
   - Why: confirmed scope excludes snapshot tables. The current transaction prevents half-empty indexes on DB failure and is the smallest safe path.

4. **Store apartments in a separate `AddressApartment` table.**
   - Why: building-first UX needs `AW_DZIV` rows linked to parent `AW_EKA` buildings. Reusing `AddressEntry` for both would blur building vs unit state and complicate `group=<id>` behavior.

5. **Drop guard counts selectable rows: buildings + apartments.**
   - Why: this is the user-visible autocomplete corpus. A failed `AW_DZIV` download should be caught, not hidden by unchanged building counts.

6. **Scheduled job skips when region codes are missing.**
   - Why: deploy should not create noisy failure rows before operators configure regions. Once configured, imports run automatically.

7. **Admin exposes `AddressImportRun` only.**
   - Why: groups/buildings/apartments can be large operational search data. Staff need status/count/error visibility, not raw search browsing.

---

## File-by-File Plan

### Create

- `apps/addresses/tasks.py`
  - Public task function: `import_vzd_addresses_from_urls() -> None`
  - Calls URL-backed service path.
  - Skips when `settings.ADDRESS_AUTOCOMPLETE_REGION_CODES` is empty.

- `apps/addresses/admin.py`
  - Read-only `AddressImportRunAdmin`.

- `apps/addresses/migrations/0002_addressapartment.py`
  - Adds `AddressApartment`.

- `apps/addresses/migrations/0003_vzd_weekly_import_schedule.py`
  - Adds django-q weekly schedule.

- `tests/addresses/test_scheduled_import.py`
  - URL download path, task, schedule, drop guard.

- `tests/addresses/test_admin.py`
  - Read-only admin visibility.

### Modify

- `apps/addresses/models.py`
  - Add `AddressApartment`.
  - Keep existing models.

- `apps/addresses/services.py`
  - Extend `VzdAddressFiles` with `dziv: Path | None = None`.
  - Add URL defaults/settings helpers if not placed in settings.
  - Add `download_vzd_address_files(destination: Path) -> VzdAddressFiles`.
  - Add `import_vzd_addresses_from_urls(region_codes: list[str]) -> AddressImportRun`.
  - Extend `import_vzd_addresses(...)` with optional drop-guard settings.
  - Add `search_apartments(query: str, building_id: int, limit: int = 10) -> list[dict[str, str]]`.
  - Add `apartment_count` into `AddressImportRun.entry_count` total.

- `apps/addresses/management/commands/import_addresses.py`
  - Make file flags optional.
  - Add `--dziv` optional path.
  - No args downloads from configured/default URLs.
  - Local flags override downloaded files.

- `apps/addresses/views.py`
  - Parse `building` query param.
  - Prefer building-scoped apartment search over group search when valid.

- `static/js/address_autocomplete.js`
  - Track selected building id/label after `kind === "address"`.
  - Continue fetching with `building=<id>` for apartment suggestions.
  - Clear building state if input text changes away from selected building label.

- `fk_cesis_mms/settings.py`
  - Add seven URL settings with defaults.
  - Add `ADDRESS_IMPORT_WEEKDAY`, `ADDRESS_IMPORT_HOUR`, `ADDRESS_IMPORT_MAX_DROP_RATIO`, `ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS`.

- `.env.example`
  - Add URL overrides and schedule/drop settings.

- `docs/address-autocomplete.md`
  - Update manual import docs, scheduled import behavior, `AW_DZIV`, failure behavior.

- `AGENTS.md`
  - Add delivered note after implementation is accepted.

---

## Test Strategy

- **Framework:** pytest + pytest-django.
- **TDD order:** tests first, implementation second.
- **Mocking:** use `unittest.mock.patch` / pytest `monkeypatch`; do not hit real data.gov.lv.
- **What to test:** service import, command contracts, URL download failure safety, scheduled task, schedule migration, apartment search API, admin read-only.
- **What not to test:** real VZD network availability, browser-level dropdown rendering beyond JS contract text checks, national full dataset performance.

---

## Task 1: Add Apartment Model and Migration

**Files:**
- Modify: `apps/addresses/models.py`
- Create: `apps/addresses/migrations/0002_addressapartment.py`
- Test: `tests/addresses/test_models.py`

- [ ] **Step 1: Write failing model test**

Add to `tests/addresses/test_models.py`:

```python
@pytest.mark.django_db
def test_address_apartment_model_links_to_building():
    from apps.addresses.models import AddressApartment, AddressEntry, AddressGroup

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
    building = AddressEntry.objects.create(
        vzd_code="401",
        label="Raiņa iela 12, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 cesis cesu nov",
        group=group,
        postal_code="LV-4101",
        region_code="300",
        region_name="Cēsu nov.",
    )

    apartment = AddressApartment.objects.create(
        vzd_code="9001",
        building=building,
        label="Raiņa iela 12-3, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 3 cesis cesu nov",
        postal_code="LV-4101",
    )

    assert str(apartment) == "Raiņa iela 12-3, Cēsis, Cēsu nov."
    assert apartment.building == building
```

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run pytest tests/addresses/test_models.py::test_address_apartment_model_links_to_building -q
```

Expected: fail importing `AddressApartment`.

- [ ] **Step 3: Implement model**

Add to `apps/addresses/models.py` after `AddressEntry`:

```python
class AddressApartment(models.Model):
    """One selectable apartment / unit address from AW_DZIV."""

    vzd_code = models.CharField(max_length=32, unique=True)
    building = models.ForeignKey(
        AddressEntry,
        on_delete=models.CASCADE,
        related_name="apartments",
    )
    label = models.CharField(max_length=255)
    normalized_label = models.CharField(max_length=255, db_index=True)
    postal_code = models.CharField(max_length=16, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["building", "normalized_label"]),
            models.Index(fields=["normalized_label"]),
        ]

    def __str__(self) -> str:
        return str(self.label)
```

- [ ] **Step 4: Create migration**

Run:

```bash
uv run python manage.py makemigrations addresses
```

Expected: creates `apps/addresses/migrations/0002_addressapartment.py`.

- [ ] **Step 5: Verify test passes**

Run:

```bash
uv run pytest tests/addresses/test_models.py::test_address_apartment_model_links_to_building -q
```

Expected: pass.

---

## Task 2: Import AW_DZIV Apartments

**Files:**
- Modify: `apps/addresses/services.py`
- Modify: `tests/addresses/test_import_addresses.py`

- [ ] **Step 1: Extend fixtures/tests first**

Update `vzd_files` fixture in `tests/addresses/test_import_addresses.py` to create `AW_DZIV.CSV` and pass it into `VzdAddressFiles`:

```python
dziv = write_csv(
    tmp_path / "AW_DZIV.CSV",
    "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB",
    [
        '9001,EKS,401,3,"Raina iela 1-3, Cesis, Cesu nov.",LV-4101',
        '9002,DEL,401,4,"Raina iela 1-4, Cesis, Cesu nov.",LV-4101',
    ],
)
return VzdAddressFiles(
    novads=novads,
    pagasts=pagasts,
    pilseta=pilseta,
    ciems=ciems,
    iela=iela,
    eka=eka,
    dziv=dziv,
)
```

Add test:

```python
@pytest.mark.django_db
def test_import_vzd_addresses_imports_active_apartments(vzd_files):
    from apps.addresses.models import AddressApartment, AddressEntry, AddressImportRun
    from apps.addresses.services import import_vzd_addresses

    run = import_vzd_addresses(vzd_files, region_codes=["300"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.entry_count == 3
    building = AddressEntry.objects.get(vzd_code="401")
    assert list(
        AddressApartment.objects.order_by("vzd_code").values_list("vzd_code", "building_id", "label")
    ) == [
        ("9001", building.id, "Raina iela 1-3, Cesis, Cesu nov."),
    ]
```

- [ ] **Step 2: Run failing test**

```bash
uv run pytest tests/addresses/test_import_addresses.py::test_import_vzd_addresses_imports_active_apartments -q
```

Expected: fail because `VzdAddressFiles` has no `dziv` or no apartment import.

- [ ] **Step 3: Extend service dataclass and import logic**

Modify `apps/addresses/services.py` imports:

```python
from apps.addresses.models import AddressApartment, AddressEntry, AddressGroup, AddressImportRun
```

Change dataclass:

```python
@dataclass(frozen=True)
class VzdAddressFiles:
    novads: Path
    pagasts: Path
    pilseta: Path
    ciems: Path
    iela: Path
    eka: Path
    dziv: Path | None = None
```

In `import_vzd_addresses`, read dziv rows after `eka_rows`:

```python
dziv_rows = _active_rows(_read_csv(files.dziv)) if files.dziv else []
```

After `entries` is built, create apartments from rows whose parent building was imported:

```python
apartments: list[AddressApartment] = []
entry_by_code = {entry.vzd_code: entry for entry in entries}
for row in dziv_rows:
    building = entry_by_code.get(row["VKUR_CD"].strip())
    if not building:
        continue
    apartments.append(
        AddressApartment(
            vzd_code=row["KODS"].strip(),
            building=building,
            label=row["STD"].strip().strip('"'),
            normalized_label=normalize_address_query(row["STD"].strip().strip('"')),
            postal_code=row.get("ATRIB", "").strip(),
        )
    )
```

Inside transaction, delete apartments before entries/groups through cascade or explicit clear; use explicit for clarity:

```python
AddressApartment.objects.all().delete()
AddressGroup.objects.all().delete()
```

After `AddressEntry.objects.bulk_create(entries)`, reload building IDs and bulk-create apartments:

```python
saved_entries = {entry.vzd_code: entry for entry in AddressEntry.objects.filter(vzd_code__in=entry_by_code)}
for apartment in apartments:
    apartment.building_id = saved_entries[apartment.building.vzd_code].id
AddressApartment.objects.bulk_create(apartments)
```

Set count:

```python
run.entry_count = len(entries) + len(apartments)
```

- [ ] **Step 4: Update existing count assertions**

Existing tests expecting `entry_count == 2` for `vzd_files` must expect `3` after fixture includes one apartment. Keep tests using custom fixtures without `dziv` unchanged.

- [ ] **Step 5: Verify import tests**

Run:

```bash
uv run pytest tests/addresses/test_import_addresses.py -q
```

Expected: all address import tests pass.

---

## Task 3: Add Apartment Search and Endpoint

**Files:**
- Modify: `apps/addresses/services.py`
- Modify: `apps/addresses/views.py`
- Modify: `tests/addresses/test_search.py`
- Modify: `tests/addresses/test_autocomplete_view.py`

- [ ] **Step 1: Write service test**

Add to `tests/addresses/test_search.py`:

```python
@pytest.mark.django_db
def test_search_apartments_returns_units_for_selected_building():
    from apps.addresses.models import AddressApartment, AddressEntry, AddressGroup
    from apps.addresses.services import search_apartments

    group = AddressGroup.objects.create(label="Raiņa iela, Cēsis", normalized_label="raina iela cesis")
    building = AddressEntry.objects.create(
        vzd_code="401",
        label="Raiņa iela 12, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 cesis cesu nov",
        group=group,
        postal_code="LV-4101",
    )
    AddressApartment.objects.create(
        vzd_code="9001",
        building=building,
        label="Raiņa iela 12-3, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 3 cesis cesu nov",
        postal_code="LV-4101",
    )

    assert search_apartments("3", building.id) == [
        {
            "kind": "apartment",
            "id": "9001",
            "label": "Raiņa iela 12-3, Cēsis, Cēsu nov.",
            "hint": "LV-4101",
        }
    ]
```

- [ ] **Step 2: Write view test**

Add to `tests/addresses/test_autocomplete_view.py`:

```python
@pytest.mark.django_db
def test_autocomplete_supports_building_apartment_suffix(verified_client):
    from apps.addresses.models import AddressApartment, AddressEntry, AddressGroup

    group = AddressGroup.objects.create(label="Raiņa iela, Cēsis", normalized_label="raina iela cesis")
    building = AddressEntry.objects.create(
        vzd_code="401",
        label="Raiņa iela 12, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 cesis cesu nov",
        group=group,
        postal_code="LV-4101",
    )
    AddressApartment.objects.create(
        vzd_code="9001",
        building=building,
        label="Raiņa iela 12-3, Cēsis, Cēsu nov.",
        normalized_label="raina iela 12 3 cesis cesu nov",
        postal_code="LV-4101",
    )

    response = verified_client.get(
        reverse("addresses:autocomplete"), {"q": "3", "building": str(building.id)}
    )

    assert response.status_code == 200
    assert response.json()["results"] == [
        {
            "kind": "apartment",
            "id": "9001",
            "label": "Raiņa iela 12-3, Cēsis, Cēsu nov.",
            "hint": "LV-4101",
        }
    ]
```

- [ ] **Step 3: Run failing tests**

```bash
uv run pytest tests/addresses/test_search.py::test_search_apartments_returns_units_for_selected_building tests/addresses/test_autocomplete_view.py::test_autocomplete_supports_building_apartment_suffix -q
```

Expected: fail because `search_apartments` and `building` param do not exist.

- [ ] **Step 4: Implement `search_apartments`**

Add to `apps/addresses/services.py`:

```python
def search_apartments(query: str, building_id: int, limit: int = 10) -> list[dict[str, str]]:
    normalized = normalize_address_query(query)
    if not normalized:
        return []
    filters = Q(building_id=building_id)
    for token in normalized.split():
        filters &= Q(normalized_label__icontains=token)
    rows = (
        AddressApartment.objects.filter(filters)
        .order_by("normalized_label")
        .values("vzd_code", "label", "postal_code")[:limit]
    )
    return [
        {
            "kind": "apartment",
            "id": row["vzd_code"],
            "label": row["label"],
            "hint": row["postal_code"] or "",
        }
        for row in rows
    ]
```

- [ ] **Step 5: Implement view param**

Modify imports in `apps/addresses/views.py`:

```python
from apps.addresses.services import search_addresses, search_apartments
```

Modify `autocomplete`:

```python
building_id = request.GET.get("building")
parsed_building_id: int | None = None
if building_id is not None:
    try:
        parsed_building_id = int(building_id)
    except ValueError:
        parsed_building_id = None
if parsed_building_id is not None:
    results = search_apartments(query, building_id=parsed_building_id)
    return JsonResponse({"results": results})
```

Keep existing group handling after this block.

- [ ] **Step 6: Verify tests pass**

```bash
uv run pytest tests/addresses/test_search.py tests/addresses/test_autocomplete_view.py -q
```

Expected: pass.

---

## Task 4: URL Download Settings and No-Arg Command

**Files:**
- Modify: `fk_cesis_mms/settings.py`
- Modify: `apps/addresses/services.py`
- Modify: `apps/addresses/management/commands/import_addresses.py`
- Modify: `tests/addresses/test_import_addresses.py`
- Create/Modify: `tests/addresses/test_scheduled_import.py`

- [ ] **Step 1: Write settings/download tests**

Create `tests/addresses/test_scheduled_import.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from django.test import override_settings


def _write_response(url: str, target: Path) -> None:
    target.write_text("KODS,STATUSS,NOSAUKUMS,VKUR_CD\n", encoding="utf-8")


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
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/addresses/test_scheduled_import.py::test_address_import_url_defaults_exist tests/addresses/test_scheduled_import.py::test_download_vzd_address_files_writes_all_files -q
```

Expected: fail missing settings/helper.

- [ ] **Step 3: Add settings**

Add to `fk_cesis_mms/settings.py` near existing address settings:

```python
ADDRESS_IMPORT_AW_NOVADS_URL = os.environ.get("ADDRESS_IMPORT_AW_NOVADS_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/c62c60bb-58d4-4f26-82c0-5b630769f9d1/download/aw_novads.csv"
ADDRESS_IMPORT_AW_PAGASTS_URL = os.environ.get("ADDRESS_IMPORT_AW_PAGASTS_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/6ba8c905-27a1-443a-b9c6-256a0777425b/download/aw_pagasts.csv"
ADDRESS_IMPORT_AW_PILSETA_URL = os.environ.get("ADDRESS_IMPORT_AW_PILSETA_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/ee02baa4-2bc3-4f77-a6cb-5427a3e9befe/download/aw_pilseta.csv"
ADDRESS_IMPORT_AW_CIEMS_URL = os.environ.get("ADDRESS_IMPORT_AW_CIEMS_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/0d3810f4-1ac0-4fba-8b10-0188084a361b/download/aw_ciems.csv"
ADDRESS_IMPORT_AW_IELA_URL = os.environ.get("ADDRESS_IMPORT_AW_IELA_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/3c4ab802-76cf-433c-9c1c-89215e28d833/download/aw_iela.csv"
ADDRESS_IMPORT_AW_EKA_URL = os.environ.get("ADDRESS_IMPORT_AW_EKA_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/a510737a-18ce-400f-ad4b-04fce5228272/download/aw_eka.csv"
ADDRESS_IMPORT_AW_DZIV_URL = os.environ.get("ADDRESS_IMPORT_AW_DZIV_URL") or "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/b83be373-f444-4f50-9b98-28741845325e/download/aw_dziv.csv"
ADDRESS_IMPORT_WEEKDAY = int(os.environ.get("ADDRESS_IMPORT_WEEKDAY", "6"))
ADDRESS_IMPORT_HOUR = int(os.environ.get("ADDRESS_IMPORT_HOUR", "1"))
ADDRESS_IMPORT_MAX_DROP_RATIO = float(os.environ.get("ADDRESS_IMPORT_MAX_DROP_RATIO", "0.50"))
ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS", "30"))
```

- [ ] **Step 4: Add downloader helpers**

Add to `apps/addresses/services.py` imports:

```python
import urllib.request
from django.conf import settings
```

Add helpers:

```python
def _download_file(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=settings.ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS) as response:
        target.write_bytes(response.read())


def download_vzd_address_files(destination: Path) -> VzdAddressFiles:
    destination.mkdir(parents=True, exist_ok=True)
    mapping = {
        "novads": (settings.ADDRESS_IMPORT_AW_NOVADS_URL, destination / "AW_NOVADS.CSV"),
        "pagasts": (settings.ADDRESS_IMPORT_AW_PAGASTS_URL, destination / "AW_PAGASTS.CSV"),
        "pilseta": (settings.ADDRESS_IMPORT_AW_PILSETA_URL, destination / "AW_PILSETA.CSV"),
        "ciems": (settings.ADDRESS_IMPORT_AW_CIEMS_URL, destination / "AW_CIEMS.CSV"),
        "iela": (settings.ADDRESS_IMPORT_AW_IELA_URL, destination / "AW_IELA.CSV"),
        "eka": (settings.ADDRESS_IMPORT_AW_EKA_URL, destination / "AW_EKA.CSV"),
        "dziv": (settings.ADDRESS_IMPORT_AW_DZIV_URL, destination / "AW_DZIV.CSV"),
    }
    for url, target in mapping.values():
        _download_file(url, target)
    return VzdAddressFiles(**{name: target for name, (_url, target) in mapping.items()})
```

- [ ] **Step 5: Update management command parser**

In `apps/addresses/management/commands/import_addresses.py`, make existing file args optional and add `--dziv`:

```python
parser.add_argument("--novads", type=Path, required=False)
...
parser.add_argument("--dziv", type=Path, required=False)
```

In `handle`, if any file path is missing, download all files to `tempfile.TemporaryDirectory()` and fill missing paths from downloaded files. Local flags override downloaded files.

Use this structure:

```python
import tempfile

from apps.addresses.services import download_vzd_address_files

with tempfile.TemporaryDirectory() as tmp:
    downloaded = None
    if not all(options[name] for name in ("novads", "pagasts", "pilseta", "ciems", "iela", "eka", "dziv")):
        downloaded = download_vzd_address_files(Path(tmp))
    files = VzdAddressFiles(
        novads=Path(options["novads"]) if options["novads"] else downloaded.novads,
        pagasts=Path(options["pagasts"]) if options["pagasts"] else downloaded.pagasts,
        pilseta=Path(options["pilseta"]) if options["pilseta"] else downloaded.pilseta,
        ciems=Path(options["ciems"]) if options["ciems"] else downloaded.ciems,
        iela=Path(options["iela"]) if options["iela"] else downloaded.iela,
        eka=Path(options["eka"]) if options["eka"] else downloaded.eka,
        dziv=Path(options["dziv"]) if options["dziv"] else downloaded.dziv,
    )
    run = import_vzd_addresses(files, region_codes=region_codes)
```

If `download_vzd_address_files` raises, create failed `AddressImportRun` with source `vzd_varis`, region codes, error, finished_at, then raise `CommandError`.

- [ ] **Step 6: Add command no-arg/override tests**

In `tests/addresses/test_import_addresses.py`, first add this import near the top:

```python
from unittest.mock import patch
```

Then add:

```python
@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=["300"])
def test_import_command_downloads_when_file_args_omitted(vzd_files):
    from apps.addresses.models import AddressEntry
    from apps.addresses.services import VzdAddressFiles

    with patch(
        "apps.addresses.management.commands.import_addresses.download_vzd_address_files",
        return_value=vzd_files,
    ) as mocked:
        call_command("import_addresses")

    mocked.assert_called_once()
    assert AddressEntry.objects.count() == 2
```

And override test:

```python
@pytest.mark.django_db
@override_settings(ADDRESS_AUTOCOMPLETE_REGION_CODES=["300"])
def test_import_command_local_flags_override_downloaded_files(vzd_files, tmp_path):
    from apps.addresses.models import AddressEntry
    from apps.addresses.services import VzdAddressFiles

    downloaded = vzd_files
    override_eka = write_csv(
        tmp_path / "OVERRIDE_EKA.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
        ['777,EKS,100,7,"Raina iela 7, Cesis, Cesu nov.",LV-4101,,,,'],
    )

    with patch(
        "apps.addresses.management.commands.import_addresses.download_vzd_address_files",
        return_value=downloaded,
    ):
        call_command("import_addresses", eka=str(override_eka))

    assert list(AddressEntry.objects.values_list("vzd_code", flat=True)) == ["777"]
```

- [ ] **Step 7: Verify command/download tests**

```bash
uv run pytest tests/addresses/test_import_addresses.py tests/addresses/test_scheduled_import.py -q
```

Expected: pass.

---

## Task 5: Failure-Safe Import and Suspicious Drop Guard

**Files:**
- Modify: `apps/addresses/services.py`
- Modify: `tests/addresses/test_scheduled_import.py`

- [ ] **Step 1: Write drop-guard tests**

Add to `tests/addresses/test_scheduled_import.py`:

```python
@pytest.mark.django_db
@override_settings(ADDRESS_IMPORT_MAX_DROP_RATIO=0.50)
def test_suspicious_drop_blocks_replacement(vzd_files, tmp_path):
    from apps.addresses.models import AddressEntry, AddressImportRun
    from apps.addresses.services import VzdAddressFiles, import_vzd_addresses

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
```

Add no previous success test:

```python
@pytest.mark.django_db
@override_settings(ADDRESS_IMPORT_MAX_DROP_RATIO=0.50)
def test_drop_guard_skips_when_no_previous_success(vzd_files):
    from apps.addresses.models import AddressImportRun
    from apps.addresses.services import import_vzd_addresses

    run = import_vzd_addresses(vzd_files, region_codes=["999"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.entry_count == 0
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/addresses/test_scheduled_import.py::test_suspicious_drop_blocks_replacement tests/addresses/test_scheduled_import.py::test_drop_guard_skips_when_no_previous_success -q
```

Expected: suspicious-drop test fails.

- [ ] **Step 3: Implement guard before transaction**

Add helper in `apps/addresses/services.py`:

```python
def _latest_successful_import() -> AddressImportRun | None:
    return AddressImportRun.objects.filter(status=AddressImportRun.Status.SUCCEEDED).order_by("-finished_at", "-started_at").first()


def _is_suspicious_drop(new_count: int, previous_count: int) -> bool:
    if previous_count <= 0:
        return False
    max_drop_ratio = getattr(settings, "ADDRESS_IMPORT_MAX_DROP_RATIO", 0.50)
    minimum_allowed = previous_count * (1 - max_drop_ratio)
    return new_count < minimum_allowed
```

Before transaction in `import_vzd_addresses`:

```python
new_entry_count = len(entries) + len(apartments)
previous = _latest_successful_import()
if previous and _is_suspicious_drop(new_entry_count, previous.entry_count):
    run.status = AddressImportRun.Status.FAILED
    run.error_message = (
        f"Suspicious address import drop: previous={previous.entry_count}, new={new_entry_count}"
    )
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error_message", "finished_at"])
    return run
```

Also fail zero-row imports when there is a previous successful index to protect:

```python
if new_entry_count == 0 and region_set:
    previous = _latest_successful_import()
    if previous:
        run.status = AddressImportRun.Status.FAILED
        run.error_message = "Address import produced zero selectable rows."
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error_message", "finished_at"])
        return run
```

Keep existing no-previous zero import test green per confirmed no-previous guard skip.

- [ ] **Step 4: Verify tests**

```bash
uv run pytest tests/addresses/test_scheduled_import.py tests/addresses/test_import_addresses.py -q
```

Expected: pass.

---

## Task 6: Weekly Scheduled Task and Migration

**Files:**
- Create: `apps/addresses/tasks.py`
- Create: `apps/addresses/migrations/0003_vzd_weekly_import_schedule.py`
- Modify: `tests/addresses/test_scheduled_import.py`

- [ ] **Step 1: Write task test**

Add to `tests/addresses/test_scheduled_import.py`:

```python
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
```

- [ ] **Step 2: Write schedule migration test**

Add this DB assertion in `tests/addresses/test_scheduled_import.py`; pytest runs after migrations, so the schedule row should already exist:

```python
@pytest.mark.django_db
def test_weekly_address_import_schedule_exists():
    from django_q.models import Schedule

    schedule = Schedule.objects.get(name="address-vzd-weekly-import")
    assert schedule.func == "apps.addresses.tasks.import_vzd_addresses_from_urls"
    assert schedule.schedule_type == Schedule.WEEKLY
```

- [ ] **Step 3: Run failing tests**

```bash
uv run pytest tests/addresses/test_scheduled_import.py::test_scheduled_import_skips_without_region_codes tests/addresses/test_scheduled_import.py::test_scheduled_import_calls_url_import tests/addresses/test_scheduled_import.py::test_weekly_address_import_schedule_exists -q
```

Expected: fail missing task/schedule.

- [ ] **Step 4: Add task module**

Create `apps/addresses/tasks.py`:

```python
"""Scheduled VZD address import tasks."""

from __future__ import annotations

import logging

from django.conf import settings

from apps.addresses.services import import_vzd_addresses_from_urls as import_vzd_addresses_from_urls_service

logger = logging.getLogger(__name__)


def import_vzd_addresses_from_urls() -> None:
    region_codes = list(getattr(settings, "ADDRESS_AUTOCOMPLETE_REGION_CODES", []))
    if not region_codes:
        logger.info("address import skipped: ADDRESS_AUTOCOMPLETE_REGION_CODES is empty")
        return
    import_vzd_addresses_from_urls_service(region_codes=region_codes)
```

Add service wrapper in `apps/addresses/services.py`:

```python
def import_vzd_addresses_from_urls(region_codes: list[str]) -> AddressImportRun:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        files = download_vzd_address_files(Path(tmp))
        return import_vzd_addresses(files, region_codes=region_codes)
```

- [ ] **Step 5: Add schedule migration**

Create `apps/addresses/migrations/0003_vzd_weekly_import_schedule.py`:

```python
"""Register weekly VZD address import django-q2 Schedule."""

import datetime

from django.conf import settings
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "address-vzd-weekly-import"
SCHEDULE_FUNC = "apps.addresses.tasks.import_vzd_addresses_from_urls"


def _next_run():
    weekday = getattr(settings, "ADDRESS_IMPORT_WEEKDAY", 6)
    hour = getattr(settings, "ADDRESS_IMPORT_HOUR", 1)
    now = timezone.localtime()
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    days_ahead = (weekday - candidate.weekday()) % 7
    candidate += datetime.timedelta(days=days_ahead)
    if candidate <= now:
        candidate += datetime.timedelta(days=7)
    return candidate


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": SCHEDULE_FUNC,
            "schedule_type": Schedule.WEEKLY,
            "next_run": _next_run(),
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("addresses", "0002_addressapartment"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
```

- [ ] **Step 6: Verify task/schedule tests**

```bash
uv run pytest tests/addresses/test_scheduled_import.py -q
```

Expected: pass.

---

## Task 7: Parent JS Building-to-Apartment Flow

**Files:**
- Modify: `static/js/address_autocomplete.js`
- Test: existing static/template tests if any; otherwise add focused static content test in `tests/addresses/test_autocomplete_static.py`

- [ ] **Step 1: Add static contract test**

Create `tests/addresses/test_autocomplete_static.py`:

```python
from pathlib import Path


def test_address_autocomplete_js_tracks_building_for_apartments():
    js = Path("static/js/address_autocomplete.js").read_text(encoding="utf-8")

    assert "data-address-building-id" in js
    assert "data-address-building-label" in js
    assert "&building=" in js
    assert "result.kind === \"address\"" in js
    assert "result.kind === \"apartment\"" in js
```

- [ ] **Step 2: Run failing test**

```bash
uv run pytest tests/addresses/test_autocomplete_static.py -q
```

Expected: fail missing building/apartment strings.

- [ ] **Step 3: Update JS state handling**

In `selectResult`:

```javascript
if (result.kind === "group") {
  input.setAttribute("data-address-group-id", result.id);
  input.setAttribute("data-address-group-label", result.label);
  input.removeAttribute("data-address-building-id");
  input.removeAttribute("data-address-building-label");
  input.focus();
  dropdown.innerHTML = "";
  dropdown.style.display = "block";
  fetchSuggestions(input, dropdown);
} else if (result.kind === "address") {
  input.setAttribute("data-address-building-id", result.id);
  input.setAttribute("data-address-building-label", result.label);
  input.removeAttribute("data-address-group-id");
  input.removeAttribute("data-address-group-label");
  input.focus();
  dropdown.innerHTML = "";
  dropdown.style.display = "block";
  fetchSuggestions(input, dropdown);
} else if (result.kind === "apartment") {
  input.removeAttribute("data-address-group-id");
  input.removeAttribute("data-address-group-label");
  input.removeAttribute("data-address-building-id");
  input.removeAttribute("data-address-building-label");
  closeDropdown(dropdown);
} else {
  input.removeAttribute("data-address-group-id");
  input.removeAttribute("data-address-group-label");
  input.removeAttribute("data-address-building-id");
  input.removeAttribute("data-address-building-label");
  closeDropdown(dropdown);
}
```

Add `getBuildingId` mirroring `getGroupId`:

```javascript
function getBuildingId(input) {
  var raw = input.getAttribute("data-address-building-id");
  if (!raw) return null;
  var value = input.value.trim();
  var buildingLabel = input.getAttribute("data-address-building-label") || "";
  if (buildingLabel && value.indexOf(buildingLabel) !== 0) {
    input.removeAttribute("data-address-building-id");
    input.removeAttribute("data-address-building-label");
    return null;
  }
  return raw;
}
```

Update `getQuery` to prefer building suffix:

```javascript
var buildingLabel = input.getAttribute("data-address-building-label") || "";
if (getBuildingId(input) && buildingLabel && value.indexOf(buildingLabel) === 0) {
  var buildingSuffix = value.slice(buildingLabel.length).replace(/^\s*,?\s*/, "").trim();
  return buildingSuffix || buildingLabel;
}
```

Update `fetchSuggestions`:

```javascript
var buildingId = getBuildingId(input);
...
if (query.length < MIN_CHARS && !groupId && !buildingId) {
...
if (buildingId) {
  url += "&building=" + encodeURIComponent(buildingId);
} else if (groupId) {
  url += "&group=" + encodeURIComponent(groupId);
}
```

- [ ] **Step 4: Verify static test**

```bash
uv run pytest tests/addresses/test_autocomplete_static.py -q
```

Expected: pass.

---

## Task 8: Admin Visibility

**Files:**
- Create: `apps/addresses/admin.py`
- Create/Modify: `tests/addresses/test_admin.py`

- [ ] **Step 1: Write admin tests**

Create `tests/addresses/test_admin.py`:

```python
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
```

- [ ] **Step 2: Run failing tests**

```bash
uv run pytest tests/addresses/test_admin.py -q
```

Expected: fail not registered.

- [ ] **Step 3: Implement admin**

Create `apps/addresses/admin.py`:

```python
from __future__ import annotations

from django.contrib import admin

from apps.addresses.models import AddressImportRun


@admin.register(AddressImportRun)
class AddressImportRunAdmin(admin.ModelAdmin):
    list_display = ("source", "status", "started_at", "finished_at", "region_codes", "group_count", "entry_count")
    list_filter = ("status", "source", "started_at")
    search_fields = ("source", "region_codes", "error_message")
    readonly_fields = (
        "source",
        "started_at",
        "finished_at",
        "status",
        "region_codes",
        "group_count",
        "entry_count",
        "error_message",
        "source_modified_at",
    )
    date_hierarchy = "started_at"
    ordering = ("-started_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Verify admin tests**

```bash
uv run pytest tests/addresses/test_admin.py -q
```

Expected: pass.

---

## Task 9: Docs and Env Example

**Files:**
- Modify: `.env.example`
- Modify: `docs/address-autocomplete.md`
- Modify: `AGENTS.md`
- Test: none beyond static docs review

- [ ] **Step 1: Update `.env.example`**

Add under address section:

```env
# Weekly VZD address import. Weekday uses Python convention: Monday=0, Sunday=6.
ADDRESS_IMPORT_WEEKDAY=6
ADDRESS_IMPORT_HOUR=1
ADDRESS_IMPORT_MAX_DROP_RATIO=0.50
ADDRESS_IMPORT_DOWNLOAD_TIMEOUT_SECONDS=30
# Optional URL overrides. Defaults are official data.gov.lv VARIS downloads.
ADDRESS_IMPORT_AW_NOVADS_URL=
ADDRESS_IMPORT_AW_PAGASTS_URL=
ADDRESS_IMPORT_AW_PILSETA_URL=
ADDRESS_IMPORT_AW_CIEMS_URL=
ADDRESS_IMPORT_AW_IELA_URL=
ADDRESS_IMPORT_AW_EKA_URL=
ADDRESS_IMPORT_AW_DZIV_URL=
```

- [ ] **Step 2: Update `docs/address-autocomplete.md`**

Replace manual-only scope with:

```markdown
## Scheduled import

The app registers a weekly django-q job named `address-vzd-weekly-import`.
By default it runs Sunday 01:00 Europe/Riga and downloads the official data.gov.lv VARIS CSV files.

The job runs when `ADDRESS_AUTOCOMPLETE_REGION_CODES` is configured. If no region codes are configured, it skips without creating a failed import run.

Source URLs have built-in defaults and can be overridden with `ADDRESS_IMPORT_AW_*_URL` env vars.
```

Update imported files list to include:

```markdown
- `AW_DZIV.CSV` — apartment / unit addresses, shown only after a building is selected
```

Update failure behavior:

```markdown
Failed downloads/imports keep the previous index. A suspicious drop greater than `ADDRESS_IMPORT_MAX_DROP_RATIO` (default `0.50`) also fails the run and keeps old data.
```

- [ ] **Step 3: Update `AGENTS.md` current status**

Add one bullet in Current Status once implementation is verified:

```markdown
- Address autocomplete now has a weekly URL-backed VZD VARIS import with `AW_DZIV` apartment suggestions, suspicious-drop protection, and read-only import-run admin visibility.
```

- [ ] **Step 4: Docs check**

Run:

```bash
uv run python -m json.tool opencode.json >/dev/null
```

Expected: pass. This repo uses this as a config sanity check; docs themselves have no separate linter.

---

## Task 10: Final Verification

**Files:** all changed files.

- [ ] **Step 1: Run focused address tests**

```bash
uv run pytest tests/addresses -q
```

Expected: pass.

- [ ] **Step 2: Run full tests**

```bash
uv run pytest -q
```

Expected: pass; no skipped/failing tests hidden.

- [ ] **Step 3: Run lint**

```bash
uv run ruff check .
```

Expected: pass.

- [ ] **Step 4: Run type check**

```bash
uv run mypy .
```

Expected: pass.

- [ ] **Step 5: Check migrations**

```bash
uv run python manage.py makemigrations --check
```

Expected: no changes detected.

---

## Acceptance Criteria Per Unit

1. **Model/import unit**
   - `AW_DZIV` active rows import as `AddressApartment` linked to parent `AddressEntry` by `VKUR_CD`.
   - Deleted/non-active `AW_DZIV` rows are ignored.

2. **Command/download unit**
   - `import_addresses` with no file args downloads configured/default URLs.
   - Local file args override downloaded files.
   - Download failure records failed run and does not clear old index.

3. **Safety unit**
   - Suspicious drop above configured threshold fails run.
   - Failed run leaves old groups/buildings/apartments intact.

4. **Schedule unit**
   - Migration creates weekly `address-vzd-weekly-import` schedule.
   - Task skips without region codes.
   - Task imports with configured region codes.

5. **Autocomplete unit**
   - `group=<id>` still returns buildings.
   - `building=<entry_id>` returns apartments.
   - Selecting an apartment sets the plain text input value only.

6. **Admin/docs unit**
   - Staff can view read-only import runs in Django admin.
   - Docs and `.env.example` describe schedule, URLs, failure behavior, and `AW_DZIV`.

## Documentation Scope

- `docs/address-autocomplete.md`: operational user-facing doc.
- `.env.example`: deploy/operator config keys.
- `AGENTS.md`: status memory after verified implementation.

## Notes for Implementers

- Do not commit unless the user explicitly asks.
- Use `uv run` for all Python commands.
- Do not call real data.gov.lv during tests.
- Do not persist VZD codes on registration/guardian/member models.
- If generated migrations differ in numbering because local branch changed, keep dependencies correct and update this plan's migration names accordingly.

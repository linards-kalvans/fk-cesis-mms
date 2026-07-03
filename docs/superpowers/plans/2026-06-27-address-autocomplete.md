# Address Autocomplete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build local VZD-powered, assist-only address autocomplete for both parent registration address fields.

**Architecture:** Create a dedicated `apps/addresses` Django app that owns VZD CSV import, indexed address group/entry storage, search ranking, and a JSON endpoint. Registration forms only add progressive-enhancement hooks and a vanilla JS widget; existing address fields remain plain text and continue accepting manual input.

**Tech Stack:** Python 3.12, Django 5, Django ORM, PostgreSQL/SQLite-compatible tests, vanilla JavaScript, pytest/pytest-django, uv, ruff, mypy.

---

## Source Documents

- Design spec: `docs/superpowers/specs/2026-06-27-address-autocomplete-design.md`
- Current registration form: `apps/registrations/forms.py`
- Current address-copy JS location: `templates/registrations/application_workspace.html`, `templates/registrations/new_registration.html`
- Current static JS style: `static/js/wizard.js`, `static/js/async_upload.js`

## File Structure

### Create

- `apps/addresses/__init__.py` — package marker.
- `apps/addresses/apps.py` — `AddressesConfig`.
- `apps/addresses/models.py` — `AddressImportRun`, `AddressGroup`, `AddressEntry`.
- `apps/addresses/services.py` — normalization, CSV import service, search service.
- `apps/addresses/views.py` — authenticated autocomplete JSON endpoint.
- `apps/addresses/urls.py` — app URL routes.
- `apps/addresses/management/__init__.py` — package marker.
- `apps/addresses/management/commands/__init__.py` — package marker.
- `apps/addresses/management/commands/import_addresses.py` — local-file import command.
- `apps/addresses/migrations/0001_initial.py` — generated migration.
- `static/js/address_autocomplete.js` — progressive-enhancement dropdown.
- `docs/address-autocomplete.md` — operator/import note and VZD attribution.
- `tests/addresses/__init__.py` — test package marker.
- `tests/addresses/test_models.py` — model basics.
- `tests/addresses/test_import_addresses.py` — parser/import behavior.
- `tests/addresses/test_search.py` — grouped search behavior.
- `tests/addresses/test_autocomplete_view.py` — endpoint behavior/security.
- `tests/registrations/test_address_autocomplete_hooks.py` — registration form/template hooks.

### Modify

- `fk_cesis_mms/settings.py` — add `apps.addresses`; parse `ADDRESS_AUTOCOMPLETE_REGION_CODES`.
- `fk_cesis_mms/urls.py` — include `apps.addresses.urls`.
- `apps/registrations/forms.py` — add autocomplete attributes to `guardian_declared_address` and `member_actual_address`.
- `templates/registrations/application_workspace.html` — load `address_autocomplete.js`.
- `templates/registrations/new_registration.html` — load `address_autocomplete.js`.
- `.env.example` — document `ADDRESS_AUTOCOMPLETE_REGION_CODES`.

---

## Task 1: App Scaffold and Models

**Files:**
- Create: `apps/addresses/__init__.py`
- Create: `apps/addresses/apps.py`
- Create: `apps/addresses/models.py`
- Create: `tests/addresses/__init__.py`
- Create: `tests/addresses/test_models.py`
- Modify: `fk_cesis_mms/settings.py`
- Migration: `apps/addresses/migrations/0001_initial.py`

- [ ] **Step 1: Write failing model/app tests**

Create `tests/addresses/test_models.py` with tests for choices, string output, and app availability.

Expected behaviors:

```python
import pytest
from django.apps import apps

from apps.addresses.models import AddressEntry, AddressGroup, AddressImportRun


@pytest.mark.django_db
def test_addresses_app_is_installed():
    assert apps.get_app_config("addresses").name == "apps.addresses"


@pytest.mark.django_db
def test_import_run_str_includes_source_and_status():
    run = AddressImportRun.objects.create(source="vzd_varis", status=AddressImportRun.Status.SUCCEEDED)

    assert str(run) == "vzd_varis: succeeded"


@pytest.mark.django_db
def test_address_group_str_returns_label():
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
    entry = AddressEntry.objects.create(
        vzd_code="400",
        label="Raiņa iela 1, Cēsis, Cēsu nov.",
        normalized_label="raina iela 1 cesis cesu nov",
        postal_code="LV-4101",
        region_code="300",
        region_name="Cēsu nov.",
    )

    assert str(entry) == "Raiņa iela 1, Cēsis, Cēsu nov."
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run pytest tests/addresses/test_models.py -q
```

Expected: FAIL because `apps.addresses` does not exist.

- [ ] **Step 3: Implement app + models**

Create `apps/addresses/apps.py`:

```python
from django.apps import AppConfig


class AddressesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.addresses"
```

Create `apps/addresses/models.py` with:

- `AddressImportRun.Status` choices: `running`, `succeeded`, `failed`.
- `AddressImportRun.__str__` returns `f"{self.source}: {self.status}"`.
- `AddressGroup` fields from spec.
- `AddressEntry` fields from spec.
- Indexes on normalized/search fields.

Modify `fk_cesis_mms/settings.py` to include `apps.addresses` in `INSTALLED_APPS`.

- [ ] **Step 4: Generate migration and run model tests**

Run:

```bash
uv run python manage.py makemigrations addresses
uv run pytest tests/addresses/test_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task 1**

```bash
git add apps/addresses fk_cesis_mms/settings.py tests/addresses/test_models.py
git commit -m "feat(addresses): add address index models"
```

---

## Task 2: CSV Parser and Import Service

**Files:**
- Create/Modify: `apps/addresses/services.py`
- Create: `apps/addresses/management/commands/import_addresses.py`
- Test: `tests/addresses/test_import_addresses.py`

- [ ] **Step 1: Write failing import tests**

Create tests with temp CSV files encoded as `ISO-8859-1` and one UTF-8 BOM fixture matching current downloaded VZD files. Use minimal VZD-like columns:

```python
from pathlib import Path

import pytest

from apps.addresses.models import AddressEntry, AddressGroup, AddressImportRun
from apps.addresses.services import VzdAddressFiles, import_vzd_addresses, normalize_address_query


def write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_bytes((header + "\n" + "\n".join(rows) + "\n").encode("ISO-8859-1"))
    return path


@pytest.fixture
def vzd_files(tmp_path):
    novads = write_csv(tmp_path / "AW_NOVADS.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", ["300,EKS,Cēsu nov.,"])
    pagasts = write_csv(tmp_path / "AW_PAGASTS.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", [])
    pilseta = write_csv(tmp_path / "AW_PILSETA.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", ["200,EKS,Cēsis,300"])
    ciems = write_csv(tmp_path / "AW_CIEMS.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", [])
    iela = write_csv(tmp_path / "AW_IELA.CSV", "KODS,STATUSS,NOSAUKUMS,VKUR_CD", ["100,EKS,Raiņa iela,200"])
    eka = write_csv(
        tmp_path / "AW_EKA.CSV",
        "KODS,STATUSS,VKUR_CD,NOSAUKUMS,STD,ATRIB,KOORD_X,KOORD_Y,DD_N,DD_E",
        [
            "401,EKS,100,1,\"Raiņa iela 1, Cēsis, Cēsu nov.\",LV-4101,,,,",
            "402,EKS,100,2,\"Raiņa iela 2, Cēsis, Cēsu nov.\",LV-4101,,,,",
            "403,DEL,100,3,\"Raiņa iela 3, Cēsis, Cēsu nov.\",LV-4101,,,,",
        ],
    )
    return VzdAddressFiles(novads=novads, pagasts=pagasts, pilseta=pilseta, ciems=ciems, iela=iela, eka=eka)


@pytest.mark.django_db
def test_import_vzd_addresses_creates_group_and_active_entries(vzd_files):
    run = import_vzd_addresses(vzd_files, region_codes=["300"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.group_count == 1
    assert run.entry_count == 2
    assert AddressGroup.objects.get().label == "Raiņa iela, Cēsis"
    assert list(AddressEntry.objects.order_by("vzd_code").values_list("vzd_code", flat=True)) == ["401", "402"]


@pytest.mark.django_db
def test_import_vzd_addresses_excludes_regions_not_configured(vzd_files):
    run = import_vzd_addresses(vzd_files, region_codes=["999"])

    assert run.status == AddressImportRun.Status.SUCCEEDED
    assert run.group_count == 0
    assert run.entry_count == 0
    assert AddressEntry.objects.count() == 0


def test_normalize_address_query_collapses_case_spaces_and_diacritics():
    assert normalize_address_query("  Raiņa   IELA  ") == "raina iela"
```

- [ ] **Step 2: Run import tests to verify RED**

```bash
uv run pytest tests/addresses/test_import_addresses.py -q
```

Expected: FAIL because services do not exist.

- [ ] **Step 3: Implement import service**

Implement in `apps/addresses/services.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VzdAddressFiles:
    novads: Path
    pagasts: Path
    pilseta: Path
    ciems: Path
    iela: Path
    eka: Path
```

Implementation requirements:

- Read CSV with UTF-8 BOM support first, `ISO-8859-1` fallback, and `delimiter=","`.
- Normalize with Unicode decomposition, strip combining marks, lowercase, collapse whitespace.
- Build parent maps from novads/pagasts/pilseta/ciems/iela.
- Region code is top-level novads code for current MVP.
- Import only `AW_EKA.STATUSS == "EKS"`.
- Clear/replace `AddressGroup` and `AddressEntry` only after parsing succeeds.
- Record successful/failed `AddressImportRun`.

- [ ] **Step 4: Implement command wrapper**

`import_addresses.py` must accept required path args:

- `--novads`
- `--pagasts`
- `--pilseta`
- `--ciems`
- `--iela`
- `--eka`
- repeated `--region-code`

It calls `import_vzd_addresses(...)` and prints `Imported N address groups and M address entries.`

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/addresses/test_import_addresses.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit task 2**

```bash
git add apps/addresses/services.py apps/addresses/management tests/addresses/test_import_addresses.py
git commit -m "feat(addresses): import VZD address data"
```

---

## Task 3: Grouped Search Service

**Files:**
- Modify: `apps/addresses/services.py`
- Test: `tests/addresses/test_search.py`

- [ ] **Step 1: Write failing search tests**

Create `tests/addresses/test_search.py`:

```python
import pytest

from apps.addresses.models import AddressEntry, AddressGroup
from apps.addresses.services import search_addresses


@pytest.fixture
def raina_group(db):
    group = AddressGroup.objects.create(
        label="Raiņa iela, Cēsis",
        normalized_label="raina iela cesis",
        street_code="100",
        street_name="Raiņa iela",
        locality_code="200",
        locality_name="Cēsis",
        region_code="300",
        region_name="Cēsu nov.",
        entry_count=3,
    )
    for number in ("1", "2", "3"):
        AddressEntry.objects.create(
            vzd_code=f"40{number}",
            label=f"Raiņa iela {number}, Cēsis, Cēsu nov.",
            normalized_label=f"raina iela {number} cesis cesu nov",
            group=group,
            postal_code="LV-4101",
            region_code="300",
            region_name="Cēsu nov.",
        )
    return group


@pytest.mark.django_db
def test_search_returns_group_before_house_number_spam(raina_group):
    results = search_addresses("Raiņa")

    assert results[0] == {"kind": "group", "id": str(raina_group.id), "label": "Raiņa iela, Cēsis", "hint": "Cēsu nov."}
    assert all(result["kind"] == "group" for result in results)


@pytest.mark.django_db
def test_search_with_group_returns_building_entries(raina_group):
    results = search_addresses("Raiņa iela, Cēsis", group_id=raina_group.id)

    assert [result["kind"] for result in results] == ["address", "address", "address"]
    assert results[0]["label"] == "Raiņa iela 1, Cēsis, Cēsu nov."
    assert results[0]["hint"] == "LV-4101"


@pytest.mark.django_db
def test_search_requires_three_characters(raina_group):
    assert search_addresses("Ra") == []


@pytest.mark.django_db
def test_search_limits_results(db):
    for index in range(12):
        AddressGroup.objects.create(
            label=f"Raiņa iela, Vieta {index}",
            normalized_label=f"raina iela vieta {index}",
            street_code=str(index),
            street_name="Raiņa iela",
            locality_code=f"2{index}",
            locality_name=f"Vieta {index}",
            region_code="300",
            region_name="Cēsu nov.",
        )

    assert len(search_addresses("Raiņa", limit=10)) == 10
```

- [ ] **Step 2: Run search tests to verify RED**

```bash
uv run pytest tests/addresses/test_search.py -q
```

Expected: FAIL because `search_addresses` is missing or incomplete.

- [ ] **Step 3: Implement `search_addresses`**

Rules:

- Trim query; if normalized length < 3 return `[]`.
- If `group_id` is provided, query `AddressEntry` for that group.
- Without group, query `AddressGroup` first.
- Prefix matches should sort before substring matches.
- Return dicts with `kind`, `id`, `label`, `hint`.
- `hint` for groups is `region_name`; for entries is `postal_code` or `region_name`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/addresses/test_search.py tests/addresses/test_import_addresses.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task 3**

```bash
git add apps/addresses/services.py tests/addresses/test_search.py
git commit -m "feat(addresses): add grouped address search"
```

---

## Task 4: Autocomplete Endpoint

**Files:**
- Create: `apps/addresses/views.py`
- Create: `apps/addresses/urls.py`
- Modify: `fk_cesis_mms/urls.py`
- Test: `tests/addresses/test_autocomplete_view.py`

- [ ] **Step 1: Write failing endpoint tests**

Use existing `verified_client` fixture for authenticated parent access.

Tests:

```python
import pytest
from django.urls import reverse

from apps.addresses.models import AddressGroup


@pytest.mark.django_db
def test_autocomplete_requires_authenticated_parent(client):
    response = client.get(reverse("addresses:autocomplete"), {"q": "Raiņa"})

    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_autocomplete_returns_empty_for_short_query(verified_client):
    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "Ra"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.django_db
def test_autocomplete_returns_results(verified_client):
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

    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "Raiņa"})

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"kind": "group", "id": str(group.id), "label": "Raiņa iela, Cēsis", "hint": "Cēsu nov."}]
    }


@pytest.mark.django_db
def test_autocomplete_empty_dataset_returns_empty(verified_client):
    response = verified_client.get(reverse("addresses:autocomplete"), {"q": "Raiņa"})

    assert response.status_code == 200
    assert response.json() == {"results": []}
```

- [ ] **Step 2: Run endpoint tests to verify RED**

```bash
uv run pytest tests/addresses/test_autocomplete_view.py -q
```

Expected: FAIL because route does not exist.

- [ ] **Step 3: Implement view and URLs**

`apps/addresses/views.py`:

- decorate with `login_required` or equivalent existing parent auth pattern;
- read `q` and optional `group`;
- parse `group` as int or ignore invalid values as `None`;
- return `JsonResponse({"results": search_addresses(...)})`.

`apps/addresses/urls.py`:

```python
from django.urls import path

from apps.addresses import views

app_name = "addresses"

urlpatterns = [path("autocomplete/", views.autocomplete, name="autocomplete")]
```

Project URLs:

```python
path("addresses/", include("apps.addresses.urls"))
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/addresses/test_autocomplete_view.py tests/addresses/test_search.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit task 4**

```bash
git add apps/addresses/views.py apps/addresses/urls.py fk_cesis_mms/urls.py tests/addresses/test_autocomplete_view.py
git commit -m "feat(addresses): expose autocomplete endpoint"
```

---

## Task 5: Registration Hooks and JavaScript Widget

**Files:**
- Modify: `apps/registrations/forms.py`
- Modify: `templates/registrations/application_workspace.html`
- Modify: `templates/registrations/new_registration.html`
- Create: `static/js/address_autocomplete.js`
- Test: `tests/registrations/test_address_autocomplete_hooks.py`

- [ ] **Step 1: Write failing hook/template tests**

Tests should assert:

- `id_guardian_declared_address` has `data-address-autocomplete="1"`.
- `id_member_actual_address` has `data-address-autocomplete="1"`.
- rendered workspace includes `address_autocomplete.js`.
- rendered new-registration page includes `address_autocomplete.js`.
- fields remain normal text inputs, not required to carry hidden VZD code fields.

Use existing registration fixtures and template tests as patterns.

- [ ] **Step 2: Run hook tests to verify RED**

```bash
uv run pytest tests/registrations/test_address_autocomplete_hooks.py -q
```

Expected: FAIL because attrs/JS are absent.

- [ ] **Step 3: Add form widget attrs**

In `RegistrationApplicationForm.__init__`, add for both fields:

```python
for _address_field in ("guardian_declared_address", "member_actual_address"):
    attrs = self.fields[_address_field].widget.attrs
    attrs["data-address-autocomplete"] = "1"
    attrs["autocomplete"] = "street-address"
    attrs["aria-autocomplete"] = "list"
```

Do not remove existing `data-sync-address-for` on `member_actual_address`.

- [ ] **Step 4: Add JS file**

`static/js/address_autocomplete.js` must:

- attach to `[data-address-autocomplete="1"]`;
- require 3+ chars;
- debounce fetch;
- call `/addresses/autocomplete/?q=...` and include `group=...` after group selection;
- render a dropdown after the input;
- support group selection by setting input value to group label and preserving active group;
- support address selection by setting input value to address label and closing dropdown;
- support Escape to close;
- degrade silently if fetch fails, while showing `Neizdevās ielādēt adreses. Varat ievadīt manuāli.` in the dropdown when possible.

- [ ] **Step 5: Include JS in templates**

Add static script include to both registration templates using existing static-loading conventions.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/registrations/test_address_autocomplete_hooks.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit task 5**

```bash
git add apps/registrations/forms.py templates/registrations/application_workspace.html templates/registrations/new_registration.html static/js/address_autocomplete.js tests/registrations/test_address_autocomplete_hooks.py
git commit -m "feat(registrations): add address autocomplete widget"
```

---

## Task 6: Config and Operator Documentation

**Files:**
- Modify: `.env.example`
- Create: `docs/address-autocomplete.md`
- Modify: `docs/milestones.md` only if implementation fully lands and status needs tracking.
- Test: targeted docs/config checks if existing tests cover `.env.example` or docs contract.

- [ ] **Step 1: Write or update config/doc tests if existing project has a contract**

Search existing tests for `.env.example` or docs contract. If present, add `ADDRESS_AUTOCOMPLETE_REGION_CODES`. If no such tests exist, no new docs-only test is required.

- [ ] **Step 2: Update `.env.example`**

Add:

```env
# VZD address autocomplete region/locality object codes, comma-separated.
# Example values must be replaced with confirmed production Cēsis-area VZD codes.
ADDRESS_AUTOCOMPLETE_REGION_CODES=
```

- [ ] **Step 3: Add operator doc**

`docs/address-autocomplete.md` must include:

- VZD dataset URL: https://data.gov.lv/dati/lv/dataset/varis-atvertie-dati
- License: CC-BY-4.0
- Imported files: `AW_NOVADS`, `AW_PAGASTS`, `AW_PILSETA`, `AW_CIEMS`, `AW_IELA`, `AW_EKA`
- Example command with local CSV paths
- Scope limitations: no apartments, no hard validation, no scheduled refresh
- Failure behavior: form remains manual

- [ ] **Step 4: Run docs/config tests or skip explicitly if none exist**

If docs/config tests exist:

```bash
uv run pytest <relevant-test-file> -q
```

Expected: PASS.

- [ ] **Step 5: Commit task 6**

```bash
git add .env.example docs/address-autocomplete.md docs/milestones.md
git commit -m "docs(addresses): document VZD address import"
```

---

## Task 7: Full Verification and Review

**Files:** all changed files from Tasks 1–6.

- [ ] **Step 1: Run targeted address tests**

```bash
uv run pytest tests/addresses tests/registrations/test_address_autocomplete_hooks.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

```bash
uv run pytest -q
```

Expected: PASS. No skipped/failing tests hidden.

- [ ] **Step 3: Run lint**

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 4: Run types**

```bash
uv run mypy .
```

Expected: PASS.

- [ ] **Step 5: Run migration check**

```bash
uv run python manage.py makemigrations --check
```

Expected: PASS, no uncommitted model changes.

- [ ] **Step 6: Final self-review checklist**

Confirm:

- autocomplete is assist-only;
- no VZD code persisted on registration/member/guardian;
- group search prevents house-number spam;
- both address fields enhanced;
- no external provider called during typing;
- no implementation scope creep: no `AW_DZIV`, no scheduled refresh, no admin config UI.

---

## Plan Self-Review

### Spec coverage

Covered:

- official VZD local import: Tasks 2 and 6;
- configurable regions: Task 2 and 6;
- `AW_EKA` only: Task 2;
- both address fields: Task 5;
- assist-only/manual fallback: Task 5 and Task 7 checklist;
- no VZD code persistence: Task 5 and Task 7 checklist;
- grouped search: Task 3;
- endpoint: Task 4;
- tests: Tasks 1–5 and 7;
- docs/attribution: Task 6.

### Placeholder scan

No `TBD`, `TODO`, or unresolved implementation placeholders. Example region codes are explicitly marked as examples and not production values.

### Type consistency

Names are consistent across tasks: `AddressImportRun`, `AddressGroup`, `AddressEntry`, `VzdAddressFiles`, `normalize_address_query`, `import_vzd_addresses`, `search_addresses`, `addresses:autocomplete`.

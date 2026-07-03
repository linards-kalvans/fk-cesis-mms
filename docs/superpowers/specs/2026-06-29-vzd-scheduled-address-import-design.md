# VZD Scheduled Address Import Design

## Goal

Add an automatic weekly refresh for the local VZD address autocomplete index, using official data.gov.lv VARIS CSV resources, while keeping the registration address fields assist-only and stored as plain text.

## Problem

The current address autocomplete index is refreshed manually with local CSV file paths. That creates operational drift: address suggestions become stale unless someone downloads and imports the VZD files by hand.

The existing autocomplete slice also imports building / land-unit addresses only (`AW_EKA`). Users who live in apartment buildings should be able to select apartment / unit addresses from `AW_DZIV`, but only after choosing the building first so suggestions stay usable.

## Confirmed Requirements

- Download official VZD VARIS open data CSV files from data.gov.lv during scheduled import.
- Configure every source URL through env vars, with defaults matching the current data.gov.lv download URLs as of 2026-06-29.
- Import these seven files: `AW_NOVADS`, `AW_PAGASTS`, `AW_PILSETA`, `AW_CIEMS`, `AW_IELA`, `AW_EKA`, `AW_DZIV`.
- Run scheduled import weekly, default Sunday 01:00 Europe/Riga.
- Make weekday and hour configurable.
- Run automatically when region codes are configured. No separate enabled flag.
- Keep old address index when download, parsing, validation, or import fails.
- Record failed import attempts in `AddressImportRun` and logs.
- Add a configurable suspicious-drop threshold, default 50%, compared to the latest successful import.
- Use current atomic replace behavior. Do not add snapshot/staging tables.
- Keep manual command usable with no args: default to downloading URLs.
- Keep local file flags as overrides for tests and offline recovery.
- Keep `--region-code` support.
- Add apartment selection as building-first flow.
- Persist final selected address text only. Do not store VZD object codes on registration, guardian, or member records.
- Add Django admin visibility for import runs.

## Out of Scope

- Hard validation that a typed address must exist in VZD data.
- Persisting VZD codes on business-domain records.
- Map/geocoding UI.
- Snapshot/staging import tables.
- Staff email alerts for failed imports.
- Admin browsing of all groups, buildings, or apartments.
- Importing historical CSV files.
- Reading VZD metadata JSON resources.

## Data Source Defaults

The app should provide defaults for these env-configured URLs:

```env
ADDRESS_IMPORT_AW_NOVADS_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/c62c60bb-58d4-4f26-82c0-5b630769f9d1/download/aw_novads.csv
ADDRESS_IMPORT_AW_PAGASTS_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/6ba8c905-27a1-443a-b9c6-256a0777425b/download/aw_pagasts.csv
ADDRESS_IMPORT_AW_PILSETA_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/ee02baa4-2bc3-4f77-a6cb-5427a3e9befe/download/aw_pilseta.csv
ADDRESS_IMPORT_AW_CIEMS_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/0d3810f4-1ac0-4fba-8b10-0188084a361b/download/aw_ciems.csv
ADDRESS_IMPORT_AW_IELA_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/3c4ab802-76cf-433c-9c1c-89215e28d833/download/aw_iela.csv
ADDRESS_IMPORT_AW_EKA_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/a510737a-18ce-400f-ad4b-04fce5228272/download/aw_eka.csv
ADDRESS_IMPORT_AW_DZIV_URL=https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/b83be373-f444-4f50-9b98-28741845325e/download/aw_dziv.csv
```

These defaults are not secrets. Env overrides exist because data.gov.lv resource URLs may change.

## Recommended Architecture

Reuse the existing `apps.addresses` app and add only the missing pieces.

```text
django-q weekly Schedule
  ↓
apps.addresses.tasks.import_vzd_addresses_from_urls()
  ↓
download configured CSV URLs to a temporary directory
  ↓
apps.addresses.services.import_vzd_addresses(...)
  ↓
atomic replace of local search index
  ↓
GET /addresses/autocomplete/
  ↓
existing parent address text inputs
```

Why:

- The app already has an isolated address-import and search boundary.
- The project already uses django-q schedules for billing and audit jobs.
- Atomic replace already prevents half-empty search indexes on failed imports.
- Staging tables would add complexity before we have evidence the current import is too slow or disruptive.

## Data Model Changes

### Existing models

Keep:

- `AddressImportRun`
- `AddressGroup`
- `AddressEntry`

`AddressEntry` continues to represent building / land-unit addresses from `AW_EKA`.

### New `AddressApartment`

Add a minimal model for `AW_DZIV` rows:

- `vzd_code`: unique VZD unit code from `AW_DZIV.KODS`;
- `building`: FK to parent `AddressEntry`, resolved from `AW_DZIV.VKUR_CD == AddressEntry.vzd_code`;
- `label`: full `AW_DZIV.STD` address text;
- `normalized_label`: normalized search text;
- `postal_code`: optional `AW_DZIV.ATRIB` value.

Indexes:

- `building, normalized_label` for building-scoped apartment search;
- `normalized_label` for simple lookup and tests.

Apartment rows are search data only. They are not linked to registration, guardian, or member records.

## Import Behavior

### URL download

Add a small downloader using Python stdlib (`urllib.request`) to avoid a new dependency.

Rules:

1. Download each configured CSV URL into a temporary directory.
2. Use short network timeouts.
3. Fail the whole import if any required file cannot be downloaded.
4. Do not alter current address index on download failure.
5. Redact long URLs/error text in stored `AddressImportRun.error_message` if needed; no PII exists in the CSV source URLs.

### Manual command

Change `import_addresses` command behavior:

```bash
uv run python manage.py import_addresses
```

No file args means download configured/default URLs.

Existing local file flags remain supported:

```bash
uv run python manage.py import_addresses \
  --novads /path/to/AW_NOVADS.CSV \
  --pagasts /path/to/AW_PAGASTS.CSV \
  --pilseta /path/to/AW_PILSETA.CSV \
  --ciems /path/to/AW_CIEMS.CSV \
  --iela /path/to/AW_IELA.CSV \
  --eka /path/to/AW_EKA.CSV \
  --dziv /path/to/AW_DZIV.CSV
```

If a file flag is present, it overrides that one downloaded file. This preserves deterministic tests and offline recovery.

`--region-code` stays repeatable and overrides/augments `ADDRESS_AUTOCOMPLETE_REGION_CODES` as today.

### Atomic replacement

Keep current replacement strategy:

1. Parse rows.
2. Build groups, buildings, and apartments in memory.
3. Validate counts and suspicious-drop guard before deleting existing search data.
4. Inside one database transaction, delete old search rows and insert new ones.
5. Mark `AddressImportRun` as succeeded only after replacement succeeds.

If any step fails before or during replacement, mark run failed and keep the old index. If the transaction fails, the database rolls back the deletion/inserts.

### Suspicious-drop guard

After parsing and region filtering, compare new total selectable row count to the latest successful run.

Total selectable rows:

```text
building_count + apartment_count
```

Default threshold:

```env
ADDRESS_IMPORT_MAX_DROP_RATIO=0.50
```

Example: if previous success had 10,000 selectable rows and the new import has fewer than 5,000, fail the run and keep the old index.

If there is no previous successful run, skip the drop guard.

## Scheduled Job

Add `apps.addresses.tasks.import_vzd_addresses_from_urls()`.

Behavior:

- If `ADDRESS_AUTOCOMPLETE_REGION_CODES` is empty, log and return without creating a failed import run.
- Otherwise, run the same URL-backed import path as the no-arg management command.
- Let the service record `AddressImportRun` status and counts.
- Catch unexpected exceptions so the job does not crash the qcluster loop; record a failed run when possible.

Add a django-q `Schedule` migration:

- `name`: `address-vzd-weekly-import`
- `func`: `apps.addresses.tasks.import_vzd_addresses_from_urls`
- `schedule_type`: weekly
- `next_run`: configurable local weekday/hour

Settings:

```env
ADDRESS_IMPORT_WEEKDAY=6
ADDRESS_IMPORT_HOUR=1
```

Weekday uses Python convention: Monday `0`, Sunday `6`.

## Autocomplete API and UI

Keep existing endpoint:

```text
GET /addresses/autocomplete/?q=<query>
GET /addresses/autocomplete/?q=<query>&group=<group_id>
```

Add building-scoped apartment query:

```text
GET /addresses/autocomplete/?q=<query>&building=<entry_id>
```

Response shape stays unchanged:

```json
{
  "results": [
    {"kind": "address", "id": "456", "label": "Raiņa iela 12, Cēsis, Cēsu nov.", "hint": "LV-4101"},
    {"kind": "apartment", "id": "789", "label": "Raiņa iela 12-3, Cēsis, Cēsu nov.", "hint": "LV-4101"}
  ]
}
```

UI behavior:

1. User types street/locality and chooses a group.
2. User narrows to a building and chooses a building.
3. If apartments exist for that building, widget continues suggestions scoped to that building.
4. If user chooses an apartment, input value becomes `AW_DZIV.STD` text.
5. If user stops at building, input value remains building address text.
6. Submitting registration stores plain text as today.

No-JS fallback stays a plain text field.

## Admin Visibility

Register `AddressImportRun` in Django admin as read-only.

List/detail should expose:

- `status`
- `source`
- `started_at`
- `finished_at`
- `region_codes`
- `group_count`
- `entry_count`
- `error_message`

Do not register `AddressGroup`, `AddressEntry`, or `AddressApartment` in admin for now. They may be large and are operational search data, not staff workflow records.

## Error Handling

- Download failure: failed run, old index retained.
- CSV parse failure: failed run, old index retained.
- Empty import for configured regions: failed run, old index retained.
- Suspicious drop: failed run, old index retained.
- Database failure during replacement: transaction rollback, failed run when possible.
- Scheduled job with no region codes: skip without failure.

## Security and Privacy

VZD VARIS data is public open data. Parent-entered addresses remain local to this app and are not sent to external autocomplete vendors.

The scheduled import must not log parent-entered address values. Import logs may include public VZD resource labels and counts.

## Testing Strategy

Use pytest and existing address fixtures/patterns.

Test areas:

- Settings defaults expose all seven URL values and schedule knobs.
- Downloader writes files and handles HTTP/network failures without touching old index.
- No-arg `import_addresses` downloads default URLs.
- Local file flags override downloaded files.
- `--dziv` works with local file imports.
- `import_vzd_addresses` imports `AW_DZIV` rows and links them to parent `AW_EKA` buildings by `VKUR_CD`.
- Apartment rows outside configured regions are excluded through their parent building.
- Apartment autocomplete returns `kind=apartment` for `building=<id>`.
- Suspicious-drop guard blocks replacement and records failure.
- No previous successful import means no drop guard.
- Weekly django-q schedule migration creates `address-vzd-weekly-import`.
- `AddressImportRun` admin is read-only and visible.

Do not hit real data.gov.lv in tests. Mock URL download.

## Documentation Scope

Update:

- `docs/address-autocomplete.md` with scheduled import, URL defaults, `AW_DZIV`, and weekly schedule.
- `.env.example` with URL override keys, weekday/hour, drop threshold.
- `AGENTS.md` current-status note if implementation lands as a significant change.

## Acceptance Criteria

- Running `uv run python manage.py import_addresses` downloads configured/default VZD CSVs and refreshes the index.
- Running the same command with local file flags uses those files instead of downloading.
- Weekly django-q schedule exists after migrations and points at the address import task.
- Failed download/import leaves previous `AddressGroup`, `AddressEntry`, and `AddressApartment` rows intact.
- Suspicious count drop beyond configured threshold records failed run and leaves old index intact.
- Apartment rows are selectable only after selecting/querying a parent building.
- Registration still stores only plain text address values.
- Staff can inspect import runs in Django admin.
- Full verification passes: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`.

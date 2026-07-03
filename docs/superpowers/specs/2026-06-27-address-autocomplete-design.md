# Address Autocomplete Design

## Goal

Add assist-only Latvian address autocomplete to the parent registration workflow so guardians can enter addresses faster and with fewer typos, while keeping the current plain-text address fields and non-blocking registration behavior.

## Problem

The registration form currently has two free-text address fields:

- `guardian_declared_address` on the guardian step;
- `member_actual_address` on the member step.

Parents must type full Latvian addresses manually. This creates friction on mobile, increases spelling inconsistency, and makes repeated sibling registrations slower. The feature should improve data entry without turning address entry into a hard registry-validation dependency.

## Confirmed Requirements

- Use official Latvian address open data from the Valsts zemes dienests Valsts adrešu reģistrs dataset.
- Keep autocomplete data local after import; parent keystrokes must not be sent to external vendors.
- Region coverage must be configurable through environment settings, with Cēsis-area coverage as the first deployment target.
- First slice uses building / land-unit addresses only (`AW_EKA`), not apartment / unit addresses (`AW_DZIV`).
- Autocomplete appears on both `guardian_declared_address` and `member_actual_address`.
- Autocomplete is assist-only: users may ignore suggestions and type any non-empty address manually.
- Keep the current persisted registration/guardian/member address fields as plain text. Do not store VZD object codes in the first slice.
- Keep a path open for a later soft-warning mode when typed text does not match imported registry data.
- Import is manual in the first slice. Scheduled refresh is deferred.
- No-JS, empty-data, or failed-endpoint fallback is the current plain text field.
- Grouped search is required: typing a street name should show street/locality groups before individual house numbers.
- Follow-up refinement: villages and other non-city localities with building addresses must be searchable, not only cities/towns with streets. For example, typing `Priekuļi` should return relevant locality/group suggestions.
- Follow-up refinement: building-number search must work in natural orders. For example, `Raiņa iela 12`, `12 Raiņa iela`, and typing `12` after selecting `Raiņa iela, Cēsis` should suggest `Raiņa iela 12, Cēsis` when that building exists.

## Out of Scope

- Hard validation that an address must exist in the VZD register.
- Persisting selected VZD object codes on `Guardian`, `RegistrationApplication`, or `Member`.
- Importing apartment / unit addresses from `AW_DZIV`.
- Scheduled daily or weekly refresh jobs.
- Admin UI for region configuration.
- Map display, geocoding UI, distance checks, or routing.
- Reworking existing address ownership or guardian/member schema.

## Data Source

Official dataset:

- Dataset: Valsts adrešu reģistra atvērtie dati
- URL: https://data.gov.lv/dati/lv/dataset/varis-atvertie-dati
- Publisher: Valsts zemes dienests
- License: CC-BY-4.0
- Update frequency: daily
- Text data format: CSV
- CSV encoding: current downloads are UTF-8 with BOM; metadata may report `ISO-8859-1`, so importer should support both
- CSV delimiter: `,`

Resources used by the first slice:

- `AW_NOVADS.CSV` — municipalities;
- `AW_PAGASTS.CSV` — parishes;
- `AW_PILSETA.CSV` — cities;
- `AW_CIEMS.CSV` — villages and small villages;
- `AW_IELA.CSV` — streets;
- `AW_EKA.CSV` — building and land-unit addresses.

`AW_EKA` columns needed for the first slice:

- `KODS` — VZD object code;
- `STATUSS` — address status (`EKS`, `DEL`, `ERR`);
- `VKUR_CD` — parent object code;
- `NOSAUKUMS` — object name;
- `STD` — full address text;
- `ATRIB` — postal code;
- `KOORD_X`, `KOORD_Y`, `DD_N`, `DD_E` — optional coordinates.

Only `STATUSS = EKS` rows are imported for search.

## Recommended Architecture

Create a dedicated `apps/addresses` app. The registration workflow consumes the app through a JSON endpoint and small progressive-enhancement JavaScript. Address import, indexing, search ranking, and future refresh logic stay isolated from registration domain logic.

```text
data.gov.lv VZD CSV files
  ↓
import_addresses management command
  ↓
AddressImportRun
AddressGroup        # e.g. "Raiņa iela, Cēsis" or "Priekuļi, Priekuļu pag."
AddressEntry        # e.g. "Raiņa iela 12, Cēsis, Cēsu nov."
  ↓
GET /addresses/autocomplete/?q=Raiņa
  ↓
address_autocomplete.js
  ↓
existing guardian/member address text inputs
```

Why this design:

- It avoids external live autocomplete vendors and keeps GDPR posture simple.
- It keeps official address data refreshable without touching registration models.
- It supports grouped search instead of noisy house-number lists.
- It preserves the current submission contract and fallback behavior.
- It gives a clean place for later soft-warning and scheduled refresh work.

## Data Model

### `AddressImportRun`

Tracks each import attempt.

Suggested fields:

- `source`: short label such as `vzd_varis`;
- `started_at`, `finished_at`;
- `status`: `running`, `succeeded`, `failed`;
- `region_codes`: list or comma-separated snapshot of configured region codes;
- `group_count`, `entry_count`;
- `error_message`: redacted operational error text;
- `source_modified_at` or resource metadata snapshot when available.

### `AddressGroup`

Represents a progressive-search grouping such as `Raiņa iela, Cēsis`.

Suggested fields:

- `label`: display text;
- `normalized_label`: normalized search text;
- `street_code`: VZD street object code when the group comes from `AW_IELA`;
- `street_name`;
- `locality_code`;
- `locality_name`;
- `region_code`;
- `region_name`;
- `entry_count`;
- indexes for `normalized_label`, `street_code`, and region fields.

### `AddressEntry`

Represents a selectable building / land-unit address from `AW_EKA`.

Suggested fields:

- `vzd_code`: `AW_EKA.KODS`;
- `label`: `AW_EKA.STD`;
- `normalized_label`: normalized search text;
- `group`: nullable FK to `AddressGroup`;
- `postal_code`: `AW_EKA.ATRIB`;
- `region_code`, `region_name`;
- optional coordinate fields;
- indexes for `normalized_label`, `vzd_code`, `group`, and region fields.

`vzd_code` should be unique within the imported active snapshot.

## Configuration

Environment setting:

```env
ADDRESS_AUTOCOMPLETE_REGION_CODES=123456789,987654321
```

The concrete values are VZD region/locality object codes. The import command may accept overrides:

```bash
uv run python manage.py import_addresses --region-code 123456789 --region-code 987654321
```

The exact Cēsis-area code should be confirmed during implementation with a small fixture or sample import from `AW_NOVADS`/`AW_PILSETA` before documenting the production `.env` value.

## Import Behavior

Command name:

```bash
uv run python manage.py import_addresses
```

Expected behavior:

1. Read or download the configured VZD CSV resources.
2. Parse CSV with UTF-8 BOM support and `ISO-8859-1` fallback, using comma delimiter.
3. Build the hierarchy needed to resolve street/locality/region labels.
4. Filter to configured region codes.
5. Import only active `AW_EKA` rows where `STATUSS = EKS`.
6. Build `AddressGroup` rows for street/locality combinations.
7. Build locality-level `AddressGroup` rows for active `AW_EKA` rows whose parent is a locality rather than a street, so villages without street parents are still searchable.
8. Build `AddressEntry` rows from full `AW_EKA.STD` labels.
9. Record row counts and status in `AddressImportRun`.
10. Avoid leaving the address search endpoint in a half-empty state after a failed import.

The first implementation can use local file paths or stable official URLs. If official URL download is implemented, it must still support local files for deterministic tests and operator fallback.

## Search API

Endpoint:

```text
GET /addresses/autocomplete/?q=<query>
GET /addresses/autocomplete/?q=<query>&group=<group_id>
```

Response shape:

```json
{
  "results": [
    {"kind": "group", "id": "123", "label": "Raiņa iela, Cēsis", "hint": "Cēsu nov."},
    {"kind": "address", "id": "456", "label": "Raiņa iela 12, Cēsis, Cēsu nov.", "hint": "LV-4101"}
  ]
}
```

Rules:

- require at least 3 non-space query characters;
- return at most 10 results;
- normalize case and Latvian diacritics for matching as needed;
- rank exact and prefix matches before substring matches;
- when no `group` is selected, prefer `AddressGroup` results for street-like queries;
- when `group` is selected, return building entries from that group;
- when a query includes a building-number token, search `AddressEntry` rows as well as groups;
- building-number search is order-insensitive: `Raiņa iela 12` and `12 Raiņa iela` should match the same building entry;
- after a group is selected, a trailing number typed after the group label should narrow to matching buildings inside that group;
- do not expose PII or non-public data;
- if no data is imported, return an empty result list, not a server error.

Access should be limited to authenticated parent/admin sessions because the endpoint is only used inside the verified registration workflow and admin/staff contexts. The data is public, but limiting access reduces unnecessary scraping and keeps the endpoint aligned with the app flow.

## Parent UI Behavior

Both address fields get the same progressive-enhancement widget.

Behavior:

- input remains a normal text field;
- after 3+ typed characters, fetch suggestions with debounce;
- dropdown supports mouse and keyboard selection;
- selecting a `group` fills the input with the group label and keeps focus in the field;
- after group selection, suggestions narrow to building addresses under that group;
- if the user types a building number after a selected group label, the widget sends the selected group id and the typed suffix so the endpoint can return matching buildings in that group;
- selecting an `address` fills the full address text;
- user can keep typing manually at any time;
- same-address checkbox continues copying the guardian field value to the member field;
- no-JS, endpoint failure, or no imported data leaves the current form fully usable.

Latvian UI states:

- `Sāciet rakstīt adresi…`
- `Turpiniet rakstīt…`
- `Adreses nav atrastas`
- `Neizdevās ielādēt adreses. Varat ievadīt manuāli.`

## Future Soft-Warning Path

The first slice stores only plain text. To support later soft-warning without redesign:

- keep the search endpoint result shape stable;
- add data attributes to the input when a suggestion is selected, but do not persist them yet;
- keep search service capable of checking whether text has a close exact match;
- later add non-blocking UI copy such as `Adrese nav atrasta adrešu reģistrā. Varat turpināt manuāli.`

Hard validation remains out of scope unless separately approved.

## Privacy and Security

- Parent keystrokes are sent only to this Django app, not external services.
- The local address index contains public VZD address data only.
- No personal IDs, document data, emails, or registration data are copied into the address index.
- The feature does not block submission, so dataset outages or missing addresses do not prevent registration.
- Import errors should avoid logging parent data or secrets.
- VZD attribution and CC-BY-4.0 license should be documented in operator/user-facing docs where appropriate.

## Testing Strategy

Unit tests:

- CSV parser handles UTF-8 BOM, `ISO-8859-1` fallback, comma delimiter, and expected VZD columns.
- Region filtering includes and excludes rows correctly.
- `STATUSS != EKS` rows are excluded.
- Group generation collapses street/locality matches and prevents house-number spam.
- Search normalization handles case and Latvian diacritics where implemented.
- Ranking prefers exact/prefix group matches before substring/building matches.
- Import tests cover locality-level `AW_EKA` parents so villages such as `Priekuļi` are included even when the address has no street parent.
- Search tests cover order-insensitive building-number queries such as `Raiņa iela 12` and `12 Raiņa iela`.

View tests:

- endpoint enforces minimum query length;
- endpoint returns stable JSON shape;
- endpoint limits result count;
- unauthenticated access is rejected or redirected according to the chosen access rule;
- empty dataset returns `{"results": []}`.

Registration/template tests:

- both address fields carry autocomplete hooks;
- existing form labels, required-field gating, and readonly guardian-profile behavior are preserved;
- same-address copy contract is not broken;
- no registration model/schema change is introduced for selected address codes.

Static/JS contract tests:

- autocomplete JS is loaded on registration workspace/new-registration surfaces;
- no-JS fallback leaves plain text inputs usable;
- Latvian UI copy has no English leakage.

## Acceptance Criteria

1. After importing Cēsis-area VZD data, typing `Raiņa` shows group suggestions such as `Raiņa iela, Cēsis` rather than a flat list of `Raiņa iela 1`, `Raiņa iela 2`, etc.
2. Selecting a group fills the field with the group label and narrows subsequent suggestions to building addresses in that group.
3. Selecting a building address fills the existing text field with the full official address string.
4. Both guardian and member address fields support the autocomplete behavior.
5. Users can submit an application with a manually typed address that was not selected from suggestions.
6. If address data is not imported or the endpoint fails, the registration form still works as it does today.
7. No VZD object code is stored on registration, guardian, or member records in the first slice.
8. Parent keystrokes are not sent to Google, OSM/Nominatim, or any other external autocomplete provider.
9. Typing `Priekuļi` returns locality/group suggestions when imported VZD data contains active building addresses under that village/locality.
10. Typing `Raiņa iela 12` returns the matching building address before unrelated group-only results.
11. Typing `12 Raiņa iela` returns the same matching building address.
12. After selecting `Raiņa iela, Cēsis`, typing `12` narrows suggestions to matching building addresses in that selected group.
13. Tests cover import parsing, filtering, grouping, endpoint shape, building-number search, locality-level groups, and registration template hooks.

## Open Implementation Notes

- Confirm exact Cēsis-area VZD object code during implementation from `AW_NOVADS`/`AW_PILSETA` fixture data.
- Decide whether initial import downloads official URLs directly, accepts local files only, or supports both. The design allows both, but tests should use local fixture files.
- If PostgreSQL trigram search is considered later, keep MVP search simple first unless performance tests require it.

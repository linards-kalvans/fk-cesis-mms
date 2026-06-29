# Address autocomplete

The parent registration form provides an assist-only address autocomplete
powered by the official Latvian address register (VZD VARIS open data).

## Data source

- **Dataset:** Valsts adrešu reģistra atvērtie dati
- **URL:** https://data.gov.lv/dati/lv/dataset/varis-atvertie-dati
- **Publisher:** Valsts zemes dienests
- **License:** CC-BY-4.0
- **Update frequency:** daily
- **Format:** CSV, currently downloaded as UTF-8 with BOM; importer falls back to `ISO-8859-1`; delimiter `,`

## Imported files

The importer downloads and indexes the following seven VARIS files:

- `AW_NOVADS.CSV` — municipalities
- `AW_PAGASTS.CSV` — parishes
- `AW_PILSETA.CSV` — cities
- `AW_CIEMS.CSV` — villages and small villages
- `AW_IELA.CSV` — streets
- `AW_EKA.CSV` — buildings and land-unit addresses
- `AW_DZIV.CSV` — apartment / unit addresses, shown only after a building is selected

Only rows with `STATUSS = "EKS"` are indexed. Building rows are attached to a street group when their parent is a street, and to a locality group when their parent is a village, parish, or city without an intervening street. Apartments are linked to their parent building by `AW_DZIV.VKUR_CD == AW_EKA.KODS`.

## Scheduled import

The app registers a weekly django-q job named `address-vzd-weekly-import`.
By default it runs Sunday 01:00 Europe/Riga and downloads the official data.gov.lv VARIS CSV files.

The job runs when `ADDRESS_AUTOCOMPLETE_REGION_CODES` is configured. If no region codes are configured, it skips without creating a failed import run.

Source URLs have built-in defaults and can be overridden with `ADDRESS_IMPORT_AW_*_URL` env vars.

## Import command

With no file arguments, the command downloads the configured/default URLs:

```bash
uv run python manage.py import_addresses --region-code <KODS>
```

You can also provide local CSV paths (any missing file is downloaded instead):

```bash
uv run python manage.py import_addresses \
  --novads /path/to/AW_NOVADS.CSV \
  --pagasts /path/to/AW_PAGASTS.CSV \
  --pilseta /path/to/AW_PILSETA.CSV \
  --ciems /path/to/AW_CIEMS.CSV \
  --iela /path/to/AW_IELA.CSV \
  --eka /path/to/AW_EKA.CSV \
  --dziv /path/to/AW_DZIV.CSV \
  --region-code <KODS>
```

Repeat `--region-code` for each municipality/locality to include. The region
code is the top-level `AW_NOVADS.KODS` value for the target area.

If `--region-code` is omitted, the command uses `ADDRESS_AUTOCOMPLETE_REGION_CODES`
from the environment. Explicit flags override/augment that default.

Set `ADDRESS_AUTOCOMPLETE_REGION_CODES` in `.env`:

```env
ADDRESS_AUTOCOMPLETE_REGION_CODES=123456789,987654321
```

## Scope limits

- Autocomplete is assist-only: parents can always type an address manually.
- No hard validation requires the address to exist in the imported data.
- No VZD object codes are persisted on `RegistrationApplication`, `Guardian`,
  or `Member` records.

## Smoke checks

After importing local VZD data, verify the refinement behavior from a shell:

```bash
uv run python manage.py shell -c "
from apps.addresses.services import search_addresses
print(search_addresses('Priekuļi')[:3])
print(search_addresses('Raiņa iela 12')[:3])
print(search_addresses('12 Raiņa iela')[:3])
"
```

Expected results:

- `Priekuļi` returns a locality group such as `Priekuļi, Priekuļu pag.`.
- `Raiņa iela 12` and `12 Raiņa iela` return the building entry first.

## Failure behavior

If the address index is empty, the endpoint is unreachable, or the typed
address is not found, the registration form falls back to the existing plain
text address inputs. Registration submission is never blocked by the
autocomplete feature.

Failed downloads, parse errors, or imports that produce zero selectable rows
keep the previous index. A suspicious drop greater than
`ADDRESS_IMPORT_MAX_DROP_RATIO` (default `0.50`) also fails the run and keeps
old data. Failed runs are recorded in `AddressImportRun` and visible in Django
admin.

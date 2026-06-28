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

The first slice imports only the following six VARIS files:

- `AW_NOVADS.CSV` — municipalities
- `AW_PAGASTS.CSV` — parishes
- `AW_PILSETA.CSV` — cities
- `AW_CIEMS.CSV` — villages and small villages
- `AW_IELA.CSV` — streets
- `AW_EKA.CSV` — buildings and land-unit addresses

Only `AW_EKA` rows with `STATUSS = "EKS"` are indexed. Building rows are attached to a street group when their parent is a street, and to a locality group when their parent is a village, parish, or city without an intervening street. Apartment / unit rows from `AW_DZIV` are not imported.

## Import command

Download the current CSV files and run:

```bash
uv run python manage.py import_addresses \
  --novads /path/to/AW_NOVADS.CSV \
  --pagasts /path/to/AW_PAGASTS.CSV \
  --pilseta /path/to/AW_PILSETA.CSV \
  --ciems /path/to/AW_CIEMS.CSV \
  --iela /path/to/AW_IELA.CSV \
  --eka /path/to/AW_EKA.CSV \
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

- First slice uses `AW_EKA` only; apartment / unit addresses (`AW_DZIV`) are
  not imported.
- Autocomplete is assist-only: parents can always type an address manually.
- No hard validation requires the address to exist in the imported data.
- No VZD object codes are persisted on `RegistrationApplication`, `Guardian`,
  or `Member` records.
- Refresh is manual in the first slice; scheduled import jobs are deferred.

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

The import command exits with an error if no region codes are configured or if
the CSV files cannot be parsed; it never leaves a half-empty index behind.

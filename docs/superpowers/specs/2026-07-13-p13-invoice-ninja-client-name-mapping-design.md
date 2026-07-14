# P13 Invoice Ninja client name mapping design

Date: 2026-07-13
Status: approved design

## Problem

Invoice Ninja client contacts expect separate first-name and family-name values. MMS currently stores the parent display name as one `Guardian.full_name`, so Invoice Ninja receives the whole parent name as `contacts[0].first_name` and no family name. That weakens client records and invoice presentation.

## Goals

- Store parent first name and family name explicitly on `Guardian`.
- Keep `Guardian.full_name` only as a temporary compatibility mirror during P13 step 1.
- Change parent registration and admin Guardian editing to write separate name fields.
- Map guardian OCR `first_name` and `last_name` into those explicit fields.
- Send Invoice Ninja client contacts with the first-name and family-name fields Invoice Ninja expects.
- Preserve the Guardian/ParentAccount consolidation: no duplicate email or phone source returns.
- Provide a safe migration/backfill path for existing guardians.

## Non-goals

- Do not drop the `Guardian.full_name` column in P13 step 1.
- Do not add a parent self-service profile page.
- Do not change child/member name storage.
- Do not mass-update existing Invoice Ninja clients. Existing clients update only when a future push path touches them or staff corrects them in Invoice Ninja.
- Do not reintroduce `Guardian.email` or `Guardian.phone` columns.

## Chosen approach

Use a two-step mirror migration.

P13 step 1 adds `Guardian.first_name` and `Guardian.family_name`, backfills them from `Guardian.full_name`, and keeps `full_name` as a stored compatibility mirror. All new writes update explicit fields first, then mirror `full_name` from them.

Why: this is safer than a big-bang drop. Current display surfaces can keep reading `full_name`, while registration, OCR, admin, and Invoice Ninja move to explicit fields. A later cleanup can drop the mirror column after the codebase no longer needs it.

## Data model

`Guardian` gains:

- `first_name` — `CharField(max_length=255, blank=True, default="")`
- `family_name` — `CharField(max_length=255, blank=True, default="")`

`full_name` remains stored for compatibility.

Invariant after P13 step 1:

```text
Guardian.full_name == f"{first_name} {family_name}".strip()
```

A tiny model/helper method should centralize mirror construction so services and admin do not duplicate string assembly.

## Migration and backfill

Existing `full_name` values split by whitespace:

- blank value -> `first_name=""`, `family_name=""`
- single token -> `first_name=<token>`, `family_name=""`
- multiple tokens -> `family_name=<last token>`, `first_name=<all earlier tokens joined by a single space>`

Examples:

- `Jānis Kalniņš` -> `Jānis` / `Kalniņš`
- `Anna Marija Ozola` -> `Anna Marija` / `Ozola`

The migration is non-destructive. It must not clear or alter the existing `full_name` mirror beyond making it consistent if implementation chooses to normalize whitespace.

## Registration form and service behavior

Parent registration changes the guardian name UI from one field to two:

- `guardian_first_name` labelled `Vecāka vārds`
- `guardian_family_name` labelled `Vecāka uzvārds`

The old form field `guardian_full_name` is removed from parent-visible sections and submit-required fields.

Service writes that currently update `Guardian.full_name` switch to writing:

- `Guardian.first_name`
- `Guardian.family_name`
- `Guardian.full_name` mirror

Submit validation requires both explicit fields in the same places that required the old full-name field.

## OCR behavior

Guardian identity OCR maps directly into the new fields:

```text
OCR first_name -> guardian_first_name
OCR last_name  -> guardian_family_name
```

Existing source-badge/provenance behavior should continue for the new fields. OCR payload storage remains unchanged.

## Admin behavior

The unified Guardian admin (`Vecāki`) edits:

- `Vārds` -> `first_name`
- `Uzvārds` -> `family_name`

It shows the derived full name read-only. Saving through admin updates the `full_name` mirror from explicit fields. Email and phone remain ParentAccount-owned proxies.

## Display behavior

Existing parent/admin display surfaces may keep reading `guardian.full_name` during P13 step 1. Because the mirror is maintained on writes, visible full-name output remains clear.

Later cleanup can replace these reads with a derived property and drop the column.

## Invoice Ninja behavior

Invoice Ninja client display name may keep using `guardian.full_name`.

Client contact payload changes from whole-name-as-first-name to explicit fields:

```python
"contacts": [
    {
        "first_name": guardian.first_name,
        "last_name": guardian.family_name,
        "email": guardian.email,
    }
]
```

The existing `custom_value1 = guardian.pk` deduplication stays unchanged.

## Error handling and compatibility

- Empty `family_name` is allowed at model level for safe migration, but parent submit requires it for current registrations.
- Existing rows with ambiguous names are backfilled deterministically; staff can correct them in Guardian admin.
- If an old or test-built Guardian has explicit fields empty but `full_name` set, display remains correct through the mirror until data is corrected.

## Tests

- Migration/backfill split rules, including Latvian names, multi-token first names, single-token names, and blank names.
- Guardian mirror helper/model behavior builds `full_name` from explicit fields.
- Registration form renders `guardian_first_name` and `guardian_family_name`, and does not render the old full-name field.
- Draft save updates `Guardian.first_name`, `Guardian.family_name`, and `Guardian.full_name` mirror.
- Submit validation requires both explicit guardian name fields.
- OCR prefill maps `first_name` and `last_name` into the new guardian fields with source labels.
- Guardian admin edits first/family name and keeps the mirror in sync.
- Invoice Ninja client payload sends `contacts[0].first_name` and `contacts[0].last_name` separately.
- Existing display surfaces still show the canonical parent display name.

## Acceptance criteria

- `Guardian` has explicit first-name and family-name fields with a safe backfill from current `full_name`.
- New registration and admin writes use explicit fields and keep `full_name` as a temporary mirror.
- Parent registration shows separate **Vecāka vārds** and **Vecāka uzvārds** fields.
- Guardian OCR fills the explicit fields directly.
- Invoice Ninja client create payload sends separate contact `first_name` and `last_name` values.
- Parent/admin display surfaces still show the full parent name clearly.
- Guardian/ParentAccount consolidation remains intact: email and phone stay account-owned.
- Full verification passes: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`, and `uv run python manage.py makemigrations --check`.

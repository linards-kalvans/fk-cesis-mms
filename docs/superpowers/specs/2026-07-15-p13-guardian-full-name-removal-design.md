# P13 Guardian full-name mirror removal design

Date: 2026-07-15
Status: approved design

## Problem

P13 introduced `Guardian.first_name` and `Guardian.family_name` while keeping `Guardian.full_name` as a temporary compatibility mirror. The P13 data migration has now been applied on all instances, so the mirror column and production compatibility alias can be removed.

## Goals

- Drop the stored `Guardian.full_name` column.
- Use `Guardian.first_name` and `Guardian.family_name` as the only production name storage.
- Add a derived Guardian display-name property for existing UI, exports, billing, DocuSeal, and Invoice Ninja reads.
- Remove production mirror helpers and production `guardian_full_name` form/service alias.
- Rename Guardian/parent context keys from `guardian_full_name` to `guardian_display_name` where those keys are internal email/template context.
- Keep `member_full_name` unchanged.
- Keep a test-only `make_guardian(full_name="...")` shorthand for readable fixtures.

## Non-goals

- No parent self-service profile page.
- No child/member name cleanup.
- No change to `Member.full_name` or registration `member_full_name` storage.
- No live Invoice Ninja mass update.
- No redesign of parent/admin surfaces.
- No removal of historical migration files that still reference past schema state.

## Chosen approach

Perform the cleanup in one small schema/code slice.

A new `members` migration removes `Guardian.full_name`. Production code switches all Guardian-name reads to `guardian.display_name`, which derives the display name from `first_name` and `family_name`. Production writes already write explicit fields, so mirror sync code is deleted. Direct service compatibility for posted `guardian_full_name` is removed because all instances have migrated and the current form no longer emits that key.

Why: the compatibility period is complete, and keeping a stored mirror now creates stale-data risk. A derived property preserves display behavior without duplicate storage.

## Data model

`Guardian` keeps:

- `first_name`
- `family_name`
- `personal_id`
- `address`
- `external_client_id`
- `parent_account`

`Guardian.full_name` is removed from the model and database.

Add:

```python
@property
def display_name(self) -> str:
    return " ".join(part for part in (self.first_name.strip(), self.family_name.strip()) if part)
```

`Guardian.__str__()` returns `display_name or str(pk)`.

## Migration

Create `apps/members/migrations/0011_remove_guardian_full_name.py` with a `RemoveField` operation for `Guardian.full_name`.

Prerequisite: P13 migration `members/0010_guardian_name_parts` has already run on every instance. The user confirmed this before cleanup.

Operational note: dropping the column removes old stored data, so production should still take a normal database backup before applying the migration.

## Production reads

Replace Guardian display reads:

```python
guardian.full_name
```

with:

```python
guardian.display_name
```

Apply to:

- DocuSeal payload builders
- Invoice Ninja client `name`
- billing/admin search fields
- registration accessors and admin search/order comments
- family hub queue/order/title
- exports
- agreement email contexts
- templates that render `guardian.full_name`

Ordering/search that used `full_name` should use `first_name`, `family_name`, and existing email/personal-id fields.

## Production writes

Remove production mirror code:

- `Guardian.sync_full_name()`
- `split_guardian_full_name()` from `apps.members.models`
- `_guardian.sync_full_name()` calls
- `full_name` in `update_fields`
- legacy `guardian_full_name` alias in `create_or_update_draft`

Registration and admin writes store only explicit fields.

## Context keys

Rename Guardian/parent context keys from:

```text
guardian_full_name
```

to:

```text
guardian_display_name
```

This applies only to internal context keys representing the Guardian/parent display name. Do not rename `member_full_name` or model fields for members/applications.

Email templates and tests should read `guardian_display_name` where they need the parent display string.

## Test helpers

Keep `tests.support.make_guardian(full_name="Anna Ozola")` as a test-only shorthand. Since production `split_guardian_full_name()` is removed, the helper owns a tiny local split function using the same last-token rule. This keeps tests readable without keeping production compatibility code.

Production code must not accept `guardian_full_name` as a current form/service input after this cleanup.

## Tests

- Model test: `Guardian.display_name` joins explicit fields and handles blanks.
- Migration test: `members/0011` removes the `full_name` field from the model state.
- Registration tests: current form/save paths use explicit name fields; legacy `guardian_full_name` alias test is removed.
- Admin tests: Guardian admin shows derived display name read-only and edits explicit fields only.
- Integration tests: Invoice Ninja and DocuSeal payloads use `display_name`.
- Email/context tests: `guardian_display_name` replaces `guardian_full_name` for Guardian/parent name context.
- Full grep-based check in tests or verification: no production `guardian_full_name` alias and no `guardian.full_name` reads outside migrations/test helper compatibility.

## Acceptance criteria

- `Guardian.full_name` model field and DB column are removed by migration.
- Production code derives Guardian display names from `first_name` + `family_name`.
- Production code no longer calls `sync_full_name()` or `split_guardian_full_name()`.
- Production `create_or_update_draft()` no longer accepts `guardian_full_name` compatibility alias.
- Internal Guardian/parent context key is `guardian_display_name`, not `guardian_full_name`.
- `make_guardian(full_name="...")` remains available only as a test helper shorthand.
- `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`, and `uv run python manage.py makemigrations --check` pass.

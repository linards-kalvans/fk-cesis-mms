# P7 Slice B — CSV export

*Design spec. Status: approved for planning. Date: 2026-06-13.*

## 1. Problem

Staff have no way to get member/registration data out of the system for offline use (rosters,
accounting, reporting). P7 acceptance items 2, 3, 9, 10 call for staff-only CSV export of members
and registrations/applications, with sensitive fields included "only where explicitly allowed,"
audited, and safe (no public exposure, no accidental PII leakage).

This is **Slice B of P7**. It builds on **Slice A (audit baseline)** — every export is recorded as
an `AuditEvent`. Slice C (admin search/filter + document-UX + sync-health) is separate.

## 2. Approach (chosen)

A small reusable CSV helper in `apps/core`, per-model column sets, and Django **admin changelist
actions**. Two actions per model: a **safe** export (no sensitive fields, all staff) and a
**sensitive** export (safe + sensitive fields, superusers only, flagged in the audit trail).

Rejected: `django-import-export` (export-only need doesn't justify the import/resource/widget
dependency — YAGNI); inline CSV in each action (duplicates BOM/delimiter/injection logic across
four actions — extract the shared helper instead).

## 3. Scope

In scope: the CSV helper, the `DATA_EXPORTED` audit action, safe + sensitive admin export actions on
`MemberAdmin` and `RegistrationApplicationAdmin`, and the column sets below.

Out of scope:
- Export of agreements / billing records (item 2 names members + registrations only).
- Scheduled / automated / API exports.
- XLSX or other formats.
- A custom per-run column picker UI.

## 4. CSV helper — `apps/core/export.py`

```
csv_response(*, filename: str, columns: list[str], rows: Iterable[Sequence]) -> HttpResponse
```

- Content type `text/csv; charset=utf-8`; `Content-Disposition: attachment; filename="<filename>"`.
- Writes a leading **UTF-8 BOM** (`﻿`) so Latvian Excel detects UTF-8.
- `csv.writer(delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")` — semicolon so
  LV/EU Excel splits columns on double-click.
- First row is `columns` (header); subsequent rows are `rows`, each cell passed through a value
  formatter and an injection guard.
- **Value formatter** `_format(value)`: `None → ""`; `datetime.date`/`datetime` → ISO
  (`YYYY-MM-DD` / second-precision); `bool → "jā"/"nē"`; everything else → `str(value)`.
- **CSV formula-injection guard** `_guard(text)`: if a cell's text starts with one of
  `= + - @`, a tab, or a CR, prefix it with a single quote (`'`) so Excel/Sheets won't evaluate a
  user-supplied value (e.g. a malicious registrant name) as a formula. Applied after formatting.
- Data is club-sized (hundreds of rows); a plain `HttpResponse` with the full body is sufficient —
  no streaming.

Filename pattern: `<model>-<YYYYMMDD-HHMM>.csv` (e.g. `members-20260613-1830.csv`), timestamp from
`timezone.localtime()`.

## 5. Audit action

Add `DATA_EXPORTED = "data_exported"` to `apps.core.models.AuditEvent.Action`. This is a
`TextChoices` value only — **no schema migration** (the `action` column is already a `CharField`).
The catalog was designed to extend (Slice A spec §5).

Each export records:
```
record_audit_event(
    action=str(AuditEvent.Action.DATA_EXPORTED),
    actor=request.user, request=request,
    target_type="member" | "registrationapplication",
    target_repr="<model> export (<N> rows)",
    metadata={"count": N, "sensitive": bool, "format": "csv"},
)
```
No `target_id` (a bulk export, not a single row). The `sensitive` flag makes sensitive exports
trivially filterable in the audit viewer.

## 6. Admin actions

On `MemberAdmin` (`apps/members/admin.py`) and `RegistrationApplicationAdmin`
(`apps/registrations/admin.py`):

- `export_csv(self, request, queryset)` — description "Eksportēt CSV (bez sensitīviem datiem)".
  Safe columns. Available to all staff. Records the audit event with `sensitive=False`.
- `export_csv_with_sensitive(self, request, queryset)` — description "Eksportēt CSV ar sensitīviem
  datiem". Safe + sensitive columns. Records `sensitive=True`.
  - **Visibility:** override `get_actions(request)` to remove `export_csv_with_sensitive` when
    `not request.user.is_superuser`, so non-superusers never see it.
  - **Defense in depth:** the action body re-checks `request.user.is_superuser`; if false,
    `self.message_user(..., level=messages.ERROR)` and return without exporting (and without an
    audit row).

Both actions build their rows from the **selected/filtered `queryset`** (staff control scope via
the changelist), using `select_related` for the FK columns (guardian, training_group,
parent_account) to avoid N+1.

Column extraction lives in a small per-model module or inline helper (e.g. `_member_row(obj, *,
sensitive)` / `_application_row(obj, *, sensitive)`), keeping the admin action thin and the column
logic unit-testable without the admin.

## 7. Column sets

**Members** (`apps/members/models.py::Member`)
- Safe: `id, full_name, birth_date, guardian_name (guardian.full_name), training_group (name or "")`.
- + Sensitive: `personal_id, guardian_email (guardian.email), guardian_phone (guardian.phone),
  guardian_address (guardian.address)`.

**Registrations** (`apps/registrations/models.py::RegistrationApplication`, via its read accessors)
- Safe: `id, status, member_full_name, member_birth_date, guardian_name, preferred_payment_mode,
  preferred_agreement_signing, submitted_at, reviewed_at`.
- + Sensitive: `member_personal_id, member_actual_address, guardian_contact_email (→
  parent_account.email), guardian_contact_phone, guardian_pid, guardian_address`.

(Header labels may be human-friendly Latvian strings; the exact label text is an implementation
detail, not a contract.)

## 7a. Security / data handling (acceptance 9)

- Staff-only: actions live in Django admin; no new public URLs.
- Safe-by-default: the default export carries no personal IDs, contact, or addresses.
- Sensitive export is superuser-gated (hidden + defensive check) and audited with `sensitive=True`.
- Formula-injection neutralized (§4).
- No payload logging of the exported rows; the audit row stores only count + flags, never the data.

## 8. Testing

- **Helper:** output starts with the UTF-8 BOM; uses `;` delimiter; header row matches `columns`;
  `_format` renders `None→""`, dates ISO, bools `jā`/`nē`; `_guard` prefixes a leading `=`/`+`/`-`/`@`
  cell with `'`; `Content-Disposition` is an attachment with the filename.
- **Members safe export:** an admin action on a queryset returns a CSV whose header = safe columns,
  values correct, and **no `personal_id`** column present.
- **Members sensitive export:** includes `personal_id` + guardian contact columns.
- **Superuser gating:** `get_actions` omits `export_csv_with_sensitive` for a non-superuser staff
  request; invoking it directly as non-superuser exports nothing and records no audit row.
- **Audit:** each export records a `DATA_EXPORTED` event with `actor`, `metadata["count"]` = row
  count, and `metadata["sensitive"]` matching the action; no row data in the event.
- **Registrations:** safe vs sensitive column sets as above; values via the read accessors.

## 9. Acceptance

1. Staff can export members and registrations/applications to CSV from the admin changelist, scoped
   to their selection/filter.
2. The CSV opens cleanly in Latvian Excel (UTF-8 BOM + `;` delimiter; diacritics + columns intact).
3. The default export contains no sensitive fields; a separate superuser-only action includes them.
4. Every export is recorded as a `DATA_EXPORTED` audit event with actor, row count, and the
   `sensitive` flag — and never the exported data itself.
5. Non-superusers cannot access the sensitive export.
6. User-supplied values cannot execute as spreadsheet formulas (injection guard).
7. Full suite, ruff, and mypy green.

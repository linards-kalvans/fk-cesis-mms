# P17 — Configurable member export templates

*Design spec. Status: approved for implementation. Date: 2026-08-26.*

## 1. Problem

Staff currently rely on two static CSV export actions on the `MemberAdmin` changelist (P7 Slice B). They cannot customise columns, filter by agreement state or training group, switch to XLSX, or save a reusable column configuration for recurring reports. The static actions are also the only export surface — staff who need sensitive data must be superuser, even for templates that only contain safe columns.

P16 (eParaksts agreement upload) is blocked on test credentials and does not block P17.

## 2. Approach (chosen)

**Shared, reusable staff-created export templates** stored in the database, each with an ordered JSON column list and optional agreement-state + training-group filters. Any active staff user can create, edit, delete, and run templates — including templates that reference sensitive columns. The pre-existing P7 static CSV exports remain unchanged, including their superuser-sensitive rule.

Templates are rendered server-side into an in-memory XLSX or CSV response and delivered as a direct download. No files are stored, no background jobs, no provider calls.

Rejected: `django-import-export` (heavy ORM resource/widget layer; YAGNI); background celery/Django-Q jobs (club scale = hundreds of rows); arbitrary query definitions (security risk, hard to validate, leaks ORM internals to staff); guardian-row templates (out of scope — one Member row per export).

## 3. Scope

### In scope

- **`MemberExportTemplate` model** in `apps.members`: `name` (`CharField(max_length=128)`, duplicates allowed), ordered unique JSON column keys, optional JSON agreement-state codes, optional M2M `TrainingGroup` filters (`related_name='export_templates'`), `created_by` (`related_name='member_export_templates_created'`), timestamps. Model-validated in `clean()` via local registry import to avoid circular import.
- **Fixed server-side column allowlist** with stable keys: `member_full_name`, `member_personal_id`, `member_birth_date`, `guardian_name`, `guardian_email`, `guardian_phone`, `guardian_address`, `agreement_state`, `agreement_signed_at`, `training_group_name`.
- **Sensitive keys:** `member_personal_id`, `guardian_email`, `guardian_phone`, `guardian_address`.
- **Registry (`apps/members/exports.py`):** `ColumnSpec` dataclass + `COLUMN_REGISTRY` dict mapping stable key → `{label: str, reader: Callable[[Member], Any], sensitive: bool}`. Pure readers — no ORM calls. Also owns stable-key and state validation/resolution helpers (`VALID_COLUMN_KEYS`, `VALID_AGREEMENT_STATES = {state.value for state in Agreement.State}`, `SENSITIVE_KEYS`). P7 helpers `member_columns`/`member_row` are preserved unchanged.
- **Template service (`apps/members/export_templates.py`):** `RenderedMemberExport` dataclass, `build_template_member_queryset(template)`, `render_member_export(template, fmt)`. Imports the registry from `exports.py`. Owns all query/filter logic.
- **Filter semantics:** agreement-state selected codes are OR, current agreement only; training-group selected groups are OR; both filters AND. Empty filters impose no restriction.
- **N+1 prevention:** filtered query uses `select_related("guardian", "guardian__parent_account", "training_group")` and `prefetch_related(Prefetch("agreements", queryset=Agreement.objects.filter(is_current=True), to_attr="_current_export_agreements"))`. Defensive `.distinct()`.
- **Admin UI:** `MemberExportTemplateAdmin` with custom ordered column picker widget (no separate template file — markup rendered from Python), agreement-state multi-select, training-group multi-select.
- **Run page:** separate admin-wrapped GET/POST page accessible from the template change page via an "Eksportēt" link. CSRF-protected POST, XLSX preselected. No nested HTML forms.
- **Formats:** XLSX (default) and CSV. CSV retains UTF-8 BOM + semicolon delimiter. Both use identical shared cell formatting and spreadsheet-formula injection protection.
- **openpyxl** added as a production dependency.
- **Audit:** `member_export_template_mutated` (create/effective-edit/delete) and `member_export_run` actions. Metadata: `template_id`, `operation` (mutation); or `template_id`, `column_keys`, `agreement_status_filters`, `training_group_ids`, `row_count`, `format`, `sensitive` (run). Never records exported values, bytes, names, personal IDs, email addresses, addresses, output values, template name, or raw target string. All calls use explicit `target_type="member_export_template"`, `target_id=str(template.pk)`, `target_repr="Member export template"`.
- **Permissions:** all template admin permissions are explicit active-staff-only overrides for view/add/change/delete/module access.

### Out of scope

- Guardian-row templates (one Member row per export).
- Scheduled / email-delivered exports.
- Arbitrary / custom formula columns.
- Arbitrary query definitions.
- Output retention (files are streamed, not stored).
- Background jobs.
- Changes to the P7 static CSV exports (unchanged).

## 4. Data model

### `MemberExportTemplate`

| Field | Type | Notes |
|-------|------|-------|
| `name` | `CharField(max_length=128)` | Duplicates allowed. |
| `column_keys` | `JSONField()` | Ordered list of unique valid key strings. Validated in `clean()` (local registry import) and form layer. |
| `agreement_status_filters` | `JSONField(default=list, blank=True)` | Unique list of valid `Agreement.State` code strings. Empty = no filter. Validated in `clean()` and form layer. |
| `training_groups` | `ManyToManyField(TrainingGroup, blank=True, related_name='export_templates')` | OR semantics. Empty = no filter. |
| `created_by` | `FK(User, null=True, on_delete=SET_NULL, related_name='member_export_templates_created')` | Staff user who created the template. Set only on initial creation. Readonly on change. |
| `created_at` | `DateTimeField(auto_now_add=True)` | |
| `updated_at` | `DateTimeField(auto_now=True)` | |

Inherits `TimeStampedModel`. Model lives in `apps.members`.

### `clean()` validation

A local import of `COLUMN_REGISTRY` and `VALID_AGREEMENT_STATES` from `apps.members.exports` avoids a circular import (`models` → `exports` → `models`). Validation rules:

- `column_keys`: must be a non-empty list of strings; all strings must be keys of `COLUMN_REGISTRY`; must be unique.
- `agreement_status_filters`: must be a list of strings; all strings must be valid `Agreement.State` values; must be unique.

Form validation mirrors these rules for good admin feedback.

### `Agreement.State` codes

Valid codes: `generated`, `sent`, `signed`, `void`, `superseded`, `discontinued`. Invalid codes fail validation.

## 5. Column registry

The registry is the canonical source of truth for column definitions. It lives in `apps/members/exports.py` (not in forms). Each entry:

```python
@dataclass(frozen=True)
class ColumnSpec:
    key: str
    label: str          # Latvian label, resolved at render time
    reader: Callable[[Member], Any]
    sensitive: bool
```

Stable keys and their readers:

| Key | Label | Reader | Sensitive |
|-----|-------|--------|-----------|
| `member_full_name` | "Biedra vārds, uzvārds" | `member.full_name` | No |
| `member_personal_id` | "Biedra personas kods" | `member.personal_id` | Yes |
| `member_birth_date` | "Biedra dzimšanas datums" | `member.birth_date` | No |
| `guardian_name` | "Vecāka vārds, uzvārds" | `member.guardian.display_name` (or `""`) | No |
| `guardian_email` | "Vecāka e-pasts" | `member.guardian.email` (or `""`) | Yes |
| `guardian_phone` | "Vecāka tālrunis" | `member.guardian.phone` (or `""`) | Yes |
| `guardian_address` | "Vecāka adrese" | `member.guardian.address` (or `""`) | Yes |
| `agreement_state` | "Līguma statuss" | `current_agreement.get_state_display()` (or `"—"`) | No |
| `agreement_signed_at` | "Līguma parakstīšanas datums" | `current_agreement.signed_at` (or `None`) | No |
| `training_group_name` | "Treniņu grupa" | `member.training_group.name` (or `"—"`) | No |

The `reader` is a pure function — it never makes ORM calls. It receives a `Member` instance and returns a scalar value.

## 6. Filter semantics

### Agreement-state filter

- Selected state codes are **OR** — a member qualifies if their current agreement has ANY of the selected states.
- **Current agreement only** — `is_current=True` agreements. Historical rows never qualify a member for the agreement-state predicate.
- Empty list = no filter (all members pass).
- Invalid codes fail validation and cannot persist or run.

### Training-group filter

- Selected groups are **OR** — a member qualifies if their `training_group` matches ANY of the selected groups.
- Empty list = no filter.

### Combined filters

- When both filters are present, they are **AND** — a member must satisfy both.
- Empty filters impose no restriction.

### Query construction

```python
from django.db.models import Prefetch

qs = Member.objects.select_related(
    "guardian", "guardian__parent_account", "training_group"
).prefetch_related(
    Prefetch(
        "agreements",
        queryset=Agreement.objects.filter(is_current=True),
        to_attr="_current_export_agreements",
    )
)

if template.agreement_status_filters:
    qs = qs.filter(
        agreements__state__in=template.agreement_status_filters,
        agreements__is_current=True,
    ).distinct()

if template.training_groups.exists():
    qs = qs.filter(
        training_group__in=template.training_groups.all()
    ).distinct()
```

`distinct()` is applied defensively to preserve one Member row even when the JOIN would produce duplicates.

## 7. Rendering

### `render_member_export(template, fmt)` → `RenderedMemberExport`

Defined in `apps/members/export_templates.py`. Returns a frozen dataclass:

```python
@dataclass(frozen=True)
class RenderedMemberExport:
    response: HttpResponse
    row_count: int
    sensitive: bool
```

- `fmt` is `"xlsx"` or `"csv"`.
- Columns are emitted in the order stored in `template.column_keys`.
- Cell values: readers produce raw values; `render_member_export` passes raw values to the shared response writers, which call `prepare_export_cell(value)` exactly once per raw cell. Identical for both formats.
- `sensitive` is `True` if any column in `template.column_keys` is marked sensitive.

### CSV

- Identical to the existing P7 CSV: UTF-8 BOM, `;` delimiter, `Content-Disposition: attachment`.
- `csv_response` from `apps/core/export.py` handles the full CSV response.

### XLSX

- Uses `openpyxl` for in-memory workbook creation.
- `xlsx_response` from `apps/core/export.py` handles the full XLSX response: `BytesIO` buffer, `Workbook`, bold header row, bounded column widths (max 40), correct XLSX attachment MIME type (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`), `prepare_export_cell` once per raw cell.
- No files stored on disk.

## 8. Admin UI

### Template change page

- **Column picker widget:** `OrderedColumnKeysWidget` renders all needed markup from Python (no separate template file). Provides an available-column list plus add/remove and move-up/move-down controls. Serializes only selected stable keys to its hidden JSON input. A native multiple-select is insufficient because it does not preserve staff-selected order.
- **Agreement-state filter:** native Django `MultipleChoiceField` with `Agreement.State.choices`.
- **Training-group filter:** native Django `ModelMultipleChoiceField` for `TrainingGroup`.
- **Eksportēt link:** a GET anchor on the change page that navigates to the run page for this template, using `original.pk` (not an assumed `object_id` context variable).

### Run page

- Admin-wrapped GET/POST page at a dedicated admin URL.
- POST is CSRF-protected.
- Format selector with XLSX preselected (radio buttons).
- On valid POST: renders the export and returns a direct download (`HttpResponse` with `Content-Disposition: attachment`).
- On invalid POST (e.g. invalid column keys in the template): renders the admin form errors with no download.
- Missing template: normal admin 404.
- **No nested HTML forms.** The run page is a standalone page, not a form nested inside the change page.
- Run view explicitly checks `has_view_permission(request, template)` after `get_object_or_404`; `admin_view` itself only guards admin-site access.

### Permissions

All template admin permissions are explicit active-staff-only overrides:

```python
class MemberExportTemplateAdmin(ModelAdmin):
    def has_view_permission(self, request, obj=None) -> bool:
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request) -> bool:
        return request.user.is_active and request.user.is_staff

    def has_change_permission(self, request, obj=None) -> bool:
        return request.user.is_active and request.user.is_staff

    def has_delete_permission(self, request, obj=None) -> bool:
        return request.user.is_active and request.user.is_staff

    def has_module_permission(self, request) -> bool:
        return request.user.is_active and request.user.is_staff
```

## 9. Audit

### New `AuditEvent.Action` choices

- `MEMBER_EXPORT_TEMPLATE_MUTATED = "member_export_template_mutated"` — on create, effective edit, and delete.
- `MEMBER_EXPORT_RUN = "member_export_run"` — on successful export runs.

### Metadata

**Mutation:** `{"template_id": int, "operation": "create" | "edit" | "delete"}`

**Run:** `{"template_id": int, "column_keys": [...], "agreement_status_filters": [...], "training_group_ids": [...], "row_count": int, "format": "xlsx" | "csv", "sensitive": bool}`

**Redaction rules:** Never record exported values, bytes, names, personal IDs, email addresses, addresses, output values, template name, or raw target string. Use a generic target representation (`"Member export template"`).

### Effective edit detection

Use `form.changed_data` (not an old database instance loaded after save). Covers `name`, `column_keys`, `agreement_status_filters`, and `training_groups`.

### Bulk delete

Audit every object, then call `super().delete_queryset(request, queryset)` once. Do not call `delete_model` in a loop (that changes Django deletion semantics).

## 10. Security and error handling

| Error condition | Handling |
|----------------|----------|
| Anonymous accessing template admin | Django admin redirects to login (302) |
| Authenticated non-staff accessing template admin | Django admin redirects to login (302) |
| Invalid column keys in template | Model `clean()` + form validation fails; cannot persist or run |
| Invalid agreement state codes | Model `clean()` + form validation fails; cannot persist or run |
| Invalid run POST | Renders admin form errors; no download |
| Missing template for run | Normal admin 404 |
| Audit write failure | Fail-safe (existing helper); no download blocked |

## 11. Why these decisions

1. **JSON column keys, not ORM paths.** Persisting arbitrary ORM paths or free-text query definitions would leak internals, be hard to validate, and create security surface. Stable keys + a server-side registry are validate-able, auditable, and future-proof.

2. **Ordered JSON, not a separate ordering table.** A separate `OrderedColumn` model with a `position` field would require a migration + more boilerplate. JSON arrays preserve order natively and are trivially serialized/deserialized by the widget.

3. **XLSX as default with openpyxl.** Staff expect spreadsheet-native formats. openpyxl is a production dependency that produces clean, styled XLSX without a browser or external service.

4. **Run page, not changelist bulk action.** More than one selected template cannot produce one unambiguous attachment. A separate run page is unambiguous and CSRF-safe.

5. **Current agreement only for state filters.** Historical agreements (superseded, discontinued) should not affect which members appear in a "current signed agreements" report. The filter targets the current agreement.

6. **No background jobs.** Club scale (hundreds of rows) means synchronous rendering and download is fast enough. No queue, no storage, no provider calls.

7. **Explicit staff-only permissions.** The requirement states "any active staff user can create, edit, delete, and run shared templates, including templates containing sensitive values." Explicit permission overrides ensure the behavior is clear and testable, not derived from Django's default superuser rules.

8. **Registry in exports.py, not forms.py.** The registry is a data definition, not a form concern. forms.py owns the widget and form classes; exports.py owns the canonical column definitions and readers.

9. **Model-level `clean()` validation.** Form validation alone is insufficient — the model must also guard against programmatic creation (e.g. from shell or management commands). A local registry import inside `clean()` avoids a circular import with `exports.py`.

10. **Widget renders from Python, no template file.** A separate template file would be an unapproved artifact. The widget's `get_context` method supplies all needed data; rendering logic lives in the widget class.

11. **`form.changed_data` for effective edits.** Loading an old database instance after save is fragile. `form.changed_data` is Django's canonical mechanism for detecting which fields actually changed.

12. **Bulk delete via `super().delete_queryset`.** Calling `delete_model` in a loop changes Django's deletion semantics (signals, cascade behavior). Audit each then delegate once.

## 12. Acceptance

1. `MemberExportTemplate` model exists with `name` (max_length=128), `column_keys`, `agreement_status_filters`, `training_groups` (related_name='export_templates'), `created_by` (related_name='member_export_templates_created'), and timestamps. Inherits `TimeStampedModel`.
2. Model `clean()` validates column keys and agreement states via local registry import.
3. Column registry (`apps/members/exports.py`) contains exactly the ten stable keys, each with a Latvian label, a pure reader, and a sensitive flag. P7 helpers `member_columns`/`member_row` are preserved unchanged.
4. `apps/members/export_templates.py` owns `RenderedMemberExport`, `build_template_member_queryset`, and `render_member_export`. Imports registry from exports.py.
5. Invalid column keys or agreement state codes fail model + form validation and cannot persist or run.
6. Agreement-state filter uses OR semantics on current agreements only; historical rows never qualify.
7. Training-group filter uses OR semantics.
8. When both filters are present, they are AND.
9. Empty filters impose no restriction.
10. The filtered query uses `select_related` + `prefetch_related(Prefetch(..., to_attr="_current_export_agreements"))` with defensive `.distinct()` to prevent N+1 and preserve one Member row.
11. Registry readers are pure — no ORM calls.
12. XLSX (default) and CSV are per-run choices. CSV retains UTF-8 BOM + semicolon. Both use identical shared cell formatting and formula-injection protection.
13. `xlsx_response` uses BytesIO, workbook, bold headers, bounded widths, correct MIME type, `prepare_export_cell` once.
14. No files are stored, no jobs, no provider calls.
15. Admin UI has a column picker widget (available columns + add/remove + move-up/move-down, no template file), agreement-state multi-select, training-group multi-select.
16. A native multiple select is NOT used for column ordering.
17. Template change page supplies an "Eksportēt" link to the run page using `original.pk`.
18. Run page is CSRF-protected, XLSX preselected, no nested HTML forms. Run view checks `has_view_permission(request, template)` after `get_object_or_404`.
19. All template admin permissions are explicit active-staff-only overrides.
20. Audit records `member_export_template_mutated` (create/effective-edit/delete via `form.changed_data`) and `member_export_run` with redacted metadata (no exported values, names, PII, template name, or raw target string). Bulk delete audits each then delegates to `super().delete_queryset`.
21. Existing P7 static CSV exports remain unchanged, including their superuser-sensitive rule.
22. Any active staff user can operate templates, including templates containing sensitive columns.
23. Full suite, ruff, and mypy green.

## Live validation note

Live validation is not required — the export is a pure server-side rendering path with no external dependencies. Stub fixtures cover the rendering logic; the test suite validates format correctness (CSV BOM/semicolon, XLSX headers/formula guard).

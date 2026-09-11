# Admin Hub — Member export runner

**Date:** 2026-09-11
**Status:** Design approved, pending implementation
**Spec:** This file
**Plan:** `docs/superpowers/plans/2026-09-11-admin-hub-member-export.md`

## Context

The Admin Hub (`/hub/`) currently provides five staff pages: Pieteikumi (queue), Izskatīšana (cockpit), Līgums (agreement), Maksas plāns un rēķini (billing), and Neapmaksātie rēķini (invoices). Member exports exist as a Django admin feature (`/admin/members/memberexporttemplate/<id>/run/`) that requires navigating out of the Hub shell. Staff want a single Hub surface to run member exports without leaving the Hub context.

P17 already delivered the full member export machinery: `MemberExportTemplate` model, `COLUMN_REGISTRY` + pure readers, `render_member_export()` (CSV/XLSX), the `MemberExportRunForm`, audit events (`MEMBER_EXPORT_RUN`), and permission posture. This feature must **reuse all of it** — no duplicate business logic.

## Requirements

### Scope

- Add a top navigation entry named **Eksporti** beside Pieteikumi and Rēķini.
- Add route `/hub/eksporti/` (named `admin_hub:exports`).
- Scope is **Member exports only**.
- Reuse: `MemberExportTemplate`, `apps.members.exports.COLUMN_REGISTRY` + readers, `apps.members.export_templates.render_member_export()`, `apps.core.export.csv_response` / `xlsx_response`, permission posture, and `AuditEvent.Action.MEMBER_EXPORT_RUN`.
- **Do not** rebuild or duplicate export business rules, column definitions, validation, filtering, or rendering.

### Hub surface: run-only

- The Hub exports page is **run-only**: it must NOT create, edit, delete, default, pin, or reorder export templates.
- It must NOT edit template columns.
- Template list order is alphabetical by `name`, then primary key (the existing `MemberExportTemplate.Meta.ordering = ("name", "pk")`).
- Templates are shared. Any active staff user can run a template even if it includes sensitive columns, matching P17.
- The Hub must show a sensitive-data marker (Latvian label) when the selected template includes any `SENSITIVE_KEYS` columns.

### Filter editing

- Selecting a template loads its saved `agreement_status_filters` and `training_groups` into editable Hub form controls.
- Staff can override both filter sets for the current request.
- The submitted selection **replaces** the stored filter set for the run only — it never persists to the template.
- An empty agreement-state selection removes the agreement predicate (no filter applied).
- An empty training-group selection removes the group predicate (no filter applied).
- Overrides never persist to the template.

### Filter data sources

- Agreement state options come from `Agreement.State.choices` (all states, in model-defined order).
- Training group options come from `TrainingGroup` rows.
- Combined filter semantics: selected agreement states → OR, selected groups → OR, both predicates → AND. This matches the existing `build_template_member_queryset()` behavior.

### Preview

- Hub supports a **preview** before export.
- Preview shows:
  - Exact matching member count (all matching rows, not capped).
  - First N matching rows, using the selected template's columns and the same effective filters as download.
- N comes from `EXPORT_PREVIEW_ROW_LIMIT` (env, default **20**).
- Missing, malformed, or non-positive setting safely falls back to 20 (exact value `20`, never a computed clamp).
- Preview creates **no** audit event.
- Preview is a CSRF-protected POST action.

### Download

- XLSX is the default format; CSV is the alternative.
- Both are direct in-memory downloads (no output persistence, jobs, email, provider calls, or schedules).
- Successful download creates the existing `AuditEvent.Action.MEMBER_EXPORT_RUN` event, enriched with effective filters, count, format, and sensitive flag.
- Audit metadata must **never** contain exported values, PII, raw rows, bytes, or the template name.
- Audit metadata keys: `template_id`, `column_keys`, `agreement_status_filters`, `training_group_ids`, `row_count`, `format`, `sensitive`.

### Error handling

| Condition | Behavior |
|-----------|----------|
| Anonymous user | Follows Hub login redirect (same as all Hub pages) |
| Non-staff user | Denied (403 or redirect to login, consistent with Hub) |
| Missing template | 404 |
| Invalid action / format / status / group | Form error displayed on the page; no output, no audit |
| Corrupted/persisted-invalid template | Refuses preview/download; shows error directing repair through Django admin |
| Zero matching rows | Empty preview table; headers-only download permitted |

### UI structure

- **Template list** — alphabetically ordered, each showing name + column count + sensitive marker. Shown whenever templates exist (regardless of selection state).
- **Selected template metadata** — column count, sensitive marker, column labels.
- **Editable agreement-state multi-select** — pre-populated from template's stored filters.
- **Editable training-group multi-select** — pre-populated from template's stored groups.
- **Format selector** — XLSX (default) / CSV radio.
- **Preview action button** — POST, renders preview count + table.
- **Preview count** — total matching member count.
- **Preview table** — first N rows with template column headers.
- **Download action button** — POST, streams attachment.
- **No templates state** — when the queryset is empty, shows "Nav sagatavotu šablonu." + link to Django admin changelist (`/admin/members/memberexporttemplate/`).

### Schema

- **No migration.** Reads `MemberExportTemplate` as-is.

## Design

### Architecture

Two distinct interaction phases:

1. **Template selection** — a GET link (`?template=<id>`) on the template list. No POST, no state mutation.
2. **Export runner** — a single POST form with `action=preview|download` dispatch. Template ID, filters, and format are form fields.

```
GET /hub/eksporti/?template=<id>
  → exports_view(request)
    → loads all MemberExportTemplate rows (ordered by name, pk)
    → if ?template=<id> present → loads template, pre-populates filter controls
    → renders exports.html

POST /hub/eksporti/
  → exports_view(request)
    → reads template_id + filters + fmt + action from form
    → validates template exists
    → validates filters against Agreement.State + TrainingGroup
    → validates template (full_clean → catches corruption)
    → dispatches: action=preview → renders preview (no audit)
                   action=download → streams attachment + audit
```

### New files

#### `apps/admin_hub/views.py` — new view function

Append to the existing `views.py`:

```python
@staff_member_required
def exports_view(request):
    ...
```

One `@staff_member_required` view — same authorization as existing Hub views. No custom decorator needed. Handles GET (template selection + filter UI) and POST (preview/download dispatch) in a single entry point.

#### `apps/admin_hub/urls.py` — new route

```python
path("eksporti/", views.exports_view, name="exports"),
```

#### `apps/admin_hub/forms.py` — new form (form boundary)

New `HubMemberExportRunForm(forms.Form)` owns request parsing for the POST runner form and presents Latvian errors. It **must not** define columns, query rules, filters, or rendering — those belong to P17.

- Reads raw POST data: `template_id` (int), `action` (str), `fmt` (str), `agreement_states` (list of str), `group_ids` (list of int).
- Validates `fmt` against `{"csv", "xlsx"}` using the same set as P17.
- Validates `action` against `{"preview", "download"}`.
- Validates `template_id` resolves to an existing `MemberExportTemplate` (uses `get_object_or_404` internally; if missing, sets a non-field error).
- Validates `agreement_states` against `VALID_AGREEMENT_STATES` from `apps.members.exports`.
- Validates `group_ids` against `TrainingGroup.objects.values_list("pk", flat=True)`.
- On success, exposes validated properties: `template`, `action`, `fmt`, `effective_agreement_states` (list of str, possibly empty), `effective_group_ids` (list of int, possibly empty).
- All error messages are Latvian, surfaced as form field errors or a non-field error for template_id.
- The form **does not** call P17 query or rendering functions — it only validates and exposes clean data. The view calls P17 services after form validation.

#### `templates/admin_hub/exports.html` — new template

Extends `admin_hub/base_hub.html`. Structure:

1. Page head: "Eksporti" title + subtitle.
2. Template list — always rendered when templates exist. Each item is an `<a href="?template={{ template.pk }}">` link showing name, column count, and sensitive marker.
3. When no templates exist: "Nav sagatavotu šablonu." + link to `/admin/members/memberexporttemplate/`.
4. When a template is selected (via `?template=<id>` GET param):
   a. Template metadata header (name, column count, sensitive marker).
   b. Agreement state multi-select (pre-filled from template).
   c. Training group multi-select (pre-filled from template).
   d. Format radio (XLSX/CSV, default XLSX).
   e. Preview button.
   f. Download button.
5. Preview section (rendered when `action=preview` POST was submitted):
   a. "Sakrit: N biedri" count.
   b. Table with column headers + first N rows.
6. Runner form: single `<form method="post">` wrapping the filter controls + both action buttons, with hidden `template_id` and `fmt` fields shared between preview and download.

#### Settings

Add to `fk_cesis_mms/settings.py` (after the AUDIT settings block, around line 230):

```python
def _parse_export_preview_row_limit(value: str) -> int:
    """Parse EXPORT_PREVIEW_ROW_LIMIT with exact fallback to 20.

    Returns 20 for any value that is not a positive integer (missing,
    empty, non-numeric, zero, negative, whitespace-only).  Never raises.
    """
    try:
        v = int(value.strip())
        return 20 if v <= 0 else v
    except (ValueError, AttributeError, TypeError):
        return 20


EXPORT_PREVIEW_ROW_LIMIT = _parse_export_preview_row_limit(
    os.environ.get("EXPORT_PREVIEW_ROW_LIMIT", "20")
)
```

The helper guarantees: no `ValueError` at startup, exact fallback to `20`, and no clamping to `1` or any other sentinel. A value of `"0"`, `"-5"`, `"abc"`, `""`, or `None` all produce `20`.

### Reused components

| Component | Source | Purpose |
|-----------|--------|---------|
| `MemberExportTemplate` | `apps/members/models.py` | Template model |
| `COLUMN_REGISTRY` | `apps/members/exports.py` | Column definitions + readers |
| `SENSITIVE_KEYS` | `apps/members/exports.py` | Sensitive column detection |
| `VALID_AGREEMENT_STATES` | `apps/members/exports.py` | Valid state validation |
| `render_member_export()` | `apps/members/export_templates.py` | Download rendering |
| `csv_response()` / `xlsx_response()` | `apps/core/export.py` | Format writers |
| `AuditEvent.Action.MEMBER_EXPORT_RUN` | `apps/core/models.py` | Audit event |
| `record_audit_event()` | `apps.core.audit` | Audit writer |
| `base_hub.html` | `templates/admin_hub/` | Template base |
| `@staff_member_required` | `django.contrib.admin` | Auth guard |

### P17 service boundary: parameterized effective filters

The Hub must **not** duplicate query or rendering logic. Instead, P17 service functions accept optional effective-filter overrides:

**`build_template_member_queryset(template, *, agreement_states=None, group_ids=None)`**

- `agreement_states`: if `None`, uses `template.agreement_status_filters`; if a list (including empty list), uses it as the effective agreement-state predicate.
- `group_ids`: if `None`, uses `template.training_groups`; if a list (including empty list), uses it as the effective group predicate.
- All other behavior identical to the existing implementation.

**`render_member_export(template, fmt, *, agreement_states=None, group_ids=None)`**

- Same sentinel semantics as `build_template_member_queryset`.
- Passes effective filters through to `build_template_member_queryset`.
- Returns `RenderedMemberExport` with `response`, `row_count`, `sensitive`.

Both functions are backward-compatible: callers that do not pass the optional params get the existing template-driven behavior.

The Hub calls these functions for both preview and download, guaranteeing exact parity. Preview additionally calls `qs.count()` and slices `[:limit]`; download passes the full queryset through the renderer.

**No new `apps/admin_hub/exports.py` module.** All filter resolution and rendering lives in the P17 service layer.

### Preview rendering

Preview renders a table with:

- Headers: `[COLUMN_REGISTRY[key].label for key in template.column_keys]`
- Rows: `[COLUMN_REGISTRY[key].reader(member) for key in template.column_keys]` for each member in the first N of the queryset.
- The count is `qs.count()` (total matching, not capped).
- The rows are `qs[:limit]` (capped slice).

To avoid N+1, the queryset already has all needed relations prefetched. The readers are pure attribute access (no queries).

### Audit event

On successful download:

```python
record_audit_event(
    action=str(AuditEvent.Action.MEMBER_EXPORT_RUN),
    actor=request.user,
    request=request,
    target_type="member_export_template",
    target_id=str(template.pk),
    target_repr="Member export template",
    metadata={
        "template_id": template.pk,
        "column_keys": list(template.column_keys or []),
        "agreement_status_filters": list(effective_agreement_states or []),
        "training_group_ids": sorted(effective_group_ids or []),
        "row_count": row_count,
        "format": fmt,
        "sensitive": rendered.sensitive,
    },
)
```

Key difference from the admin run view: `agreement_status_filters` and `training_group_ids` reflect the **effective** (possibly overridden) filters, not the template's stored values.

### Navigation

Add to `templates/admin_hub/base_hub.html`, inside the `<nav class="hub-nav">` block, between the "Rēķini" link and the `{% block hub_nav_extra %}` block:

```html
<a href="{% url 'admin_hub:exports' %}" class="{% if hub_section == 'exports' %}is-active{% endif %}">Eksporti</a>
```

The `hub_section` context variable must be `"exports"` for the exports page (and its preview/download POST targets, which render the same page context).

### Template structure

```
{% extends "admin_hub/base_hub.html" %}

{% block hub_title %}FK Cēsis Admin — Eksporti{% endblock %}

{% block hub_content %}
  <div class="page-head">
    <h1 class="page-title">Eksporti</h1>
    <p class="page-sub">Izvēlieties šablonu un eksportējiet biedru datus.</p>
  </div>

  {% if templates %}
    <!-- Template list (always shown when templates exist) -->
    <div class="template-list">
      {% for template in templates %}
        <a href="?template={{ template.pk }}" class="template-item">
          <h3>{{ template.name }}</h3>
          <p>{{ template.column_count }} kolonnas{% if template.has_sensitive %} · Sensitīvi dati{% endif %}</p>
        </a>
      {% endfor %}
    </div>

    {% if selected_template %}
      <!-- Selected template: filter controls + actions -->
      <form method="post" action="{% url 'admin_hub:exports' %}" id="export-form">
        {% csrf_token %}
        <input type="hidden" name="selected_template_id" value="{{ selected_template.pk }}">

        <!-- Template metadata -->
        <div class="template-meta">
          <h2>{{ selected_template.name }}</h2>
          <span>{{ selected_template.column_count }} kolonnas</span>
          {% if selected_template.has_sensitive %}
            <span>Sensitīvi dati</span>
          {% endif %}
        </div>

        <!-- Agreement state filter -->
        <div class="filter-group">
          <label>Līguma statuss (vairāku izvēle)</label>
          <select name="agreement_states" multiple size="4">
            {% for value, label in agreement_state_options %}
              <option value="{{ value }}" {% if value in selected_agreement_states %}selected{% endif %}>{{ label }}</option>
            {% endfor %}
          </select>
        </div>

        <!-- Training group filter -->
        <div class="filter-group">
          <label>Treniņu grupa (vairāku izvēle)</label>
          <select name="group_ids" multiple size="4">
            {% for group in all_groups %}
              <option value="{{ group.pk }}" {% if group.pk in selected_group_ids %}selected{% endif %}>{{ group.name }}</option>
            {% endfor %}
          </select>
        </div>

        <!-- Format selector -->
        <div class="filter-group">
          <label>Formāts</label>
          <label class="radio-option">
            <input type="radio" name="fmt" value="xlsx" {% if fmt == "xlsx" %}checked{% endif %}>
            XLSX
          </label>
          <label class="radio-option">
            <input type="radio" name="fmt" value="csv" {% if fmt == "csv" %}checked{% endif %}>
            CSV
          </label>
        </div>

        <!-- Actions -->
        <div class="export-actions">
          <button type="submit" name="action" value="preview">Priekšskats</button>
          <button type="submit" name="action" value="download">Lejupielādēt</button>
        </div>
      </form>
    {% endif %}
  {% else %}
    <!-- No templates at all -->
    <div class="card">
      <p>Nav sagatavotu šablonu.</p>
      <a href="/admin/members/memberexporttemplate/" class="btn">Pārvaldīt šablonus Django admin →</a>
    </div>
  {% endif %}

  <!-- Preview section (shown after action=preview POST) -->
  {% if preview_rows is not None %}
    <div class="preview-section">
      <h3>Sakrit: {{ preview_count }} biedri</h3>
      {% if preview_rows %}
        <table>
          <thead>
            <tr>
              {% for header in preview_headers %}
                <th>{{ header }}</th>
              {% endfor %}
            </tr>
          </thead>
          <tbody>
            {% for row in preview_rows %}
              <tr>
                {% for cell in row %}
                  <td>{{ cell|default:"—" }}</td>
                {% endfor %}
              </tr>
            {% endfor %}
          </tbody>
        </table>
        {% if preview_count > preview_limit %}
          <p class="hint">Rādīti pirmie {{ preview_limit }} no {{ preview_count }} rezultātiem.</p>
        {% endif %}
      {% else %}
        <p class="hint">Nav biedru, kas atbilstu izvēlētajiem filtriem.</p>
      {% endif %}
    </div>
  {% endif %}
{% endblock %}
```

Styling follows existing Admin Hub patterns (`.hub-page`, `.page-head`, `.page-title`, `.card`, `.btn`, `.hint` from `hub.css`). The preview table must be responsive — cells wrap, columns do not overflow the viewport. No invented CSS class names or visual contracts are prescribed beyond what the Hub already provides.

### Authorization

The view uses `@staff_member_required` — the same guard as the existing Hub views (`queue_view`, `invoices_view`, etc.). No additional permission checks are needed. The Hub's existing pattern is:

```python
@staff_member_required
def hub_view(request):
    ...
```

This redirects anonymous users to the login page and denies non-staff users with a 403.

### Form handling

Two distinct interaction surfaces:

- **Template selection** — a plain `<a href="?template=<id>">` GET link on the template list. No POST, no form, no state mutation.
- **Export runner** — a single `<form method="post">` with `action=preview|download` dispatch. Template ID, filters, and format are form fields. Preview and download share this form.

`HubMemberExportRunForm` (in `apps/admin_hub/forms.py`) parses the POST data, validates all fields, and exposes clean effective-filter values. It reuses P17 validation constants (`VALID_AGREEMENT_STATES`) and presents Latvian errors, but does not define columns, query rules, filters, or rendering. The `fmt` field uses the same `{"xlsx": "XLSX", "csv": "CSV"}` choices as P17's `MemberExportRunForm`; the Hub form may inherit from or duplicate only this choice set.

### Validation flow

```
POST (any action)
  → HubMemberExportRunForm(request.POST)
    → validate action in {"preview", "download"}
    → validate fmt in {"csv", "xlsx"}
    → validate template_id → get_object_or_404(MemberExportTemplate)
    → validate agreement_states against VALID_AGREEMENT_STATES
    → validate group_ids against TrainingGroup pk set
    → if errors → re-render page with form errors
    → if valid → view dispatches on form.action
  → template.full_clean() → if ValidationError → form error "Šablons ir nederīgs — labojiet kolonnas un statusus pilnajā administrācijā."
  → dispatch: preview | download
```

### Preview vs download parity

Preview and download share the **exact same** filter resolution and queryset construction, both calling the parameterized P17 service functions. The only difference: preview slices `[:limit]` and renders a table; download renders the full queryset through `render_member_export()`.

## Test plan

Tests live in `tests/admin_hub/test_admin_hub_exports.py`.

| Test | What it verifies |
|------|------------------|
| `test_nav_entry_rendered` | "Eksporti" link present in base nav, `is-active` class on exports page |
| `test_route_resolves` | `reverse("admin_hub:exports")` returns `/hub/eksporti/` |
| `test_anonymous_redirects` | Anonymous GET → redirect to login |
| `test_non_staff_denied` | Non-staff GET → 403 |
| `test_template_list_shown_when_templates_exist` | Templates exist + no `?template=` → alphabetical list rendered (not empty state) |
| `test_empty_templates_state` | No templates → "Nav sagatavotu šablonu." + admin changelist link |
| `test_templates_alphabetical_order` | Templates rendered in `name, pk` order |
| `test_template_item_metadata` | Column count + sensitive marker rendered correctly |
| `test_select_template_via_get` | `?template=<id>` selects template without POST |
| `test_stored_defaults_preserved` | Stored filters used when no override submitted |
| `test_clear_agreement_filter` | Empty agreement-state selection removes predicate |
| `test_clear_group_filter` | Empty group selection removes predicate |
| `test_combined_filter_semantics` | Both filters applied with AND semantics |
| `test_preview_count_exact` | Preview count equals `qs.count()` (not capped) |
| `test_preview_row_cap` | Preview rows ≤ `EXPORT_PREVIEW_ROW_LIMIT` |
| `test_preview_selected_columns` | Preview table uses template's column order + labels |
| `test_preview_no_n_plus_1` | Preview uses prefetched relations (assertNumQueries) |
| `test_download_xlsx_default` | Default format is XLSX |
| `test_download_csv_alternative` | CSV format produces CSV response |
| `test_preview_download_parity` | Preview and download use same queryset |
| `test_audit_only_on_download` | Preview creates no audit; download creates `MEMBER_EXPORT_RUN` |
| `test_audit_redacted_metadata` | Audit metadata contains no values, PII, rows, or template name |
| `test_zero_result_preview` | Zero matching → empty preview table |
| `test_zero_result_download` | Zero matching → headers-only download succeeds |
| `test_missing_template_404` | Invalid template_id → 404 |
| `test_invalid_format_error` | Invalid fmt → form error, no output, no audit |
| `test_invalid_agreement_state_error` | Invalid state → form error |
| `test_invalid_group_error` | Invalid group pk → form error |
| `test_corrupted_template_refused` | Invalid persisted template → error + admin link |
| `test_sensitive_marker_rendered` | Template with sensitive columns shows marker |
| `test_export_preview_row_limit_fallback` | Malformed/non-positive env value falls back to exact 20 |
| `test_hub_form_validates_with_p17_constants` | HubMemberExportRunForm uses VALID_AGREEMENT_STATES, does not define columns |
| `test_hub_form_no_duplicate_rules` | Hub form does not define query rules, filters, or rendering |

## Ambiguities

1. **Preview table rendering**: The spec says "preview shows exact matching member count and first N matching rows, using selected template columns and the same effective filters as download." It does not specify whether the preview table should render column headers. Decision: **yes, render column headers** to match the download output format.

2. **Sensitive data marker wording**: The spec says "show an appropriate sensitive-data marker." No specific text is mandated. Decision: a simple inline text label in Latvian ("Sensitīvi dati"), styled consistently with the Hub's existing visual patterns. No invented CSS classes or markup contracts.

3. **Template selection UX**: The spec says "template cards/list" but does not specify card vs table. Decision: simple list of links (`?template=<id>` GET param), avoiding POST forms for template selection entirely.

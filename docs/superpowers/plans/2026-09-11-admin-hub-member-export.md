# Admin Hub Member Export Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let active staff run existing shared Member export templates from `/hub/eksporti/`, temporarily adjust template filters, preview the first configured rows, then download XLSX or CSV.

**Architecture:** Keep `MemberExportTemplate` and P17 export services as canonical source for column definitions, filter semantics, query construction, rendering, and output safety. Add optional effective-filter arguments to the P17 service boundary; Hub request parsing stays in one `HubMemberExportRunForm`, and one staff-only Hub view dispatches preview versus download. No export configuration or output is persisted from Hub.

**Tech Stack:** Python 3.12, Django 5, pytest + pytest-django, Django templates, existing `openpyxl` export writer, ruff, mypy.

---

## Locked file map

| File | Change | Responsibility |
|---|---|---|
| `apps/members/export_templates.py` | Modify | Parameterized effective-filter queryset/render service, used by P17 admin and Hub. |
| `apps/admin_hub/forms.py` | Create | POST parsing and Latvian validation for Hub runner inputs only. |
| `apps/admin_hub/views.py` | Modify | One staff-only `exports_view`: GET selection, POST preview/download, audit. |
| `apps/admin_hub/urls.py` | Modify | Named `/hub/eksporti/` route. |
| `templates/admin_hub/base_hub.html` | Modify | `Eksporti` navigation item. |
| `templates/admin_hub/exports.html` | Create | Run-only template chooser, override form, preview, empty/error states. |
| `static/admin_hub/hub.css` | Modify | Responsive export-list/form/preview-table rules, following existing Hub tokens. |
| `fk_cesis_mms/settings.py` | Modify | Safe `EXPORT_PREVIEW_ROW_LIMIT` parser and setting, default 20. |
| `.env.example` | Modify | Document preview row-limit environment variable. |
| `tests/members/test_member_export_templates.py` | Modify | P17 service override/sentinel regression tests. |
| `tests/admin_hub/test_hub_exports.py` | Create | Hub route, UI, validation, preview, download, audit, and query tests. |
| `docs/milestones.md` | Modify after acceptance | Record delivered Hub member-export runner. |
| `AGENTS.md` | Modify after acceptance | Record route/capability and verification evidence. |

No migrations, model changes, background jobs, stored files, providers, schedules, template authoring UI, column editing UI, registration exports, or invoice exports.

## Contract details

### P17 service contract

Change signatures to:

```python
def build_template_member_queryset(
    template: MemberExportTemplate,
    *,
    agreement_states: list[str] | None = None,
    group_ids: list[int] | None = None,
) -> QuerySet[Member]: ...

def render_member_export(
    template: MemberExportTemplate,
    fmt: str,
    *,
    agreement_states: list[str] | None = None,
    group_ids: list[int] | None = None,
) -> RenderedMemberExport: ...
```

- `None` means use template-stored filter values.
- Explicit `[]` means remove that predicate.
- Non-empty state values retain current-agreement-only OR filtering.
- Non-empty group IDs retain OR filtering.
- When both values are non-empty, predicates remain ANDed.
- Existing P17 admin callers pass no new keywords and retain identical behaviour.
- The existing `select_related`, current-agreement `Prefetch(to_attr="_current_export_agreements")`, `.distinct()`, registry readers, CSV/XLSX response writers, filename convention, and sensitive detection remain single-source P17 behaviour.

### Hub form contract

Create `HubMemberExportRunForm(forms.Form)` in `apps/admin_hub/forms.py`:

```python
class HubMemberExportRunForm(forms.Form):
    action = forms.ChoiceField(choices=(("preview", "preview"), ("download", "download")))
    template_id = forms.IntegerField(min_value=1)
    agreement_states = forms.MultipleChoiceField(
        required=False,
        choices=Agreement.State.choices,
    )
    group_ids = forms.ModelMultipleChoiceField(
        required=False,
        queryset=TrainingGroup.objects.order_by("name", "pk"),
    )
    fmt = forms.ChoiceField(
        choices=MemberExportRunForm.FMT_CHOICES,
        initial="xlsx",
        widget=forms.RadioSelect,
    )

    @property
    def effective_group_ids(self) -> list[int]: ...
```

It owns request coercion and Latvian field errors only. It must not define column keys, query rules, or rendering. State choices and format choices reuse canonical P17/domain declarations. Empty submitted multi-selects clean to explicit empty lists, never `None`.

### Hub view contract

`exports_view` is the only Hub endpoint:

```text
GET  /hub/eksporti/
GET  /hub/eksporti/?template=<positive-pk>
POST /hub/eksporti/  action=preview|download
```

- All routes use `@staff_member_required` consistent with existing Hub pages.
- GET loads templates using model ordering; an invalid supplied template ID is `404`.
- When templates exist but no `template` parameter is supplied, render chooser list.
- Empty chooser state appears only when there are zero templates and links to `/admin/members/memberexporttemplate/`.
- POST obtains template by validated ID, runs `template.full_clean()`, validates `HubMemberExportRunForm`, then uses explicit cleaned lists as P17 overrides.
- Corrupted templates return a Latvian non-field error and admin repair link; no preview, download, or audit.
- Preview uses parameterized `build_template_member_queryset`; it counts whole queryset and slices at `settings.EXPORT_PREVIEW_ROW_LIMIT`. It renders registry labels and pure-reader cell values.
- Download uses parameterized `render_member_export`, then emits `MEMBER_EXPORT_RUN` with exact effective filter metadata. Preview never audits.

### Settings contract

In `fk_cesis_mms/settings.py` expose:

```python
def _parse_export_preview_row_limit(value: str | None) -> int:
    try:
        parsed = int(value.strip())
    except (AttributeError, TypeError, ValueError):
        return 20
    return parsed if parsed > 0 else 20


EXPORT_PREVIEW_ROW_LIMIT = _parse_export_preview_row_limit(
    os.environ.get("EXPORT_PREVIEW_ROW_LIMIT", "20")
)
```

Every missing, whitespace-only, malformed, zero, or negative value resolves to exactly `20`; application startup never raises from this setting.

## Task 1: Parameterize P17 export services

**Files:**
- Modify: `tests/members/test_member_export_templates.py`
- Modify: `apps/members/export_templates.py`

- [ ] **Step 1: Write failing override-contract tests**

Add tests beside current queryset/render tests. Create templates with stored `signed` status and one training group, plus members that distinguish state-only, group-only, both, and neither. Cover:

```python
def test_queryset_none_uses_stored_template_filters(...):
    assert list(build_template_member_queryset(template)) == [both_match]

def test_queryset_explicit_empty_filters_remove_predicates(...):
    qs = build_template_member_queryset(template, agreement_states=[], group_ids=[])
    assert set(qs) == {state_only, group_only, both_match, neither}

def test_queryset_effective_filters_replace_template_filters(...):
    qs = build_template_member_queryset(
        template, agreement_states=[Agreement.State.SENT], group_ids=[other_group.pk]
    )
    assert list(qs) == [replacement_match]

def test_render_effective_filters_uses_same_rows_as_queryset(...):
    rendered = render_member_export(template, "csv", agreement_states=[], group_ids=[])
    assert rendered.row_count == build_template_member_queryset(
        template, agreement_states=[], group_ids=[]
    ).count()
```

Also retain an existing no-keyword render/query regression test to prove P17 admin behaviour remains stored-template-driven.

- [ ] **Step 2: Run red phase**

Run:

```bash
uv run pytest -q tests/members/test_member_export_templates.py
```

Expected: FAIL because service functions reject `agreement_states` and `group_ids` keyword arguments.

- [ ] **Step 3: Implement smallest shared override boundary**

In `apps/members/export_templates.py`:

1. Add keyword-only optional `agreement_states` and `group_ids` arguments to `build_template_member_queryset`.
2. Resolve `states` as `list(template.agreement_status_filters or [])` only when `agreement_states is None`; otherwise use `list(agreement_states)`.
3. Resolve group IDs from `template.training_groups.values_list("pk", flat=True)` only when `group_ids is None`; otherwise use `list(group_ids)`.
4. Preserve current filter clauses, prefetch, and `.distinct()` exactly.
5. Add same keyword-only args to `render_member_export` and pass them to the builder.

Do not validate untrusted input in this service; Hub form and existing template model validation own that. Do not change headers, output writers, filenames, or static-admin call sites.

- [ ] **Step 4: Run green phase**

Run:

```bash
uv run pytest -q tests/members/test_member_export_templates.py tests/members/test_member_export_template_admin.py
```

Expected: PASS. Existing Django-admin export run remains compatible.

- [ ] **Step 5: Commit service boundary**

```bash
git add apps/members/export_templates.py tests/members/test_member_export_templates.py
git commit -m "feat(exports): support temporary filters"
```

## Task 2: Add safe preview-limit setting

**Files:**
- Modify: `fk_cesis_mms/settings.py`
- Modify: `.env.example`
- Test: `tests/admin_hub/test_hub_exports.py`

- [ ] **Step 1: Write failing setting tests**

Create `tests/admin_hub/test_hub_exports.py`. Import `_parse_export_preview_row_limit` and test:

```python
@pytest.mark.parametrize("value", [None, "", "  ", "zero", "0", "-3"])
def test_preview_limit_invalid_value_falls_back_to_20(value):
    assert _parse_export_preview_row_limit(value) == 20


def test_preview_limit_positive_integer_is_preserved():
    assert _parse_export_preview_row_limit("31") == 31
```

- [ ] **Step 2: Run red phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k preview_limit
```

Expected: FAIL because parser does not exist.

- [ ] **Step 3: Implement setting and sample environment entry**

Add the exact safe parser/constant contract above in `fk_cesis_mms/settings.py`, near current environment-backed settings. Add to `.env.example`:

```dotenv
# Admin Hub member-export preview row cap. Invalid or non-positive values use 20.
EXPORT_PREVIEW_ROW_LIMIT=20
```

- [ ] **Step 4: Run green phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k preview_limit
```

Expected: PASS.

- [ ] **Step 5: Commit setting**

```bash
git add fk_cesis_mms/settings.py .env.example tests/admin_hub/test_hub_exports.py
git commit -m "feat(hub): configure export preview limit"
```

## Task 3: Add Hub POST form contract

**Files:**
- Create: `apps/admin_hub/forms.py`
- Modify: `tests/admin_hub/test_hub_exports.py`

- [ ] **Step 1: Write failing form tests**

Add form-level tests that create two groups and cover:

```python
def test_run_form_defaults_to_xlsx_when_unbound(): ...
def test_run_form_cleans_empty_filters_to_explicit_empty_lists(): ...
def test_run_form_returns_selected_group_ids_in_name_pk_order(): ...
def test_run_form_rejects_unknown_action_format_state_and_group(): ...
```

Assert visible Latvian errors on `action`, `fmt`, `agreement_states`, and `group_ids`. Do not make database queries part of field readers.

- [ ] **Step 2: Run red phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k run_form
```

Expected: FAIL because `apps.admin_hub.forms.HubMemberExportRunForm` does not exist.

- [ ] **Step 3: Implement minimal Hub form**

Create `apps/admin_hub/forms.py` with `HubMemberExportRunForm`:

- `template_id`: positive integer.
- `action`: `preview` / `download` choices.
- `fmt`: `MemberExportRunForm.FMT_CHOICES`, default XLSX.
- `agreement_states`: optional `MultipleChoiceField` using `Agreement.State.choices`; call P17 `validate_agreement_status_filters` in its cleaner so P17 remains canonical for state validation.
- `group_ids`: optional `ModelMultipleChoiceField(TrainingGroup.objects.order_by("name", "pk"))`; expose a deterministic `effective_group_ids` property returning integer primary keys.
- Normalize Django default English errors to Latvian strings for invalid fields.

The form must return explicit `[]` for unselected filters. It must not import `COLUMN_REGISTRY`, build querysets, read member values, or render attachments.

- [ ] **Step 4: Run green phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k run_form
```

Expected: PASS.

- [ ] **Step 5: Commit form**

```bash
git add apps/admin_hub/forms.py tests/admin_hub/test_hub_exports.py
git commit -m "feat(hub): add member export run form"
```

## Task 4: Implement Hub route, navigation, and template selection

**Files:**
- Modify: `apps/admin_hub/urls.py`
- Modify: `apps/admin_hub/views.py`
- Modify: `templates/admin_hub/base_hub.html`
- Create: `templates/admin_hub/exports.html`
- Modify: `tests/admin_hub/test_hub_exports.py`

- [ ] **Step 1: Write failing GET/permission/navigation tests**

Add tests:

```python
def test_exports_route_resolves():
    assert reverse("admin_hub:exports") == "/hub/eksporti/"

def test_anonymous_exports_redirects_to_login(client): ...
def test_non_staff_exports_is_forbidden(client, non_staff_user): ...
def test_exports_nav_link_and_active_state_render(staff_client): ...
def test_templates_render_in_model_name_pk_order(staff_client, export_templates): ...
def test_get_selected_template_prefills_stored_filters(staff_client, export_template): ...
def test_unknown_get_template_is_404(staff_client): ...
def test_zero_templates_renders_admin_changelist_link(staff_client): ...
```

Use `MemberExportTemplate.objects.create(...)` with valid `column_keys`; test same-name templates by PK to pin secondary order. For selected GET, assert stored state option and group option are selected, but no mutation/audit occurs.

- [ ] **Step 2: Run red phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k "route or exports_nav or templates_render or selected_template or zero_templates or anonymous or non_staff"
```

Expected: FAIL because route and view do not exist.

- [ ] **Step 3: Implement minimal GET surface**

1. Add `path("eksporti/", views.exports_view, name="exports")`.
2. Add `Eksporti` nav anchor after Rēķini, active only for `hub_section == "exports"`.
3. In `exports_view`, use `@staff_member_required`; on GET load all templates with default model ordering.
4. If `request.GET.get("template")` exists, resolve with `get_object_or_404(MemberExportTemplate, pk=...)`; reject non-integer IDs as `Http404`; prepare form initial state from stored template filters and groups.
5. Render template chooser whenever templates exist and no selection is present; render zero-template empty state only when no templates exist.
6. Set `hub_section="exports"`, `agreement_state_options=Agreement.State.choices`, selected template metadata, and template column labels from `COLUMN_REGISTRY`.

Do not add a template-authoring route, default field, persistence, or POST action in this task.

- [ ] **Step 4: Run green phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k "route or exports_nav or templates_render or selected_template or zero_templates or anonymous or non_staff"
```

Expected: PASS.

- [ ] **Step 5: Commit GET surface**

```bash
git add apps/admin_hub/urls.py apps/admin_hub/views.py templates/admin_hub/base_hub.html templates/admin_hub/exports.html tests/admin_hub/test_hub_exports.py
git commit -m "feat(hub): add member export page"
```

## Task 5: Add preview and download dispatch with audit

**Files:**
- Modify: `apps/admin_hub/views.py`
- Modify: `templates/admin_hub/exports.html`
- Modify: `tests/admin_hub/test_hub_exports.py`

- [ ] **Step 1: Write failing POST, preview, download, and audit tests**

Add factories/fixtures for templates, groups, guardians, members, and current agreements. Cover all acceptance behavior:

```python
def test_preview_replaces_stored_filters(staff_client, stored_filter_template, ...): ...
def test_preview_empty_filter_removes_that_predicate(staff_client, ...): ...
def test_preview_filters_are_and_combined(staff_client, ...): ...
def test_preview_shows_exact_count_and_first_configured_rows(settings, staff_client, ...): ...
def test_preview_uses_selected_template_column_order_and_labels(staff_client, ...): ...
def test_preview_emits_no_audit_event(staff_client, ...): ...
def test_download_defaults_to_xlsx_and_audits_effective_metadata(staff_client, ...): ...
def test_download_csv_uses_same_effective_rows_as_preview(staff_client, ...): ...
def test_zero_result_preview_and_headers_only_download(staff_client, ...): ...
def test_invalid_post_action_format_state_or_group_has_error_and_no_audit(staff_client, ...): ...
def test_corrupted_template_refuses_preview_and_download(staff_client, ...): ...
```

For preview cap, set `settings.EXPORT_PREVIEW_ROW_LIMIT = 2`, create three matching members, assert count text reports 3 and output table contains two member names only. For preview/download parity, parse CSV body into rows and assert its data rows equal the preview's expected filtered member set. For audit, assert metadata equals safe structural values:

```python
{
    "template_id": template.pk,
    "column_keys": template.column_keys,
    "agreement_status_filters": [Agreement.State.SIGNED],
    "training_group_ids": [group.pk],
    "row_count": 1,
    "format": "xlsx",
    "sensitive": True,
}
```

Then assert metadata serialization does not contain any member, guardian, email, personal-ID, address, or template-name value.

For N+1, build/evaluate a preview queryset, then wrap only the registry-reader loop in `CaptureQueriesContext(connection)` and assert zero additional queries.

- [ ] **Step 2: Run red phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k "preview or download or audit or corrupted or invalid_post or zero_result"
```

Expected: FAIL because POST dispatch is not implemented.

- [ ] **Step 3: Implement one POST dispatch path**

Extend `exports_view` only:

1. Bind `HubMemberExportRunForm(request.POST)` for POST. Invalid form re-renders selected-template page, carrying field errors, submitted selections, and no preview/audit.
2. Resolve `template_id` after successful form validation; unknown ID is `404`.
3. Call `template.full_clean()`. On `ValidationError`, add Latvian non-field error, include `/admin/members/memberexporttemplate/` repair link, and return without P17 query/render/audit.
4. Read `effective_states = form.cleaned_data["agreement_states"]` and `effective_group_ids = form.effective_group_ids`. These are explicit lists, including `[]`.
5. For `preview`, call parameterized P17 queryset builder once for the effective definition; calculate `count()`, slice only `settings.EXPORT_PREVIEW_ROW_LIMIT`, read cells through `COLUMN_REGISTRY`, and return the page. Do not create an audit event.
6. For `download`, call parameterized `render_member_export`. Call `record_audit_event` once with `MEMBER_EXPORT_RUN`, generic target fields, and exact effective structural metadata. Return attachment.
7. Always reuse a single context builder so selected template, submitted controls, column headers, and errors are identical for preview and failed download POST paths.

Do not create output records/files, invoke background jobs, alter templates, issue raw external links, or call CSV/XLSX writers directly from Hub.

- [ ] **Step 4: Run green phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py
```

Expected: PASS.

- [ ] **Step 5: Commit runner behavior**

```bash
git add apps/admin_hub/views.py templates/admin_hub/exports.html tests/admin_hub/test_hub_exports.py
git commit -m "feat(hub): run and preview member exports"
```

## Task 6: Add responsive Hub styling and template regression guard

**Files:**
- Modify: `static/admin_hub/hub.css`
- Modify: `templates/admin_hub/exports.html`
- Modify: `tests/admin_hub/test_hub_exports.py`
- Modify: `tests/admin_hub/test_no_template_comment_leaks.py`

- [ ] **Step 1: Write failing presentation-contract tests**

Add tests that assert rendered export page has:

```python
assert 'data-export-template-list' in body
assert 'data-export-preview' in body
assert 'data-export-sensitive' in body
assert 'data-export-table' in body
```

Add route to the no-comment-leak parametrized list so rendered export HTML never contains Django template-comment bodies.

- [ ] **Step 2: Run red phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k presentation tests/admin_hub/test_no_template_comment_leaks.py
```

Expected: FAIL because stable export-page hooks do not exist.

- [ ] **Step 3: Implement minimal responsive styling**

Add stable `data-export-*` hooks to template elements. Append focused CSS using existing Hub tokens/classes:

- chooser list/card layout wraps at narrow widths;
- filter controls stack below 720px;
- sensitive marker uses existing warning palette;
- preview table sits in horizontal overflow container, keeps headers readable, and does not push page beyond viewport;
- preview/download buttons remain reachable and at least existing `.btn` touch sizing.

Use only normal Django `{% comment %}...{% endcomment %}` syntax if a template comment is necessary. No inline styles, no JavaScript, and no new visual system.

- [ ] **Step 4: Run green phase**

Run:

```bash
uv run pytest -q tests/admin_hub/test_hub_exports.py -k presentation tests/admin_hub/test_no_template_comment_leaks.py
```

Expected: PASS.

- [ ] **Step 5: Commit presentation layer**

```bash
git add static/admin_hub/hub.css templates/admin_hub/exports.html tests/admin_hub/test_hub_exports.py tests/admin_hub/test_no_template_comment_leaks.py
git commit -m "style(hub): polish member export runner"
```

## Task 7: Update delivery documentation and verify full repository

**Files:**
- Modify: `docs/milestones.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update milestone tracker**

Add a concise delivered entry under Admin Hub status. State that `/hub/eksporti/` is a run-only Member export adapter over P17 templates; it offers temporary status/group overrides, N-row preview with configured default 20, XLSX/CSV download, and redacted download audit. Explicitly state template authoring remains Django-admin-only and no export output persists.

- [ ] **Step 2: Update project guide**

Add the same operational capability to the Admin Hub delivered section in `AGENTS.md`, including environment variable name/default and run-only boundary.

- [ ] **Step 3: Run focused verification**

Run:

```bash
uv run pytest -q tests/members/test_member_export_templates.py tests/members/test_member_export_template_admin.py tests/admin_hub/test_hub_exports.py tests/admin_hub/test_no_template_comment_leaks.py
```

Expected: PASS.

- [ ] **Step 4: Run full required verification**

Run sequentially:

```bash
uv run pytest -q && uv run ruff check . && uv run mypy . && uv run python manage.py makemigrations --check
```

Expected: all commands exit 0; migration check reports no changes.

- [ ] **Step 5: Commit docs**

```bash
git add docs/milestones.md AGENTS.md
git commit -m "docs: record Hub member export runner"
```

## Acceptance traceability

| Acceptance requirement | Implemented and tested in |
|---|---|
| Top-nav Eksporti + `/hub/eksporti/` | Task 4 |
| Member-only run-only scope | Tasks 4–5 |
| Alphabetical shared templates; no default | Task 4 |
| Temporary replace/clear overrides | Tasks 1, 3, 5 |
| OR within filter sets, AND across sets | Tasks 1, 5 |
| Preview first N + exact count | Tasks 2, 5 |
| XLSX default and CSV option | Tasks 3, 5 |
| Direct, unpersisted output | Task 5 |
| Active-staff permission and sensitive visibility | Tasks 4–5 |
| Redacted download-only audit | Task 5 |
| Invalid/corrupt/zero-result handling | Task 5 |
| Responsive Hub UI | Task 6 |
| Milestones/project guide | Task 7 |

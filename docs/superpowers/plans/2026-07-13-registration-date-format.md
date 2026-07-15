# Registration Date Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parent registration child birth date shows/accepts Latvian `DD.MM.GGGG`, keeps native picker assist, and auto-inserts dots while typing.

**Architecture:** Django form remains the source of truth for server validation. The visible field is a text-style date field with `DD.MM.GGGG`; a hidden native `type=date` input provides calendar assist; vanilla JS in existing `wizard.js` syncs picker values and applies a small mask. CSS keeps it as one short visible control.

**Tech Stack:** Django forms/templates, vanilla JS in `static/js/wizard.js`, CSS in `static/css/parent_theme.css`, pytest + pytest-django.

---

## File-by-file plan

- Modify `apps/registrations/forms.py`
  - `member_birth_date` widget attrs: `placeholder="DD.MM.GGGG"`, `data-date-format="lv-dot"`, `autocomplete="bday"`, `inputmode="numeric"`, `maxlength="10"`.
  - Keep `input_formats=["%d.%m.%Y"]` and `format="%d.%m.%Y"`.

- Modify `templates/parent_ui/includes/form_field.html`
  - Keep existing picker-assist markup for `data-date-format="lv-dot"`.

- Modify `static/js/wizard.js`
  - Add `formatLvDotDateInput(value)` helper.
  - Convert `01022025`, `01/02/2025`, and `2025-02-01` to `01.02.2025`.
  - Auto-insert dots after day/month while typing.
  - On visible input event: normalize visible value, sync picker ISO value when complete/valid-looking.
  - On picker change: fill visible field with `DD.MM.YYYY` and dispatch bubbling `input` + `change` events.

- Modify `static/css/parent_theme.css`
  - Keep current compact single-control date-assist CSS.

- Modify tests:
  - `tests/registrations/test_wizard_js_contract.py`: source-level contract for mask helper and examples.
  - `tests/registrations/test_application_workspace_template.py`: keep DOM/CSS date assist tests.
  - Existing UI POST fixtures remain `DD.MM.YYYY`.

- No migrations, no dependency.

## Test strategy

- Red phase: add JS source contract test before implementation.
- Targeted tests:
  - `uv run pytest tests/registrations/test_wizard_js_contract.py::TestWizardJsContract::test_date_mask_contract_for_latvian_birth_date -q`
  - `uv run pytest tests/registrations/test_application_workspace_template.py::test_member_birth_date_renders_latvian_placeholder_hint_and_picker_assist -q`
  - `uv run pytest tests/registrations/test_application_workspace_template.py::test_date_assist_css_contract_single_short_control_with_inside_button -q`
- Final gate:
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run mypy .`
  - `uv run python manage.py makemigrations --check`

## Acceptance criteria per unit

### Native-date probe
- Chromium probe with `lang="lv"` showed `mm/dd/yyyy` / `02/01/2025`; native-only path is rejected.

### Form unit
- `01.02.2025` parses to `date(2025, 2, 1)`.
- Invalid date still shows `Ievadiet derīgu datumu.`.

### Editable UI unit
- One short visible control with button inside right edge.
- Hidden native input not visible as second field.
- Placeholder and hint remain.

### JS mask unit
- Source contains `formatLvDotDateInput`.
- Source contains ISO paste pattern for `YYYY-MM-DD`.
- Source contains dot/slash cleanup and max 8-digit logic.
- Source wires visible input through formatter before picker sync.

## Tasks

### Task 1: Add failing JS mask contract test

**Files:**
- Modify: `tests/registrations/test_wizard_js_contract.py`

- [ ] **Step 1: Add source-level mask test**

Add to `TestWizardJsContract`:

```python
    def test_date_mask_contract_for_latvian_birth_date(self):
        src = _source()
        assert "formatLvDotDateInput" in src
        assert "data-date-format" in src
        assert "2025-02-01" in src or "(\\d{4})-(\\d{2})-(\\d{2})" in src
        assert "replace(/\\D/g" in src or "replace(/[^\\d]/g" in src
        assert "slice(0, 8)" in src
        assert "01.02.2025" in src or "parts.join('.')" in src
```

- [ ] **Step 2: Run red phase**

```bash
uv run pytest tests/registrations/test_wizard_js_contract.py::TestWizardJsContract::test_date_mask_contract_for_latvian_birth_date -q
```

Expected: fails because `formatLvDotDateInput` does not exist.

### Task 2: Add mask implementation

**Files:**
- Modify: `apps/registrations/forms.py`
- Modify: `static/js/wizard.js`

- [ ] **Step 1: Add form attrs**

Update `member_birth_date` widget attrs to include:

```python
"inputmode": "numeric",
"maxlength": "10",
```

- [ ] **Step 2: Add formatter helper to `wizard.js` near date helpers**

```javascript
  function formatLvDotDateInput(value) {
    var raw = (value || '').trim();
    var iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
    if (iso) return iso[3] + '.' + iso[2] + '.' + iso[1];

    var digits = raw.replace(/\D/g, '').slice(0, 8);
    if (digits.length <= 2) return digits.length === 2 ? digits + '.' : digits;
    if (digits.length <= 4) return digits.slice(0, 2) + '.' + digits.slice(2) + (digits.length === 4 ? '.' : '');
    return digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4);
  }
```

- [ ] **Step 3: Use formatter in visible input handler**

Inside `setupDatePickerAssists`, replace visible input listeners with a single handler:

```javascript
      function normalizeVisibleAndSyncPicker() {
        var formatted = formatLvDotDateInput(visible.value);
        if (formatted && formatted !== visible.value) visible.value = formatted;
        syncPickerFromVisible();
      }

      visible.addEventListener('input', normalizeVisibleAndSyncPicker);
      visible.addEventListener('change', normalizeVisibleAndSyncPicker);
```

Keep `syncPickerFromVisible()` for button-click use.

- [ ] **Step 4: Ensure picker change still dispatches events**

No change expected if current code already dispatches bubbling `input` and `change` after setting visible value.

- [ ] **Step 5: Run targeted tests**

```bash
uv run pytest tests/registrations/test_wizard_js_contract.py::TestWizardJsContract::test_date_mask_contract_for_latvian_birth_date tests/registrations/test_application_workspace_template.py::test_member_birth_date_renders_latvian_placeholder_hint_and_picker_assist tests/registrations/test_application_workspace_template.py::test_date_assist_css_contract_single_short_control_with_inside_button -q
```

Expected: pass.

### Task 3: Final verification

**Files:**
- No further edits expected.

- [ ] **Step 1: Run focused tests**

```bash
uv run pytest tests/registrations/test_wizard_js_contract.py tests/registrations/test_application_workspace_template.py tests/registrations/test_workspace_auto_save.py tests/registrations/test_registration_form_contract.py -q
```

Expected: pass.

- [ ] **Step 2: Run full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: all pass, no migrations.

- [ ] **Step 3: Generate filtered critique diff**

```bash
bunx critique --web "Registration date mask" --filter "apps/registrations/forms.py" --filter "templates/parent_ui/includes/form_field.html" --filter "static/js/wizard.js" --filter "static/css/parent_theme.css" --filter "templates/registrations/application_workspace.html" --filter "tests/registrations/test_registration_form_contract.py" --filter "tests/registrations/test_application_workspace_template.py" --filter "tests/registrations/test_wizard_js_contract.py" --filter "tests/analytics/test_milestone_hooks.py" --filter "tests/documents/test_guardian_document_reuse.py" --filter "tests/registrations/test_parent_application_workspace.py" --filter "tests/registrations/test_parent_edit_permissions.py" --filter "tests/registrations/test_parent_ocr_prefill_flow.py" --filter "tests/registrations/test_workspace_auto_save.py" --filter "docs/superpowers/specs/2026-07-13-registration-date-format-design.md" --filter "docs/superpowers/plans/2026-07-13-registration-date-format.md"
```

## Plan self-review

- Covers native `lang=lv` probe result.
- Covers dot mask and ISO paste conversion.
- Keeps one-field picker-assist layout.
- No placeholder tasks.
- No new dependency or migration.

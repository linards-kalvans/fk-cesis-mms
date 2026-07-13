# Registration Date Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Force the parent registration child birth date field to show and accept Latvian `DD.MM.GGGG` format.

**Architecture:** Keep the database/model date field unchanged. Replace only the form widget/parsing/display contract for `RegistrationApplicationForm.member_birth_date`, using Django's built-in `DateField.input_formats` and `DateInput(format=...)` support. Parent templates keep the shared field partial; only read-only/review date formatting changes where currently hardcoded.

**Tech Stack:** Django forms/templates, pytest + pytest-django, existing `uv run` commands.

---

## Design decisions

1. **Use text input, not native `type="date"`.**
   - Why: browser-native date inputs own the visible date format and placeholder behavior, so `DD.MM.GGGG` cannot be reliably forced across user locales.
   - Contract: visible input value is `DD.MM.GGGG`; cleaned value remains a Python `date`.

2. **Use Django form parsing, not custom parser code.**
   - Why: `forms.DateField(input_formats=["%d.%m.%Y"])` already validates real calendar dates and produces `date` values.
   - Boundary: no JavaScript mask, no date picker dependency.

3. **Keep shared form-field rendering.**
   - Why: `templates/parent_ui/includes/form_field.html` already renders label, widget, help text, and errors. Setting `help_text` on the form field is enough.

4. **Format parent read-only display in the template.**
   - Why: one current template line renders the member birth date as `Y-m-d`; changing it to `d.m.Y` is the smallest correct fix.

## File-by-file plan

- Modify `apps/registrations/forms.py`
  - Change `member_birth_date` from native date widget to text input.
  - Add `help_text="Ievadiet datumu formātā DD.MM.GGGG"`.
  - Add `input_formats=["%d.%m.%Y"]`.
  - Set `widget=forms.DateInput(attrs={"placeholder": "DD.MM.GGGG"}, format="%d.%m.%Y")`.

- Modify `templates/registrations/application_workspace.html`
  - Change read-only `member_birth_date` display from `date:"Y-m-d"` to `date:"d.m.Y"`.

- Modify tests in `tests/registrations/test_registration_form_contract.py`
  - Add focused form tests for valid/invalid Latvian date input.
  - Keep existing service tests using ISO strings unless they fail; those paths pass date-like values into services and are not the parent visible form contract.

- Modify tests in `tests/registrations/test_application_workspace_template.py`
  - Add rendered HTML assertion that `member_birth_date` input is text-like (no `type="date"`), has `placeholder="DD.MM.GGGG"`, and the help text appears.

- Add or update a read-only display assertion in `tests/registrations/test_application_workspace_template.py`
  - Use an approved/submitted read-only workspace response and assert the rendered date is dot-separated (`01.01.2025`) and old ISO display (`2025-01-01`) is absent near the birth-date label.

- No docs beyond the existing spec/plan.
- No migrations.

## Test strategy

- Framework: existing pytest + pytest-django.
- Red phase: add tests first and run them before implementation.
- Targeted tests:
  - `uv run pytest tests/registrations/test_registration_form_contract.py::TestRegistrationFormContract::test_member_birth_date_accepts_latvian_dot_format -q`
  - `uv run pytest tests/registrations/test_registration_form_contract.py::TestRegistrationFormContract::test_member_birth_date_rejects_invalid_latvian_dot_format -q`
  - `uv run pytest tests/registrations/test_application_workspace_template.py::test_member_birth_date_renders_latvian_placeholder_and_hint -q`
  - `uv run pytest tests/registrations/test_application_workspace_template.py::test_read_only_member_birth_date_uses_latvian_dot_format -q`
- Final gate:
  - `uv run pytest -q`
  - `uv run ruff check .`
  - `uv run mypy .`
  - `uv run python manage.py makemigrations --check`

Do not test browser locale behavior; implementation removes browser-native date formatting from the contract.

## Acceptance criteria per unit

### Form unit
- `RegistrationApplicationForm(data={..., "member_birth_date": "01.02.2025"}, is_submit=False)` is valid for the date field.
- `form.cleaned_data["member_birth_date"]` equals `date(2025, 2, 1)`.
- `32.02.2025` is invalid and uses the existing Latvian invalid-date error.
- Rendered widget value for an initial date is `01.02.2025`.

### Parent editable template unit
- Rendered `member_birth_date` input contains `placeholder="DD.MM.GGGG"`.
- Rendered page contains `Ievadiet datumu formātā DD.MM.GGGG`.
- Rendered `member_birth_date` input is not `type="date"`.

### Parent read-only template unit
- Existing stored date `2025-01-01` displays as `01.01.2025`.
- `2025-01-01` is not rendered as the birth-date value in the read-only parent workspace.

## Documentation scope

- Existing design spec: `docs/superpowers/specs/2026-07-13-registration-date-format-design.md`.
- This plan: `docs/superpowers/plans/2026-07-13-registration-date-format.md`.
- Do not update `AGENTS.md`, `docs/milestones.md`, or README for this small UI/form contract change.

---

## Tasks

### Task 1: Add failing form contract tests

**Files:**
- Modify: `tests/registrations/test_registration_form_contract.py`

- [ ] **Step 1: Add imports**

Add near existing imports if missing:

```python
from datetime import date
```

- [ ] **Step 2: Add valid Latvian date test inside `TestRegistrationFormContract`**

```python
    def test_member_birth_date_accepts_latvian_dot_format(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm(
            data={
                "guardian_email": "date-format@example.com",
                "member_birth_date": "01.02.2025",
            },
            is_submit=False,
        )

        assert form.is_valid()
        assert form.cleaned_data["member_birth_date"] == date(2025, 2, 1)
```

- [ ] **Step 3: Add invalid Latvian date test inside `TestRegistrationFormContract`**

```python
    def test_member_birth_date_rejects_invalid_latvian_dot_format(self):
        from apps.registrations.forms import RegistrationApplicationForm

        form = RegistrationApplicationForm(
            data={
                "guardian_email": "date-format@example.com",
                "member_birth_date": "32.02.2025",
            },
            is_submit=False,
        )

        assert not form.is_valid()
        assert form.errors["member_birth_date"] == ["Ievadiet derīgu datumu."]
```

- [ ] **Step 4: Run red-phase form tests**

Run:

```bash
uv run pytest tests/registrations/test_registration_form_contract.py::TestRegistrationFormContract::test_member_birth_date_accepts_latvian_dot_format tests/registrations/test_registration_form_contract.py::TestRegistrationFormContract::test_member_birth_date_rejects_invalid_latvian_dot_format -q
```

Expected before implementation: at least the valid-format test fails because the field currently expects browser/native ISO format.

### Task 2: Add failing template contract tests

**Files:**
- Modify: `tests/registrations/test_application_workspace_template.py`

- [ ] **Step 1: Add editable template test**

Add after existing required-input rendering tests:

```python
def test_member_birth_date_renders_latvian_placeholder_and_hint():
    client = Client()
    account, app = _make_draft("date-placeholder@example.com")
    _login(client, account)

    response = client.get(f"/applications/{app.pk}/")

    assert response.status_code == 200
    html = response.content.decode()
    tag = _find_input_tag(html, "member_birth_date")
    assert _attr_value(tag, "placeholder") == "DD.MM.GGGG"
    assert _attr_value(tag, "type") != "date"
    assert "Ievadiet datumu formātā DD.MM.GGGG" in html
```

- [ ] **Step 2: Add read-only template test**

Add below the editable template test:

```python
def test_read_only_member_birth_date_uses_latvian_dot_format():
    client = Client()
    account, app = _make_draft("date-readonly@example.com")
    app.status = RegistrationApplication.Status.SUBMITTED
    app.submitted_at = timezone.now()
    app.save(update_fields=["status", "submitted_at", "updated_at"])
    _login(client, account)

    response = client.get(f"/applications/{app.pk}/")

    assert response.status_code == 200
    html = response.content.decode()
    assert "01.01.2025" in html
    assert "2025-01-01" not in html
```

- [ ] **Step 3: Run red-phase template tests**

Run:

```bash
uv run pytest tests/registrations/test_application_workspace_template.py::test_member_birth_date_renders_latvian_placeholder_and_hint tests/registrations/test_application_workspace_template.py::test_read_only_member_birth_date_uses_latvian_dot_format -q
```

Expected before implementation: editable test fails because placeholder/help are missing or input is `type="date"`; read-only test fails because current display is `Y-m-d`.

### Task 3: Implement form widget and parsing

**Files:**
- Modify: `apps/registrations/forms.py`

- [ ] **Step 1: Replace `member_birth_date` definition**

Replace the current field block:

```python
    member_birth_date = forms.DateField(
        required=False,
        label="Bērna dzimšanas datums",
        error_messages={"invalid": "Ievadiet derīgu datumu."},
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
```

with:

```python
    member_birth_date = forms.DateField(
        required=False,
        label="Bērna dzimšanas datums",
        help_text="Ievadiet datumu formātā DD.MM.GGGG",
        input_formats=["%d.%m.%Y"],
        error_messages={"invalid": "Ievadiet derīgu datumu."},
        widget=forms.DateInput(attrs={"placeholder": "DD.MM.GGGG"}, format="%d.%m.%Y"),
    )
```

- [ ] **Step 2: Run targeted form tests**

Run:

```bash
uv run pytest tests/registrations/test_registration_form_contract.py::TestRegistrationFormContract::test_member_birth_date_accepts_latvian_dot_format tests/registrations/test_registration_form_contract.py::TestRegistrationFormContract::test_member_birth_date_rejects_invalid_latvian_dot_format -q
```

Expected: both pass.

### Task 4: Implement read-only date display

**Files:**
- Modify: `templates/registrations/application_workspace.html`

- [ ] **Step 1: Change read-only date format**

Replace:

```django
{{ application.member_birth_date|date:"Y-m-d" }}
```

with:

```django
{{ application.member_birth_date|date:"d.m.Y" }}
```

- [ ] **Step 2: Run targeted template tests**

Run:

```bash
uv run pytest tests/registrations/test_application_workspace_template.py::test_member_birth_date_renders_latvian_placeholder_and_hint tests/registrations/test_application_workspace_template.py::test_read_only_member_birth_date_uses_latvian_dot_format -q
```

Expected: both pass.

### Task 5: Verify integration and no schema drift

**Files:**
- No further edits expected.

- [ ] **Step 1: Run focused registration tests**

Run:

```bash
uv run pytest tests/registrations/test_registration_form_contract.py tests/registrations/test_application_workspace_template.py -q
```

Expected: all tests in both files pass.

- [ ] **Step 2: Run full verification gate**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected:
- pytest passes.
- ruff passes.
- mypy passes.
- makemigrations reports no changes.

- [ ] **Step 3: Generate critique diff URL**

Run:

```bash
bunx critique --web "Registration date format" --filter "apps/registrations/forms.py" --filter "templates/registrations/application_workspace.html" --filter "tests/registrations/test_registration_form_contract.py" --filter "tests/registrations/test_application_workspace_template.py" --filter "docs/superpowers/specs/2026-07-13-registration-date-format-design.md" --filter "docs/superpowers/plans/2026-07-13-registration-date-format.md"
```

Expected: critique prints a preview URL to share with the user.

## Plan self-review

- Spec coverage: all requested behavior maps to Tasks 1-4; final verification and no-migration check in Task 5.
- Placeholder scan: no TBD/TODO/later placeholders.
- Type consistency: uses existing `member_birth_date`, `RegistrationApplicationForm`, `_find_input_tag`, `_attr_value`, and `RegistrationApplication.Status.SUBMITTED` names.
- Scope check: one field only; no JavaScript, no model migration, no admin date fields.

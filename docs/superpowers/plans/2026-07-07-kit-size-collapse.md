# Kit Size Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse separate shirt/shorts kit-size selection into one parent-facing **Formas izmērs** field and sort sizes naturally.

**Architecture:** Reuse `RegistrationApplication.member_kit_size_shirt` as the canonical stored kit size. Keep legacy `member_kit_size_shorts` in the database for compatibility, but remove it from the parent form, validation, and current save path. Add a tiny local sort helper for size labels; no dependency or schema cleanup yet.

**Tech Stack:** Django 5, Python 3.12, pytest/pytest-django, uv, ruff, mypy.

---

## 1. Design decisions

### Data flow

Current parent form data flows:

```text
RegistrationApplicationForm.cleaned_data
  -> create_or_update_draft(data=...)
  -> RegistrationApplication.member_kit_size_shirt/member_kit_size_shorts
  -> submit_application validation
```

New flow:

```text
RegistrationApplicationForm.cleaned_data["member_kit_size_shirt"]
  -> create_or_update_draft(data=...)
  -> RegistrationApplication.member_kit_size_shirt  # canonical single kit size
  -> submit_application validates member_kit_size_shirt only
```

### Why reuse `member_kit_size_shirt`

The approved source rule is “use old shirt size”. Existing rows already hold the chosen value in `member_kit_size_shirt`, so reusing it avoids destructive migration and avoids a repo-wide schema rename. The legacy `member_kit_size_shorts` field remains stored but inactive in parent flow.

### Component boundaries

- `apps/registrations/forms.py` owns parent-form shape, labels, active choices, wizard required hooks.
- `apps/registrations/services.py` owns draft persistence and submit validation.
- `apps/registrations/views.py` owns initial values for edit/resume.
- `apps/members/models.py` owns kit option ordering at model level if the helper lives there.
- Tests pin parent-visible behavior and service contract.

### API contracts

No external API change. Internal form contract changes:

- Still post `member_kit_size_shirt` for the one size field.
- Stop posting `member_kit_size_shorts` from current parent UI.
- Legacy callers that still include `member_kit_size_shorts` should not be required for submit success.

### State model

- Canonical current state: `RegistrationApplication.member_kit_size_shirt_id`.
- Legacy state: `RegistrationApplication.member_kit_size_shorts_id`, ignored by current parent flow.
- `KitSizeOption.kind` remains because removing it requires larger migration/admin cleanup. The form should read active shirt-kind options only for now, because old data and fixtures already use shirt options as source.

---

## 2. File-by-file plan

### Files to modify

- `apps/members/models.py`
  - Add pure helper `kit_size_sort_key(label: str) -> tuple[int, int | str]` or equivalent tuple that mypy accepts.
  - Keep `KitSizeOption.Meta.ordering` unchanged or update only if safe. Prefer using helper in form code to avoid DB-specific ordering complexity.

- `apps/registrations/forms.py`
  - Remove `member_kit_size_shorts` from `section_order`.
  - Rename `member_kit_size_shirt` label to `Formas izmērs`.
  - Remove `member_kit_size_shorts` field or keep field class unreachable only if tests require. Prefer remove from form field definitions.
  - Remove `member_kit_size_shorts` from `submit_required_fields`.
  - Populate only `member_kit_size_shirt` choices.
  - Sort active shirt options with `kit_size_sort_key`.
  - Remove `member_kit_size_shorts` from `_field_step_map`.

- `apps/registrations/services.py`
  - In `create_or_update_draft`, persist only `member_kit_size_shirt` for current forms.
  - Remove or ignore shorts assignment block.
  - Update `_require_valid_kit_sizes` to require only `member_kit_size_shirt_id`.
  - Update error text to `member kit size is required before submit`.

- `apps/registrations/views.py`
  - Remove `member_kit_size_shorts` from edit form `initial` dict.
  - Keep `member_kit_size_shirt` initial value unchanged.

- Tests likely to modify:
  - `tests/registrations/test_registration_form_contract.py`
  - `tests/registrations/test_application_workspace_template.py`
  - `tests/registrations/conftest.py`
  - Any test fixtures that post both fields only because form used to require both. Update only failing current-flow tests to post canonical field.
  - Add/adjust a focused test for choice sorting.

### Files not to modify

- No schema migration unless implementation proves unavoidable.
- No CSS/template rewrite unless tests show field labels are hard-coded outside form rendering.
- No Invoice Ninja, agreement, billing, or document code.

---

## 3. Test strategy

### Framework

Use existing `pytest` + `pytest-django` tests. Write/adjust tests before implementation.

### What to test

1. Form contract
   - `member_kit_size_shirt` remains in member section.
   - `member_kit_size_shorts` is absent from member section and step-gating.
   - Visible label is `Formas izmērs`.

2. Choice ordering
   - Active options with labels `M`, `XS`, `S` render as `XS`, `S`, `M`.
   - Inactive options are excluded.

3. Draft persistence
   - Posting only `member_kit_size_shirt` saves canonical kit size.
   - Posting no shorts does not clear or require anything for current flow.

4. Submit validation
   - Missing `member_kit_size_shirt` fails.
   - Present `member_kit_size_shirt` passes kit-size validation even when shorts is absent; other required docs/fields can be mocked using existing fixtures.

5. Parent workspace rendering
   - Rendered HTML contains `Formas izmērs`.
   - Rendered HTML does not contain `Krekla izmērs` or `Šortu izmērs`.

### What not to test

- Browser visual layout beyond label presence/absence.
- Database column removal.
- Admin inventory workflows.
- Every possible custom size label; one unknown-label fallback test is enough if helper is public.

---

## 4. Acceptance criteria per unit

### Unit: form field collapse

- `RegistrationApplicationForm.section_order` has one kit-size field in the `member` section: `member_kit_size_shirt`.
- `member_kit_size_shorts` is not present in `RegistrationApplicationForm.base_fields` or is at least not rendered/required/step-gated. Prefer fully absent.
- `RegistrationApplicationForm.base_fields["member_kit_size_shirt"].label == "Formas izmērs"`.

### Unit: choice sorting

- Given active shirt options `M`, `XS`, `S`, the field choices are ordered `XS`, `S`, `M`.
- Unknown labels sort after known labels alphabetically.

### Unit: draft save

- `create_or_update_draft(... data={"member_kit_size_shirt": pk, no shorts key ...})` sets `application.member_kit_size_shirt_id == pk`.
- Service does not throw for missing `member_kit_size_shorts`.

### Unit: submit validation

- `_require_valid_kit_sizes(application)` raises when `member_kit_size_shirt_id is None`.
- It does not inspect `member_kit_size_shorts_id`.

### Unit: parent workspace

- Workspace/member section renders exactly one size label, `Formas izmērs`.
- Old size labels are absent.

---

## 5. Documentation scope

- Keep design spec: `docs/superpowers/specs/2026-07-07-kit-size-collapse-design.md`.
- This implementation plan: `docs/superpowers/plans/2026-07-07-kit-size-collapse.md`.
- Update `AGENTS.md` only if implementation changes architecture/status materially. Expected not needed for this small pre-P10 feature.

---

## 6. Bite-sized implementation tasks

### Task 1: Add red tests for form collapse and sorted choices

**Files:**
- Modify: `tests/registrations/test_registration_form_contract.py`

- [ ] **Step 1: Replace the old two-field form contract test**

Find the test that expects both `member_kit_size_shirt` and `member_kit_size_shorts` in the form/member section. Replace or add focused assertions like:

```python
def test_member_section_has_single_kit_size_field(self):
    from apps.registrations.forms import RegistrationApplicationForm

    member_fields = dict(RegistrationApplicationForm.section_order)["member"]

    assert "member_kit_size_shirt" in member_fields
    assert "member_kit_size_shorts" not in member_fields
    assert RegistrationApplicationForm.base_fields["member_kit_size_shirt"].label == "Formas izmērs"
    assert "member_kit_size_shorts" not in RegistrationApplicationForm.base_fields
```

If `base_fields` cannot be used because choices are initialized in `__init__`, instantiate `form = RegistrationApplicationForm()` and assert against `form.fields`.

- [ ] **Step 2: Add sorted choice test**

Add this test near existing `TestKitSizeOption` or form tests:

```python
@pytest.mark.django_db
def test_kit_size_choices_sort_naturally_and_exclude_inactive(self):
    from apps.members.models import KitSizeOption
    from apps.registrations.forms import RegistrationApplicationForm

    KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="M", is_active=True)
    KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="XS", is_active=True)
    KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="S", is_active=True)
    KitSizeOption.objects.create(kind=KitSizeOption.Kind.SHIRT, label="L", is_active=False)

    form = RegistrationApplicationForm()

    assert [label for _, label in form.fields["member_kit_size_shirt"].choices] == ["XS", "S", "M"]
```

- [ ] **Step 3: Run red tests**

Run:

```bash
uv run pytest tests/registrations/test_registration_form_contract.py -q
```

Expected: fails because shorts still exists and ordering is still lexical/model ordering.

### Task 2: Implement form collapse and sorting

**Files:**
- Modify: `apps/members/models.py`
- Modify: `apps/registrations/forms.py`

- [ ] **Step 1: Add tiny sort helper**

In `apps/members/models.py`, above `KitSizeOption`, add:

```python
_KIT_SIZE_ORDER = {
    "XXS": 0,
    "XS": 1,
    "S": 2,
    "M": 3,
    "L": 4,
    "XL": 5,
    "2XL": 6,
    "3XL": 7,
    "4XL": 8,
    "5XL": 9,
}


def kit_size_sort_key(label: str) -> tuple[int, int | str]:
    normalized = label.strip().upper()
    known = _KIT_SIZE_ORDER.get(normalized)
    if known is not None:
        return (0, known)
    return (1, normalized)
```

- [ ] **Step 2: Collapse form fields**

In `apps/registrations/forms.py`:

1. Remove `"member_kit_size_shorts"` from `section_order`.
2. Change field definition:

```python
member_kit_size_shirt = forms.ChoiceField(required=False, label="Formas izmērs")
```

3. Delete the `member_kit_size_shorts = forms.ChoiceField(...)` line.
4. Remove `"member_kit_size_shorts"` from `submit_required_fields`.
5. Replace choice population with:

```python
        from apps.members.models import KitSizeOption, kit_size_sort_key

        kit_opts = sorted(
            KitSizeOption.objects.filter(kind=KitSizeOption.Kind.SHIRT, is_active=True),
            key=lambda option: kit_size_sort_key(option.label),
        )
        self.fields["member_kit_size_shirt"].choices = [(str(o.pk), o.label) for o in kit_opts]
```

6. Remove the old `shorts_opts` block and `self.fields["member_kit_size_shorts"].choices = ...`.
7. Remove `"member_kit_size_shorts": "member"` from `_field_step_map`.

- [ ] **Step 3: Run form tests**

Run:

```bash
uv run pytest tests/registrations/test_registration_form_contract.py -q
```

Expected: new form tests pass; other tests may fail where they still assume shorts is required.

### Task 3: Update service and view contract

**Files:**
- Modify: `apps/registrations/services.py`
- Modify: `apps/registrations/views.py`

- [ ] **Step 1: Simplify draft kit-size persistence**

In `apps/registrations/services.py`, replace the kit-size block around lines 455-472 with:

```python
    # Kit size — member_kit_size_shirt is the canonical single "Formas izmērs" field.
    kit_size_id = data.get("member_kit_size_shirt")
    if kit_size_id is not None:
        try:
            application.member_kit_size_shirt = KitSizeOption.objects.get(pk=kit_size_id)
        except (KitSizeOption.DoesNotExist, ValueError, TypeError):
            application.member_kit_size_shirt = None
    else:
        application.member_kit_size_shirt = None
```

Do not write `member_kit_size_shorts` in current parent flow.

- [ ] **Step 2: Simplify submit kit-size validation**

Replace `_require_valid_kit_sizes` with:

```python
def _require_valid_kit_sizes(application: RegistrationApplication) -> None:
    if application.member_kit_size_shirt_id is None:
        raise ValueError("member kit size is required before submit")
```

- [ ] **Step 3: Remove shorts from initial form data**

In `apps/registrations/views.py`, remove this entry from the edit initial dict:

```python
"member_kit_size_shorts": application.member_kit_size_shorts_id,
```

Keep:

```python
"member_kit_size_shirt": application.member_kit_size_shirt_id,
```

- [ ] **Step 4: Run focused registration tests**

Run:

```bash
uv run pytest tests/registrations/test_registration_form_contract.py tests/registrations/test_application_workspace_template.py -q
```

Expected: focused tests pass or show only fixture assumptions to update in Task 4.

### Task 4: Update fixtures and current-flow tests

**Files:**
- Modify: `tests/registrations/conftest.py`
- Modify only failing test files that post `member_kit_size_shorts` as current parent-form input.

- [ ] **Step 1: Update shared submit payload**

In `tests/registrations/conftest.py`, remove `member_kit_size_shorts` from the shared `submit_payload` fixture if it represents current form submission. Keep fixture-created shorts options only if other legacy tests still need database rows.

Example target payload fragment:

```python
payload.update(
    {
        "member_kit_size_shirt": shirt_pk,
    }
)
```

- [ ] **Step 2: Update failing tests mechanically**

For tests that post both fields to exercise parent form save/submit, delete only this line:

```python
"member_kit_size_shorts": shorts_pk,
```

or equivalent.

Do not modify unrelated tests. If a test is explicitly about legacy shorts storage, keep it and adjust expected behavior only if necessary.

- [ ] **Step 3: Add/adjust workspace render assertion**

In `tests/registrations/test_application_workspace_template.py`, add or update a rendered-workspace test:

```python
def test_workspace_renders_single_kit_size_label(verified_client, draft_application):
    response = verified_client.get(draft_application.get_absolute_url())

    assert response.status_code == 200
    html = response.content.decode()
    assert "Formas izmērs" in html
    assert "Krekla izmērs" not in html
    assert "Šortu izmērs" not in html
```

If `get_absolute_url()` is unavailable on the fixture, use the existing URL pattern already used in that file.

- [ ] **Step 4: Run broader registration lane**

Run:

```bash
uv run pytest tests/registrations -q
```

Expected: registration tests pass or identify remaining current-flow posts to update.

### Task 5: Full verification

**Files:**
- No code changes unless verification finds real failures.

- [ ] **Step 1: Run full tests**

Run:

```bash
uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: no lint failures.

- [ ] **Step 3: Run type check**

Run:

```bash
uv run mypy .
```

Expected: no type failures.

- [ ] **Step 4: Check migrations**

Run:

```bash
uv run python manage.py makemigrations --check
```

Expected: no model changes detected.

---

## 7. Plan self-review

### Spec coverage

- Single field label: Task 2.
- Only one required kit size: Tasks 2 and 3.
- Old shirt source rule: design uses `member_kit_size_shirt`; no migration needed.
- Natural ordering: Tasks 1 and 2.
- No unrelated scope: file list excludes billing/agreement/docs.
- Full verification: Task 5.

### Placeholder scan

No TODO/TBD placeholders are present. All code snippets use actual paths and field names.

### Type consistency

- Canonical field is consistently `member_kit_size_shirt`.
- Legacy field is consistently `member_kit_size_shorts`.
- Helper name is consistently `kit_size_sort_key`.

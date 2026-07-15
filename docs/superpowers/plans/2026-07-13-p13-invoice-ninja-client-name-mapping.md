# P13 Invoice Ninja Client Name Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit Guardian first/family name fields, keep `full_name` as a temporary mirror, and send separate names to Invoice Ninja.

**Architecture:** `Guardian` becomes the source of truth for parent name parts. Registration, OCR, and Guardian admin write `first_name`/`family_name`; a model helper keeps the existing `full_name` column mirrored so current display surfaces continue working. Invoice Ninja reads the explicit fields for contact payloads and keeps `custom_value1` dedup unchanged.

**Tech Stack:** Django 5, Python 3.12, PostgreSQL-compatible migrations, pytest + pytest-django, ruff, mypy, uv.

---

## Design decisions

1. **Data flow**
   - Parent form posts `guardian_first_name` and `guardian_family_name`.
   - `apps.registrations.services.create_or_update_draft` writes those values to the linked `Guardian`.
   - `Guardian.sync_full_name()` writes `full_name = "{first_name} {family_name}".strip()`.
   - Existing display code keeps reading `guardian.full_name` during this step.
   - Invoice Ninja `ensure_client()` sends `contacts[0].first_name` and `contacts[0].last_name`.

2. **Component boundaries**
   - `apps.members.models.Guardian`: owns fields and mirror helper.
   - `apps.registrations.forms.RegistrationApplicationForm`: owns parent-visible field names and labels.
   - `apps.registrations.services`: owns draft save, prefill, submit-required names, manual/OCR source keys.
   - `apps.registrations.views._ocr_extracted_fields`: owns async OCR response field keys.
   - `apps.members.admin.GuardianAdminForm`: owns staff edit fields and mirror save path.
   - `apps.integrations.invoice_ninja.ensure_client`: owns external client payload.

3. **API contracts**
   - Parent form field names become `guardian_first_name` and `guardian_family_name`.
   - Compatibility alias: if old callers post `guardian_full_name`, split it once in service using the backfill rule; this keeps old tests/tools from failing abruptly.
   - `RegistrationApplication.guardian_name` still returns `guardian.full_name`.
   - Invoice Ninja payload keeps `name = guardian.full_name`, `custom_value1 = guardian.pk`, and `email = guardian.email`.

4. **State model**
   - P13 step 1 stores three Guardian name columns temporarily: `first_name`, `family_name`, `full_name` mirror.
   - Empty `family_name` remains DB-valid for legacy/backfill rows; parent submit requires it.
   - Later cleanup may drop `full_name` after all reads are converted.

---

## File-by-file plan

### Modify `apps/members/models.py`

- Add `Guardian.first_name` and `Guardian.family_name`.
- Add helpers:

```python
def split_guardian_full_name(full_name: str) -> tuple[str, str]:
    parts = str(full_name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]
```

```python
class Guardian(models.Model):
    first_name = models.CharField(max_length=255, blank=True, default="")
    family_name = models.CharField(max_length=255, blank=True, default="")
    full_name = models.CharField(max_length=255)

    def sync_full_name(self) -> None:
        self.full_name = " ".join(
            part for part in (self.first_name.strip(), self.family_name.strip()) if part
        )
```

- Keep `__str__` returning `self.full_name or str(self.pk)`.

### Create `apps/members/migrations/0010_guardian_name_parts.py`

- Add `first_name` and `family_name` fields.
- Backfill from existing `full_name` using last-token family-name rule.
- Keep `full_name` column.

### Modify `apps/members/admin.py`

- `GuardianAdminForm.Meta.fields` becomes `("first_name", "family_name", "personal_id", "address")`.
- Add labels: `Vārds`, `Uzvārds`.
- `GuardianAdmin.readonly_fields` includes `"full_name"` with `related_records`.
- `GuardianAdmin.fields` includes read-only `full_name` after explicit fields.
- `save_model()` calls `obj.sync_full_name()` before `super().save_model(...)`.
- `search_fields` may keep `full_name` and add `first_name`, `family_name`.

### Modify `apps/registrations/forms.py`

- Replace `guardian_full_name` with:

```python
guardian_first_name = forms.CharField(max_length=255, required=False, label="Vecāka vārds")
guardian_family_name = forms.CharField(max_length=255, required=False, label="Vecāka uzvārds")
```

- In `section_order`, replace `guardian_full_name` with both fields before personal ID.
- In `submit_required_fields`, replace `guardian_full_name` with both fields.
- In `_field_step_map`, map both fields to `guardian`.
- In readonly locking, lock both fields instead of old `guardian_full_name`.

### Modify `templates/registrations/application_workspace.html`

- Update lock JS list from `id_guardian_full_name` to:

```javascript
var lockableIds = [
  "id_guardian_first_name",
  "id_guardian_family_name",
  "id_guardian_personal_id",
  "id_guardian_phone",
  "id_guardian_declared_address"
];
```

### Modify `apps/registrations/models.py`

- Keep `guardian_name` returning `guardian.full_name`.
- Change `guardian_profile_populated` to require explicit fields:

```python
return bool(
    self.guardian_id is not None
    and self.guardian.first_name.strip()
    and self.guardian.family_name.strip()
)
```

### Modify `apps/registrations/services.py`

- Replace `guardian_full_name` in `REQUIRED_SUBMIT_FIELDS` with `guardian_first_name`, `guardian_family_name`.
- Update `_GUARDIAN_SUBMIT_ACCESSORS` to map both to accessors or add properties on model.
- Replace `guardian_full_name` in `MANUAL_P1_FIELDS` with both explicit fields.
- `get_application_prefill()` returns `guardian_first_name`, `guardian_family_name` from latest linked guardian.
- `_merge_ocr_extractions()` maps OCR `first_name` and `last_name` directly.
- `_set_ocr_field_sources()` sets both `guardian_first_name` and `guardian_family_name` to `ocr_guardian_identity`.
- Guardian document reuse fallback sets both fields as `manual_only` when no extraction exists.
- `create_or_update_draft()` writes `Guardian.first_name`, `Guardian.family_name`, calls `sync_full_name()`, saves `update_fields=["first_name", "family_name", "full_name", "personal_id", "address"]`.
- Add compatibility split only inside service:

```python
if "guardian_full_name" in data and (
    "guardian_first_name" not in data and "guardian_family_name" not in data
):
    first_name, family_name = split_guardian_full_name(str(data["guardian_full_name"]))
    data = dict(data)
    data["guardian_first_name"] = first_name
    data["guardian_family_name"] = family_name
```

### Modify `apps/registrations/views.py`

- In `application_workspace` initial data, replace `guardian_full_name` with `guardian_first_name` and `guardian_family_name`.
- In `_ocr_extracted_fields()`, map guardian OCR directly:

```python
if document.kind == Document.Kind.GUARDIAN_IDENTITY:
    if first:
        fields["guardian_first_name"] = first
    if last:
        fields["guardian_family_name"] = last
```

- Member OCR remains unchanged and still builds `member_full_name`.

### Modify `apps/integrations/tasks.py`

- Search `apps/integrations/tasks.py` for `guardian_full_name`. If found, replace only guardian name field mappings with `guardian_first_name` and `guardian_family_name`; leave member mappings unchanged.

### Modify `apps/integrations/invoice_ninja.py`

- Change client payload contact from whole-name first name to explicit fields:

```python
body = {
    "name": guardian.full_name,
    "custom_value1": str(guardian.pk),
    "contacts": [
        {
            "first_name": guardian.first_name,
            "last_name": guardian.family_name,
            "email": guardian.email,
        }
    ],
}
```

### Modify tests/support fixtures

- Update `tests/support.py::make_guardian` and any local Guardian factories to accept `first_name` and `family_name`, call `sync_full_name()`, and preserve `full_name=` compatibility by splitting it when explicit fields are omitted.

### Update tests

- Add/modify tests in:
  - `tests/members/test_guardian_name_parts.py`
  - `tests/members/test_guardian_admin_form.py`
  - `tests/registrations/test_guardian_profile_lock.py`
  - `tests/registrations/test_guardian_read_through.py`
  - `tests/registrations/test_parent_ocr_prefill_flow.py`
  - `tests/registrations/test_ocr_field_source_values.py`
  - `tests/integrations/test_invoice_ninja_provider.py`
  - `tests/members/test_guardian_name_parts.py` should import `apps.members.migrations.0010_guardian_name_parts` and call `backfill_guardian_name_parts(apps, None)` directly, matching the existing migration-test style in `tests/agreements/test_backfill_migration.py`.

### Update docs

- Update `docs/milestones.md` P13 status after implementation only.
- Update `docs/admin-hub.md` only if visible Guardian admin instructions mention `full_name` editing; otherwise no doc change.

---

## Test strategy

- **Framework:** pytest + pytest-django.
- **Red phase:** write tests first and run targeted commands to prove they fail before implementation.
- **Model tests:** pure split helper, `sync_full_name()`, save paths.
- **Migration tests:** backfill rule for blank, single-token, two-token, and multi-token names by importing the migration module and calling `backfill_guardian_name_parts(apps, None)` directly.
- **Form tests:** field names, labels, section order, required fields, readonly lock field IDs.
- **Service tests:** draft save updates explicit fields and mirror; legacy `guardian_full_name` alias still works.
- **OCR tests:** prior-document prefill and async upload JSON use explicit keys with existing source labels.
- **Admin tests:** Guardian change page renders `first_name`, `family_name`, read-only `full_name`; save updates mirror.
- **Integration tests:** Invoice Ninja client payload sends `first_name` and `last_name` separately.
- **What not to test:** live Invoice Ninja API; visual pixel layout; parent self-service profile page; dropping `full_name` column.

Targeted commands:

```bash
uv run pytest -q tests/members/test_guardian_name_parts.py tests/members/test_guardian_admin_form.py
uv run pytest -q tests/registrations/test_guardian_profile_lock.py tests/registrations/test_guardian_read_through.py
uv run pytest -q tests/registrations/test_parent_ocr_prefill_flow.py tests/registrations/test_ocr_field_source_values.py
uv run pytest -q tests/integrations/test_invoice_ninja_provider.py
```

Full gate:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

---

## Acceptance criteria per unit

1. **Model and migration**
   - `Guardian` has `first_name` and `family_name` columns.
   - Existing rows backfill with last token as `family_name`.
   - `Guardian.sync_full_name()` mirrors explicit fields into `full_name`.

2. **Registration flow**
   - Parent form renders `guardian_first_name` and `guardian_family_name` with Latvian labels.
   - Parent form no longer renders `guardian_full_name`.
   - Submit requires both explicit name fields.
   - Draft save writes explicit fields and mirror.

3. **OCR flow**
   - Guardian OCR `first_name` fills `guardian_first_name`.
   - Guardian OCR `last_name` fills `guardian_family_name`.
   - Existing OCR source labels still render.

4. **Admin flow**
   - Guardian admin edits `Vārds` and `Uzvārds`.
   - `Pilns vārds`/`full_name` is shown read-only or as existing admin label but not the primary editable source.
   - Save updates `full_name` mirror.
   - Email/phone remain ParentAccount-owned.

5. **Invoice Ninja**
   - Client contact payload uses explicit `first_name` and `last_name`.
   - Client `name` and `custom_value1` behavior stays unchanged.

6. **Docs and verification**
   - P13 milestone updated only after implementation passes gates.
   - Full gate commands pass.

---

## Task 1: Model fields, mirror helper, and backfill tests

**Files:**
- Modify: `apps/members/models.py`
- Create: `apps/members/migrations/0010_guardian_name_parts.py`
- Create/modify: `tests/members/test_guardian_name_parts.py`
- Modify: `tests/support.py` if it defines `make_guardian`
- Modify: `tests/conftest.py` and `tests/registrations/conftest.py` only if grep shows direct Guardian factory code there

- [ ] **Step 1: Write failing model-helper tests**

Create `tests/members/test_guardian_name_parts.py`:

```python
import pytest

from apps.members.models import Guardian, split_guardian_full_name

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("full_name", "expected"),
    [
        ("", ("", "")),
        ("   ", ("", "")),
        ("Jānis", ("Jānis", "")),
        ("Jānis Kalniņš", ("Jānis", "Kalniņš")),
        ("Anna Marija Ozola", ("Anna Marija", "Ozola")),
        ("  Anna   Marija   Ozola  ", ("Anna Marija", "Ozola")),
    ],
)
def test_split_guardian_full_name_last_token_is_family_name(full_name, expected):
    assert split_guardian_full_name(full_name) == expected


def test_sync_full_name_joins_explicit_fields(parent_account):
    guardian = Guardian(
        parent_account=parent_account,
        first_name="Anna Marija",
        family_name="Ozola",
    )
    guardian.sync_full_name()
    assert guardian.full_name == "Anna Marija Ozola"


def test_sync_full_name_strips_blank_parts(parent_account):
    guardian = Guardian(parent_account=parent_account, first_name="Jānis", family_name="")
    guardian.sync_full_name()
    assert guardian.full_name == "Jānis"
```

- [ ] **Step 2: Run red test**

Run:

```bash
uv run pytest -q tests/members/test_guardian_name_parts.py
```

Expected: FAIL because `split_guardian_full_name`, `Guardian.first_name`, `Guardian.family_name`, and `sync_full_name()` do not exist.

- [ ] **Step 3: Implement minimal model code**

In `apps/members/models.py`, add helper near `kit_size_sort_key()` and fields/method on `Guardian`:

```python
def split_guardian_full_name(full_name: str) -> tuple[str, str]:
    parts = str(full_name).split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]
```

```python
class Guardian(models.Model):
    first_name = models.CharField(max_length=255, blank=True, default="")
    family_name = models.CharField(max_length=255, blank=True, default="")
    full_name = models.CharField(max_length=255)
    personal_id = models.CharField(max_length=32, blank=True, default="")
    address = models.CharField(max_length=255, blank=True, default="")
    external_client_id = models.CharField(max_length=64, blank=True, default="")

    def sync_full_name(self) -> None:
        self.first_name = self.first_name.strip()
        self.family_name = self.family_name.strip()
        self.full_name = " ".join(part for part in (self.first_name, self.family_name) if part)
```

- [ ] **Step 4: Create migration**

Run:

```bash
uv run python manage.py makemigrations members
```

Then edit generated migration to include `RunPython` backfill after the two `AddField` operations:

```python
def split_name(full_name):
    parts = str(full_name or "").split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return " ".join(parts[:-1]), parts[-1]


def backfill_guardian_name_parts(apps, schema_editor):
    Guardian = apps.get_model("members", "Guardian")
    for guardian in Guardian.objects.all().only("pk", "full_name"):
        first_name, family_name = split_name(guardian.full_name)
        guardian.first_name = first_name
        guardian.family_name = family_name
        guardian.save(update_fields=["first_name", "family_name"])
```

- [ ] **Step 5: Run model tests**

Run:

```bash
uv run pytest -q tests/members/test_guardian_name_parts.py
```

Expected: PASS.

---

## Task 2: Registration form, lock UI, and draft-save service

**Files:**
- Modify: `apps/registrations/forms.py`
- Modify: `apps/registrations/models.py`
- Modify: `apps/registrations/services.py`
- Modify: `apps/registrations/views.py`
- Modify: `templates/registrations/application_workspace.html`
- Test: `tests/registrations/test_guardian_profile_lock.py`
- Test: `tests/registrations/test_guardian_read_through.py`
- Add/modify: `tests/registrations/test_guardian_name_fields.py`

- [ ] **Step 1: Write failing form/service tests**

Create `tests/registrations/test_guardian_name_fields.py`:

```python
import pytest

from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db


def test_form_uses_explicit_guardian_name_fields():
    form = RegistrationApplicationForm()
    assert "guardian_first_name" in form.fields
    assert "guardian_family_name" in form.fields
    assert "guardian_full_name" not in form.fields
    assert form.fields["guardian_first_name"].label == "Vecāka vārds"
    assert form.fields["guardian_family_name"].label == "Vecāka uzvārds"


def test_submit_requires_both_guardian_name_fields():
    assert "guardian_first_name" in RegistrationApplicationForm.submit_required_fields
    assert "guardian_family_name" in RegistrationApplicationForm.submit_required_fields
    assert "guardian_full_name" not in RegistrationApplicationForm.submit_required_fields


def test_draft_save_writes_guardian_name_parts_and_mirror(parent_account):
    data = {
        "guardian_email": parent_account.email,
        "guardian_first_name": "Anna Marija",
        "guardian_family_name": "Ozola",
        "guardian_personal_id": "010180-12345",
        "guardian_phone": "+37120000000",
        "guardian_declared_address": "Cēsis",
    }
    app = create_or_update_draft(data=data, files={}, verified_account=parent_account)
    guardian = app.guardian
    guardian.refresh_from_db()
    assert guardian.first_name == "Anna Marija"
    assert guardian.family_name == "Ozola"
    assert guardian.full_name == "Anna Marija Ozola"


def test_draft_save_accepts_legacy_guardian_full_name_alias(parent_account):
    app = create_or_update_draft(
        data={
            "guardian_email": parent_account.email,
            "guardian_full_name": "Jānis Kalniņš",
        },
        files={},
        verified_account=parent_account,
    )
    app.guardian.refresh_from_db()
    assert app.guardian.first_name == "Jānis"
    assert app.guardian.family_name == "Kalniņš"
    assert app.guardian.full_name == "Jānis Kalniņš"
```

- [ ] **Step 2: Run red tests**

Run:

```bash
uv run pytest -q tests/registrations/test_guardian_name_fields.py tests/registrations/test_guardian_profile_lock.py
```

Expected: FAIL on old form field names and missing model fields if Task 1 not done.

- [ ] **Step 3: Update form field contract**

In `apps/registrations/forms.py`:

```python
guardian_first_name = forms.CharField(max_length=255, required=False, label="Vecāka vārds")
guardian_family_name = forms.CharField(max_length=255, required=False, label="Vecāka uzvārds")
```

Replace `guardian_full_name` in `section_order`, `submit_required_fields`, `_field_step_map`, and readonly lock tuple with both explicit fields.

- [ ] **Step 4: Update application model profile-populated signal**

In `apps/registrations/models.py`:

```python
@property
def guardian_profile_populated(self) -> bool:
    return bool(
        self.guardian_id is not None
        and self.guardian.first_name.strip()
        and self.guardian.family_name.strip()
    )
```

- [ ] **Step 5: Update services**

In `apps/registrations/services.py` import splitter:

```python
from apps.members.models import KitSizeOption, Member, TrainingGroup, split_guardian_full_name
```

Update constants:

```python
REQUIRED_SUBMIT_FIELDS = (
    "guardian_first_name",
    "guardian_family_name",
    "guardian_personal_id",
    "guardian_email",
    "guardian_phone",
    "guardian_declared_address",
    ...
)

_GUARDIAN_SUBMIT_ACCESSORS = {
    "guardian_first_name": "guardian_first_name",
    "guardian_family_name": "guardian_family_name",
    ...
}

MANUAL_P1_FIELDS = (
    "guardian_first_name",
    "guardian_family_name",
    ...
)
```

Add read properties on `RegistrationApplication` if needed:

```python
@property
def guardian_first_name(self) -> str:
    return str(self.guardian.first_name) if self.guardian_id is not None else ""

@property
def guardian_family_name(self) -> str:
    return str(self.guardian.family_name) if self.guardian_id is not None else ""
```

In `create_or_update_draft()`, before Guardian write:

```python
if "guardian_full_name" in data and (
    "guardian_first_name" not in data and "guardian_family_name" not in data
):
    first_name, family_name = split_guardian_full_name(str(data["guardian_full_name"]))
    data = dict(data)
    data["guardian_first_name"] = first_name
    data["guardian_family_name"] = family_name
```

Replace Guardian write block:

```python
_guardian.first_name = str(data.get("guardian_first_name", "")).strip()
_guardian.family_name = str(data.get("guardian_family_name", "")).strip()
_guardian.sync_full_name()
_guardian.personal_id = str(data.get("guardian_personal_id", "")).strip()
_guardian.address = str(data.get("guardian_declared_address", "")).strip()
_guardian.save(update_fields=["first_name", "family_name", "full_name", "personal_id", "address"])
```

- [ ] **Step 6: Update initial data and lock JS**

In `apps/registrations/views.py`, wherever initial data sets `guardian_full_name`, set explicit fields from application/guardian:

```python
"guardian_first_name": application.guardian_first_name,
"guardian_family_name": application.guardian_family_name,
```

In `templates/registrations/application_workspace.html`, update lockable field IDs to explicit names.

- [ ] **Step 7: Run targeted tests**

Run:

```bash
uv run pytest -q tests/registrations/test_guardian_name_fields.py tests/registrations/test_guardian_profile_lock.py tests/registrations/test_guardian_read_through.py
```

Expected: PASS after replacing every guardian-name form assertion with `guardian_first_name` and `guardian_family_name`. Keep member `member_full_name` assertions unchanged.

---

## Task 3: OCR mapping and source labels

**Files:**
- Modify: `apps/registrations/services.py`
- Modify: `apps/registrations/views.py`
- Modify: `apps/integrations/tasks.py` only when grep finds `guardian_full_name` mappings
- Test: `tests/registrations/test_parent_ocr_prefill_flow.py`
- Test: `tests/registrations/test_ocr_field_source_values.py`
- Test: `tests/registrations/test_ocr_source_presentation.py`

- [ ] **Step 1: Write failing OCR mapping assertions**

Add/adjust tests to assert guardian OCR response uses explicit fields:

```python
def test_guardian_ocr_async_fields_use_explicit_name_parts(draft_with_documents):
    from apps.registrations.views import _ocr_extracted_fields
    from apps.documents.models import Document

    doc = draft_with_documents.documents.get(kind=Document.Kind.GUARDIAN_IDENTITY)
    fields = _ocr_extracted_fields(doc)
    assert "guardian_first_name" in fields
    assert "guardian_family_name" in fields
    assert "guardian_full_name" not in fields
```

Add/adjust field-source test:

```python
def test_guardian_ocr_source_keys_use_explicit_name_parts(application_with_guardian_ocr):
    sources = application_with_guardian_ocr.field_sources
    assert sources["guardian_first_name"] == "ocr_guardian_identity"
    assert sources["guardian_family_name"] == "ocr_guardian_identity"
    assert "guardian_full_name" not in sources
```

- [ ] **Step 2: Run red OCR tests**

Run:

```bash
uv run pytest -q tests/registrations/test_parent_ocr_prefill_flow.py tests/registrations/test_ocr_field_source_values.py tests/registrations/test_ocr_source_presentation.py
```

Expected: FAIL where old `guardian_full_name` key is still used.

- [ ] **Step 3: Update OCR prefill in services**

In `_merge_ocr_extractions()`:

```python
if fn:
    result["guardian_first_name"] = fn
if ln:
    result["guardian_family_name"] = ln
```

In `_set_ocr_field_sources()` guardian branch:

```python
sources["guardian_first_name"] = "ocr_guardian_identity"
sources["guardian_family_name"] = "ocr_guardian_identity"
sources["guardian_personal_id"] = "ocr_guardian_identity"
```

In reusable-document fallback:

```python
sources["guardian_first_name"] = "manual_only"
sources["guardian_family_name"] = "manual_only"
sources["guardian_personal_id"] = "manual_only"
```

- [ ] **Step 4: Update async OCR field response**

In `apps/registrations/views.py::_ocr_extracted_fields()`:

```python
if document.kind == Document.Kind.GUARDIAN_IDENTITY:
    if first:
        fields["guardian_first_name"] = first
    if last:
        fields["guardian_family_name"] = last
    if pid:
        fields["guardian_personal_id"] = pid
```

Keep member branch building `member_full_name`.

- [ ] **Step 5: Check OCR job mapping**

Search `apps/integrations/tasks.py` for `guardian_full_name`. If matches exist, replace guardian mappings with explicit name keys, preserving member mappings. If no matches exist, record that no integration-task change was needed in the implementation summary.

- [ ] **Step 6: Run OCR tests**

Run:

```bash
uv run pytest -q tests/registrations/test_parent_ocr_prefill_flow.py tests/registrations/test_ocr_field_source_values.py tests/registrations/test_ocr_source_presentation.py
```

Expected: PASS.

---

## Task 4: Guardian admin explicit fields

**Files:**
- Modify: `apps/members/admin.py`
- Test: `tests/members/test_guardian_admin_form.py`
- Test: `tests/members/test_admin_guardian_search.py`
- Test: `tests/admin_hub/test_guardian_changelist.py`

- [ ] **Step 1: Update failing admin tests**

In `tests/members/test_guardian_admin_form.py`, change POST bodies from `full_name` editable input to explicit fields:

```python
resp = c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
    "first_name": "Anna",
    "family_name": "Ozola",
    "personal_id": "",
    "address": "",
    "email": "old@example.com",
    "phone": "+37100099",
    "is_active": "",
})
```

Add:

```python
def test_save_writes_name_parts_and_full_name_mirror():
    g = _guardian()
    c = _staff_client()
    resp = c.post(reverse("admin:members_guardian_change", args=[g.pk]), {
        "first_name": "Anna Marija",
        "family_name": "Ozola",
        "personal_id": "",
        "address": "",
        "email": "old@example.com",
        "phone": "+371",
        "is_active": "on",
    })
    assert resp.status_code == 302
    g.refresh_from_db()
    assert g.first_name == "Anna Marija"
    assert g.family_name == "Ozola"
    assert g.full_name == "Anna Marija Ozola"
```

- [ ] **Step 2: Run red admin tests**

Run:

```bash
uv run pytest -q tests/members/test_guardian_admin_form.py tests/members/test_admin_guardian_search.py tests/admin_hub/test_guardian_changelist.py
```

Expected: FAIL until admin form uses explicit fields.

- [ ] **Step 3: Update admin form and save**

In `apps/members/admin.py`:

```python
class GuardianAdminForm(forms.ModelForm):
    email = forms.EmailField(label="E-pasts (pieslēgšanās)", required=True)
    phone = forms.CharField(label="Tālrunis", max_length=20, required=False)
    is_active = forms.BooleanField(label="Konts aktīvs", required=False)

    class Meta:
        model = Guardian
        fields = ("first_name", "family_name", "personal_id", "address")
        labels = {
            "first_name": "Vārds",
            "family_name": "Uzvārds",
        }
```

Update `GuardianAdmin`:

```python
search_fields = ("full_name", "first_name", "family_name", "parent_account__email", "personal_id")
readonly_fields = ("related_records", "full_name")
fields = (
    "related_records",
    "first_name",
    "family_name",
    "full_name",
    "personal_id",
    "address",
    "email",
    "phone",
    "is_active",
)
```

In `save_model()` before `super()`:

```python
obj.sync_full_name()
super().save_model(request, obj, form, change)
```

- [ ] **Step 4: Run admin tests**

Run:

```bash
uv run pytest -q tests/members/test_guardian_admin_form.py tests/members/test_admin_guardian_search.py tests/admin_hub/test_guardian_changelist.py
```

Expected: PASS.

---

## Task 5: Invoice Ninja client payload

**Files:**
- Modify: `apps/integrations/invoice_ninja.py`
- Test: `tests/integrations/test_invoice_ninja_provider.py`

- [ ] **Step 1: Write failing payload test**

Add test:

```python
@override_settings(**INVOICE_NINJA)
def test_ensure_client_posts_name_parts(parent_account, make_guardian):
    from apps.integrations import invoice_ninja

    guardian = make_guardian(
        parent_account,
        first_name="Anna Marija",
        family_name="Ozola",
    )
    lookup = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")
    created = SimpleNamespace(status_code=200, json=lambda: {"id": "client-99"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, created],
    ) as m:
        result = invoice_ninja.ensure_client(guardian)

    assert result.external_id == "client-99"
    body = m.call_args.kwargs["json"]
    assert body["name"] == "Anna Marija Ozola"
    assert body["custom_value1"] == str(guardian.pk)
    assert body["contacts"] == [
        {
            "first_name": "Anna Marija",
            "last_name": "Ozola",
            "email": parent_account.email,
        }
    ]
```

- [ ] **Step 2: Run red test**

Run:

```bash
uv run pytest -q tests/integrations/test_invoice_ninja_provider.py::test_ensure_client_posts_name_parts
```

Expected: FAIL because current code sends whole name as contact first name and no last name.

- [ ] **Step 3: Update payload**

In `apps/integrations/invoice_ninja.py::ensure_client()`:

```python
body = {
    "name": guardian.full_name,
    "custom_value1": str(guardian.pk),
    "contacts": [
        {
            "first_name": guardian.first_name,
            "last_name": guardian.family_name,
            "email": guardian.email,
        }
    ],
}
```

- [ ] **Step 4: Run integration provider tests**

Run:

```bash
uv run pytest -q tests/integrations/test_invoice_ninja_provider.py
```

Expected: PASS.

---

## Task 6: Fixture and old-test sweep

**Files:**
- Modify: `tests/support.py`
- Modify: `tests/conftest.py` or `tests/registrations/conftest.py` if they create guardians directly
- Modify any failing tests found by targeted grep

- [ ] **Step 1: Search old field use**

Run:

```bash
rg "guardian_full_name|id_guardian_full_name|full_name=\".*\".*Guardian|Guardian\.objects\.create" tests apps templates
```

Expected: list of old tests/code to update. Do not replace member `full_name` or display-only `guardian.full_name` reads.

- [ ] **Step 2: Update helper factory**

In `tests/support.py::make_guardian`, support explicit names and full-name compatibility:

```python
def make_guardian(parent_account, *, first_name="", family_name="", full_name="", **kwargs):
    from apps.members.models import Guardian, split_guardian_full_name

    if full_name and not (first_name or family_name):
        first_name, family_name = split_guardian_full_name(full_name)
    guardian = Guardian(
        parent_account=parent_account,
        first_name=first_name,
        family_name=family_name,
        **kwargs,
    )
    guardian.sync_full_name()
    guardian.save()
    return guardian
```

Adjust exact signature to match existing helper; preserve existing kwargs like `personal_id`, `address`, `external_client_id`.

- [ ] **Step 3: Update direct Guardian test factories**

For tests that do:

```python
Guardian.objects.create(full_name="Anna Ozola", parent_account=acc)
```

replace with:

```python
g = Guardian(parent_account=acc, first_name="Anna", family_name="Ozola")
g.sync_full_name()
g.save()
```

or use `make_guardian(acc, first_name="Anna", family_name="Ozola")`.

- [ ] **Step 4: Run broad related tests**

Run:

```bash
uv run pytest -q tests/members tests/registrations tests/integrations/test_invoice_ninja_provider.py
```

Expected: PASS or failures only in unrelated slow/external tests. Fix P13-related failures before moving on.

---

## Task 7: Docs and milestone update

**Files:**
- Modify: `docs/milestones.md`
- Modify if needed: `docs/admin-hub.md`

- [ ] **Step 1: Update milestone status**

After implementation and targeted tests pass, update `docs/milestones.md` P13 section:

```markdown
### P13 — Invoice Ninja client name mapping
**Status:** dev complete (2026-07-13)
```

Add delivered bullets:

```markdown
**Delivered**
- `Guardian.first_name` and `Guardian.family_name` added with safe backfill from `full_name`; `full_name` remains a temporary mirror.
- Registration, OCR, and Guardian admin write explicit parent name fields.
- Invoice Ninja client contact payload sends separate first-name and family-name values.
- Existing display surfaces continue reading the mirrored full name.
```

Do not mark LAN accepted unless a separate LAN pass happened.

- [ ] **Step 2: Update admin guide only if needed**

If `docs/admin-hub.md` mentions editing the parent full-name field, update it to `Vārds` / `Uzvārds`. If it only mentions display, leave it alone.

---

## Task 8: Full verification

**Files:** no source changes unless failures reveal P13 bugs.

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run lint**

```bash
uv run ruff check .
```

Expected: PASS.

- [ ] **Step 3: Run type check**

```bash
uv run mypy .
```

Expected: PASS.

- [ ] **Step 4: Check migrations**

```bash
uv run python manage.py makemigrations --check
```

Expected: `No changes detected`.

- [ ] **Step 5: Generate diff URL**

```bash
bunx critique --web "P13 Invoice Ninja client name mapping"
```

Expected: critique URL printed; share it with the user.

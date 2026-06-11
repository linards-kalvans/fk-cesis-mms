# Canonical Guardian Identity — Slice B2 (drop columns) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the five denormalized `guardian_*` columns from `RegistrationApplication`, making the canonical `Guardian`/`ParentAccount` the sole source of guardian data.

**Architecture:** Contract phase of expand/contract. Order chosen to stay green at every commit: (1) **sweep the tests** so no test constructs `RegistrationApplication` with `guardian_*=` kwargs and no test asserts a guardian value off an unpopulated Guardian — done while the columns still exist (omitting a `guardian_email` kwarg writes `""`, so this is safe); (2) **production** — stop writing the columns (the Guardian is written from `data` at draft-save), validate submit via the read accessors, simplify the accessors to drop the column fallback, fix `__str__` + admin; (3) **migration** — drop the five columns; (4) carryover review items + gate + docs.

**Tech Stack:** Python 3.12 / Django 5.x, pytest + pytest-django, uv, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-06-09-p6-canonical-guardian-identity-design.md` (§4 — drop the five `guardian_*` fields). Slice B1 added the read accessors (`guardian_name`, `guardian_pid`, `guardian_contact_phone`, `guardian_address`, `guardian_contact_email`), populated the Guardian at draft-save, and repointed all reads. B2 finishes the job.

---

## Background the implementer needs

- The five columns: `RegistrationApplication.guardian_full_name`, `guardian_personal_id`, `guardian_email` (NOT NULL `EmailField`), `guardian_phone`, `guardian_declared_address` (models.py lines ~47-51).
- The read accessors already exist and currently fall back to those columns. After B2 they read the Guardian/ParentAccount only.
- **Form fields keep their names** (`guardian_email`, `guardian_full_name`, …) — they are `forms.Form` fields, not model fields. POST-dict keys, `field_sources` JSON keys, and the `get_application_prefill` dict keys all use these names and STAY. Only *model column* reads/writes change.
- **Why the sweep is safe before the drop:** a `CharField`/`EmailField` omitted from `.objects.create()` is stored as `""` (Django's empty-string default), so removing a `guardian_email=...` filler kwarg does not violate the NOT NULL constraint while the column still exists.
- Test classification (from inventory):
  - **Filler pattern (drop the kwarg):** tests that pass only `guardian_email=...` (or a couple of guardian kwargs) just to populate a row, and do NOT assert guardian display/prefill. Fix = delete the guardian `*=` kwargs from the constructor.
  - **Populated-guardian pattern (link a Guardian):** tests that pass guardian profile kwargs AND assert a guardian value through an accessor/template/prefill. Fix = create a `Guardian` (linked to the app's `parent_account`, with the profile fields) and pass `guardian=<that>` to the constructor instead of the `guardian_*` columns.
- A helper from Task 1 makes the populated-guardian pattern DRY.

## File Structure

- **Modify** `tests/conftest.py` — add `make_guardian` helper fixture (Task 1).
- **Modify** ~24 test files across `tests/billing/`, `tests/agreements/`, `tests/documents/`, `tests/integrations/`, `tests/registrations/` (Tasks 2-4).
- **Modify** `apps/registrations/services.py` — `create_or_update_draft` (stop column writes; Guardian-populate from `data`), `_require_complete_application` (validate via accessors) (Task 5).
- **Modify** `apps/registrations/models.py` — simplify the 5 accessors, fix `__str__`; remove the 5 field declarations (Tasks 6, 7).
- **Modify** `apps/registrations/admin.py` — `list_display` + `search_fields` (Task 6).
- **Create** migration `apps/registrations/migrations/0010_*.py` (Task 7).
- **Modify** `apps/registrations/views.py` — `select_related("parent_account")` carryover (Task 8).

---

## Task 1: `make_guardian` test helper

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_make_guardian_helper_links_a_populated_guardian(make_guardian):
    account = ParentAccount.objects.create(email="helper@example.com")
    guardian = make_guardian(account, full_name="Helper Name", personal_id="010101-12345",
                             phone="+37120000000", address="Helper Addr")
    assert guardian.parent_account_id == account.id
    assert guardian.full_name == "Helper Name"
    assert guardian.email == "helper@example.com"  # mirrored from the account
    app = RegistrationApplication.objects.create(parent_account=account, guardian=guardian)
    assert app.guardian_name == "Helper Name"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_make_guardian_helper_links_a_populated_guardian -v`
Expected: FAIL — `fixture 'make_guardian' not found`.

- [ ] **Step 3: Add the helper fixture**

In `tests/conftest.py`, add:

```python
@pytest.fixture
def make_guardian(db):
    """Create a Guardian linked to a ParentAccount with a populated profile.

    Use in tests that previously set guardian_* columns on RegistrationApplication
    and assert guardian values through the read accessors.
    """
    from apps.members.models import Guardian

    def _make(account, *, full_name="", personal_id="", phone="", address=""):
        return Guardian.objects.create(
            parent_account=account,
            email=account.email,
            full_name=full_name,
            personal_id=personal_id,
            phone=phone,
            address=address,
        )

    return _make
```

(If `tests/conftest.py` does not already `import pytest`, add it at the top.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_make_guardian_helper_links_a_populated_guardian -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/registrations/test_guardian_read_through.py
git commit -m "test: make_guardian helper for the B2 fixture sweep (P6 Slice B2)"
```

---

## The sweep transformation rule (Tasks 2-4)

For every `RegistrationApplication(...)` / `RegistrationApplication.objects.create(...)` call that passes any of `guardian_full_name=`, `guardian_personal_id=`, `guardian_email=`, `guardian_phone=`, `guardian_declared_address=`:

- **If the test does NOT assert a guardian value** (the kwargs were row-fillers): delete those `guardian_*=` kwargs from the constructor. (The row still inserts; omitted char columns default to `""`.) If the call relied on `guardian_email` to identify the account, set `parent_account=<account>` and/or `claimed_email=<email>` instead as appropriate.
- **If the test DOES assert a guardian value** (via `app.guardian_name`/`guardian_pid`/etc., a rendered template, or `get_application_prefill`): create a populated Guardian with the helper and link it:
  ```python
  guardian = make_guardian(account, full_name="…", personal_id="…", phone="…", address="…")
  app = RegistrationApplication.objects.create(parent_account=account, guardian=guardian, …)
  ```
  Move the old `guardian_full_name=…` value into `make_guardian(full_name=…)`, etc. The verified email comes from `account.email` (no `guardian_email=` kwarg).

**Do NOT change** `data={...}` dicts passed to `create_or_update_draft` / form POSTs / `client.post(...)` — those keys are form field names and stay. Only change **model constructor kwargs**.

**Per-task verification:** after editing a file, run that file green; then `grep -nE "guardian_(full_name|personal_id|email|phone|declared_address)=" <file>` must return nothing (no constructor kwargs left). If a file mixes patterns and you are unsure whether a value is asserted, read the assertions in that test before choosing the rule — do not guess; if still unclear, STOP and report BLOCKED naming the test.

---

## Task 2: Sweep `tests/billing/` + `tests/agreements/`

**Files (all single `guardian_email=` filler — apply the drop-the-kwarg rule; add `parent_account=`/`claimed_email=` only if the test needs to identify the account):**
- `tests/billing/test_backfill_billing.py`
- `tests/billing/test_billing_admin.py`
- `tests/billing/test_billing_presentation.py`
- `tests/billing/test_billing_registration_fields.py`
- `tests/billing/test_billing_trigger.py`
- `tests/billing/test_create_draft.py`
- `tests/billing/test_discount_engine.py`
- `tests/billing/test_signed_completed_trigger.py`
- `tests/agreements/test_backfill_migration.py`

- [ ] **Step 1: Apply the sweep rule** to each file above (see "The sweep transformation rule"). These are filler removals; none assert guardian values.

- [ ] **Step 2: Verify each file green + no kwargs remain**

Run: `uv run pytest tests/billing/ tests/agreements/ -q`
Expected: PASS.
Run: `grep -rnE "guardian_(full_name|personal_id|email|phone|declared_address)=" tests/billing/ tests/agreements/`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add tests/billing/ tests/agreements/
git commit -m "test(billing,agreements): drop guardian_* constructor kwargs (P6 Slice B2)"
```

---

## Task 3: Sweep `tests/documents/` + `tests/integrations/`

**Files:**
- `tests/documents/test_admin_document_access.py` (1 — filler)
- `tests/documents/test_admin_re_ocr_action.py` (5 — likely fixture rows; apply the rule per call: filler-drop unless a guardian value is asserted)
- `tests/integrations/test_ocr_tasks.py` (5 — apply the rule per call)
- `tests/documents/test_guardian_document_reuse.py` and `tests/documents/test_ocr_extraction_models.py` IF they contain `guardian_*=` constructor kwargs (grep them; the earlier inventory flagged guardian-doc-reuse heavily — verify and sweep if present)

- [ ] **Step 1: Grep the documents/integrations trees to confirm the full file set**

Run: `grep -rlnE "guardian_(full_name|personal_id|email|phone|declared_address)=" tests/documents/ tests/integrations/`
Apply the sweep rule to every file returned.

- [ ] **Step 2: Apply the sweep rule** to each. For OCR tests that upload a guardian identity doc and assert extracted guardian fields land on the workspace/prefill, that assertion goes through `create_or_update_draft` + accessors — those tests typically build the app via the service, not via `guardian_*=` constructor kwargs, so only the *constructor* kwargs change.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/documents/ tests/integrations/ -q`
Expected: PASS.
Run: `grep -rnE "guardian_(full_name|personal_id|email|phone|declared_address)=" tests/documents/ tests/integrations/`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add tests/documents/ tests/integrations/
git commit -m "test(documents,integrations): drop guardian_* constructor kwargs (P6 Slice B2)"
```

---

## Task 4: Sweep `tests/registrations/`

**Files (mixed — apply the rule per call; the multi-kwarg ones generally assert guardian values, so use `make_guardian`):**
- `tests/registrations/test_new_app_prefill_from_extraction.py` (12 — populated-guardian)
- `tests/registrations/test_document_status_endpoint.py` (10 — likely filler fixtures)
- `tests/registrations/test_ocr_source_presentation.py` (5 — populated-guardian)
- `tests/registrations/test_submit_while_ocr_pending.py` (5 — filler)
- `tests/registrations/test_async_document_upload.py` (5 — filler)
- `tests/registrations/test_parent_ocr_prefill_flow.py` (4 — populated-guardian)
- `tests/registrations/test_personal_data_consent_flow.py` (4 — mix)
- `tests/registrations/test_guardian_dedup.py` (1)
- `tests/registrations/test_parent_edit_permissions.py` (1)
- `tests/registrations/test_portal_polish.py` (1)
- `tests/registrations/test_parent_surface_copy_contract.py` (1)

**Plus `tests/registrations/test_guardian_read_through.py`** — this is the Slice B1 test file and needs special handling because some of its tests assert the column FALLBACK that B2 removes:
- DELETE `test_accessors_fall_back_to_columns_when_guardian_profile_empty` (the fallback no longer exists).
- In `test_accessors_prefer_guardian_when_profile_populated`, `test_linked_guardian_is_source_even_when_field_empty`, and `test_email_accessor_prefers_parent_account_over_column`: remove the `guardian_*=` *column* kwargs from the `RegistrationApplication.objects.create(...)` calls (keep the `parent_account=`/`guardian=` links and the assertions, which test that the Guardian/ParentAccount is the source). The "stale column" framing in those tests is obsolete — they now just assert the accessor returns the linked Guardian/ParentAccount value.
- Keep all the draft-save / propagation / approval-no-clobber tests (they build via `create_or_update_draft` and stay valid).

- [ ] **Step 1: Apply the sweep rule** to each registrations file. Use `make_guardian` for the populated-guardian cases. Handle `test_guardian_read_through.py` per the bullets above.

- [ ] **Step 2: Verify**

Run: `uv run pytest tests/registrations/ -q`
Expected: PASS.
Run: `grep -rnE "guardian_(full_name|personal_id|email|phone|declared_address)=" tests/registrations/`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add tests/registrations/
git commit -m "test(registrations): drop guardian_* constructor kwargs; retire fallback tests (P6 Slice B2)"
```

- [ ] **Step 4: Whole-suite checkpoint (columns still present)**

Run: `uv run pytest -q`
Expected: PASS. A repo-wide grep now shows the only `guardian_(full_name|personal_id|email|phone|declared_address)=` hits are NOT model constructor kwargs:
Run: `grep -rnE "RegistrationApplication\(|\.objects\.create\(" tests/ | head` is not needed; instead confirm: `grep -rnE "guardian_(full_name|personal_id|email|phone|declared_address)=" tests/` returns no model-constructor lines (any remaining hits must be `data={...}`/POST dict keys — there should be none of the `=` form left). If any constructor kwarg remains, fix it before proceeding.

---

## Task 5: Production — stop writing columns; validate submit via accessors

**Files:**
- Modify: `apps/registrations/services.py` (`create_or_update_draft`, `_require_complete_application`)
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_draft_save_writes_guardian_not_columns(make_guardian):
    """create_or_update_draft populates the Guardian from form data; the
    application's guardian_* columns are no longer written."""
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="nocol@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Form Name",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "Form Addr"},
        files={}, verified_account=account,
    )
    guardian = app.guardian
    assert guardian.full_name == "Form Name"
    assert guardian.personal_id == "010101-12345"
    assert guardian.phone == "+37120000000"
    assert guardian.address == "Form Addr"
```

(This test passes today too, but guards the behavior once the column writes are gone. It mainly documents intent; the real proof is the full suite staying green after the column writes + column reads in `_require_complete_application` are removed.)

- [ ] **Step 2: Stop the column writes + populate the Guardian from `data`**

In `create_or_update_draft`, REMOVE the five column-write lines:
```python
    application.guardian_full_name = str(data.get("guardian_full_name", "")).strip()
    application.guardian_personal_id = str(data.get("guardian_personal_id", "")).strip()
    application.guardian_email = email
    application.guardian_phone = str(data.get("guardian_phone", "")).strip()
    application.guardian_declared_address = str(data.get("guardian_declared_address", "")).strip()
```
and change the Guardian-populate block (added in B1) to read from `data` instead of the (now-unwritten) columns:
```python
    # Populate the canonical Guardian profile from the submitted form data.
    # Email stays sourced from ParentAccount.
    if application.guardian_id is not None:
        _guardian = application.guardian
        _guardian.full_name = str(data.get("guardian_full_name", "")).strip()
        _guardian.personal_id = str(data.get("guardian_personal_id", "")).strip()
        _guardian.phone = str(data.get("guardian_phone", "")).strip()
        _guardian.address = str(data.get("guardian_declared_address", "")).strip()
        _guardian.save(update_fields=["full_name", "personal_id", "phone", "address"])
```
Leave the `email = str(data.get("guardian_email", "")).strip().lower()` line and the verified-account check intact (the email var is still used for `claimed_email` and the account-match guard).

- [ ] **Step 3: Validate submit via accessors**

In `apps/registrations/services.py`, add a mapping near `REQUIRED_SUBMIT_FIELDS` and use it in `_require_complete_application`:

```python
_GUARDIAN_SUBMIT_ACCESSORS = {
    "guardian_full_name": "guardian_name",
    "guardian_personal_id": "guardian_pid",
    "guardian_email": "guardian_contact_email",
    "guardian_phone": "guardian_contact_phone",
    "guardian_declared_address": "guardian_address",
}
```

In `_require_complete_application`, change the read so guardian fields resolve through the accessor:
```python
    for field in REQUIRED_SUBMIT_FIELDS:
        attr = _GUARDIAN_SUBMIT_ACCESSORS.get(field, field)
        val = getattr(application, attr)
        if field in boolean_fields:
            if val is None:
                missing.append(field)
        elif not val:
            missing.append(field)
```
(Keep the existing `boolean_fields` set and the trailing `if missing: raise ValueError(...)`.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/registrations/ tests/billing/ tests/integrations/ -q`
Expected: PASS. If a submit-path test fails with "missing required fields" for a guardian field, the application's Guardian was not populated — check that the test builds via `create_or_update_draft` or links a populated Guardian; do not weaken the validation. If unsure, STOP and report BLOCKED.

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/services.py tests/registrations/test_guardian_read_through.py
git commit -m "refactor(registrations): draft-save writes only the Guardian; submit validates via accessors (P6 Slice B2)"
```

---

## Task 6: Production — simplify accessors, fix `__str__` + admin

**Files:**
- Modify: `apps/registrations/models.py` (the 5 accessors + `__str__`)
- Modify: `apps/registrations/admin.py` (`list_display`, `search_fields`)
- Test: `tests/registrations/test_guardian_read_through.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_str_uses_account_email_not_column(make_guardian):
    account = ParentAccount.objects.create(email="str@example.com")
    app = RegistrationApplication.objects.create(parent_account=account, member_full_name="Kid")
    assert str(app) == "str@example.com — Kid"


def test_accessors_return_empty_when_unlinked():
    app = RegistrationApplication.objects.create(claimed_email="anon@example.com")
    assert app.guardian_name == ""
    assert app.guardian_contact_email == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/registrations/test_guardian_read_through.py::test_str_uses_account_email_not_column tests/registrations/test_guardian_read_through.py::test_accessors_return_empty_when_unlinked -v`
Expected: FAIL — `test_str_*` fails because `__str__` reads `self.guardian_email` (still the column); the unlinked test currently passes via fallback but will be the contract after simplification.

- [ ] **Step 3: Simplify the accessors + `__str__`**

In `apps/registrations/models.py`, replace the five accessor bodies with the no-fallback versions:
```python
    @property
    def guardian_name(self) -> str:
        return str(self.guardian.full_name) if self.guardian_id is not None else ""

    @property
    def guardian_pid(self) -> str:
        return str(self.guardian.personal_id) if self.guardian_id is not None else ""

    @property
    def guardian_contact_phone(self) -> str:
        return str(self.guardian.phone) if self.guardian_id is not None else ""

    @property
    def guardian_address(self) -> str:
        return str(self.guardian.address) if self.guardian_id is not None else ""

    @property
    def guardian_contact_email(self) -> str:
        return str(self.parent_account.email) if self.parent_account_id is not None else ""
```
and change `__str__` from `return f"{self.guardian_email} — {self.member_full_name or 'draft'}"` to:
```python
    def __str__(self):
        return f"{self.guardian_contact_email or self.claimed_email} — {self.member_full_name or 'draft'}"
```

- [ ] **Step 4: Fix the admin**

In `apps/registrations/admin.py`:
- In `list_display`, replace `"guardian_email"` with `"guardian_contact_email"` (a model property — valid in `list_display`).
- Change `search_fields = ("member_full_name", "guardian_email", "guardian_full_name")` to `search_fields = ("member_full_name", "parent_account__email", "guardian__full_name")` (search needs real ORM lookups, not properties).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/registrations/ -q && uv run mypy apps/registrations/models.py apps/registrations/admin.py`
Expected: PASS + clean. (The columns still exist at this point, so nothing breaks; the accessors now simply ignore them.)

- [ ] **Step 6: Commit**

```bash
git add apps/registrations/models.py apps/registrations/admin.py tests/registrations/test_guardian_read_through.py
git commit -m "refactor(registrations): accessors/__str__/admin drop guardian_* columns (P6 Slice B2)"
```

---

## Task 7: Drop the five columns (migration)

**Files:**
- Modify: `apps/registrations/models.py` (remove the 5 field declarations)
- Create: `apps/registrations/migrations/0010_*.py`

- [ ] **Step 1: Remove the field declarations**

In `apps/registrations/models.py`, delete the five lines (the `# Guardian snapshot fields (P1 names)` block, ~47-51):
```python
    guardian_full_name = models.CharField(max_length=255, blank=True)
    guardian_personal_id = models.CharField(max_length=32, blank=True)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=32, blank=True)
    guardian_declared_address = models.CharField(max_length=255, blank=True)
```
(and the comment line above them).

- [ ] **Step 2: Generate the migration**

Run: `uv run python manage.py makemigrations registrations`
Expected: a migration with five `RemoveField` operations on `registrationapplication`.

- [ ] **Step 3: Confirm no remaining references**

Run: `grep -rnE "\.guardian_full_name|\.guardian_personal_id|\.guardian_email\b|\.guardian_phone|\.guardian_declared_address" apps/ tests/ --include="*.py"`
Expected: no output (every column attribute access is gone; form-field-name strings and `field_sources` keys are not attribute accesses so won't match the `\.` patterns).
Run: `grep -rn "guardian_email" apps/registrations/admin.py apps/registrations/models.py`
Expected: no output.

- [ ] **Step 4: Run the gate**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all green (the test DB is rebuilt from migrations, so the columns are gone there too). If anything fails with `AttributeError: ... 'guardian_email'` or `FieldError`, a reference was missed — find and fix it (repoint to the accessor / `parent_account` / form-field key). If a *test* fails because it still constructs with a `guardian_*=` kwarg, fix that test (sweep miss). STOP and report BLOCKED only if a failure is neither of those.

- [ ] **Step 5: Commit**

```bash
git add apps/registrations/models.py apps/registrations/migrations/
git commit -m "feat(registrations): drop the five guardian_* columns (P6 Slice B2)"
```

---

## Task 8: Carryover review items + gate + docs

**Files:**
- Modify: `apps/registrations/views.py` (add `select_related("parent_account")`)
- Modify: `tests/registrations/test_guardian_read_through.py` (admin-update-path test)
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: select_related the email accessor's FK**

In `apps/registrations/views.py`, the `admin_review_queue` and `parent_portal` querysets already `select_related("guardian")` (added at the end of B1). Add `parent_account` so the `guardian_contact_email` accessor does not trigger a per-row query:
- `account.applications.select_related("guardian")...` → `account.applications.select_related("guardian", "parent_account")...`
- `RegistrationApplication.objects.select_related("guardian").filter(...)` → `RegistrationApplication.objects.select_related("guardian", "parent_account").filter(...)`

- [ ] **Step 2: Add the admin-update-path test (carryover review note #4)**

Append to `tests/registrations/test_guardian_read_through.py`:

```python
def test_update_existing_draft_repopulates_guardian_profile():
    """create_or_update_draft on an existing draft updates the linked Guardian
    from the new form data (the guardian_id-guarded write, regardless of
    verified_account)."""
    from apps.registrations.services import create_or_update_draft

    account = ParentAccount.objects.create(email="update@example.com")
    app = create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "First",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "A"},
        files={}, verified_account=account,
    )
    create_or_update_draft(
        data={"guardian_email": account.email, "guardian_full_name": "Second",
              "guardian_personal_id": "010101-12345", "guardian_phone": "+37120000000",
              "guardian_declared_address": "A"},
        files={}, application=app, verified_account=account,
    )
    app.refresh_from_db()
    assert app.guardian_name == "Second"
```

- [ ] **Step 3: Run + commit the carryover**

Run: `uv run pytest tests/registrations/ -q && uv run ruff check apps/registrations/views.py && uv run mypy apps/registrations/views.py`
Expected: PASS + clean.
```bash
git add apps/registrations/views.py tests/registrations/test_guardian_read_through.py
git commit -m "perf+test(registrations): select_related(parent_account); admin-update-path test (P6 Slice B2)"
```

- [ ] **Step 4: Full gate**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`
Expected: all green. Record the passed count.

- [ ] **Step 5: Update docs**

`AGENTS.md`: add a dated entry (today) under the Slice B1 record — Slice B2 delivered: the five `guardian_*` columns are dropped (migration `registrations/0010`); the read accessors now read the Guardian/ParentAccount only (no fallback); `create_or_update_draft` writes only the Guardian; submit validates guardian fields via the accessors; `__str__` uses `guardian_contact_email`/`claimed_email`; admin `search_fields` use `parent_account__email`/`guardian__full_name`. Note the `make_guardian` test helper and that ~24 test files were swept off the columns. Use the real passed count.

`docs/milestones.md`: add a line recording Slice B2 delivery (columns dropped), and update the "Guardian dedup by email" gap note — read-through is now fully landed (B1 + B2); only Slice C (locked-profile UX + admin email change) remains for the guardian-identity work.

- [ ] **Step 6: Commit**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "docs: record P6 guardian-identity Slice B2 (drop columns)"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** §4 "drop the five `guardian_*` fields" is delivered by Tasks 5-7; the read-through end state (Guardian/ParentAccount the sole source) holds. The two B1 carryover review items (select_related `parent_account`, admin-update-path test) are Task 8.
- **Ordering is load-bearing:** the test sweep (Tasks 2-4) runs while the columns still exist so the suite stays green; production stops using the columns (5-6) before the migration drops them (7). Never makemigrations before the references are gone.
- **What stays:** form field names, `field_sources` JSON keys, `get_application_prefill` dict keys, the OCR-response JSON keys, the address-sync JS — none are model columns.
- **Not in B2:** locked-profile UX + admin-initiated email change (Slice C); parent self-service email change (deferred).
- **If the sweep missed a file:** Task 7 Step 4 / Step 3 greps will catch it as an `AttributeError`/`FieldError` or a leftover constructor kwarg — fix in place; it's a sweep miss, not a design problem.

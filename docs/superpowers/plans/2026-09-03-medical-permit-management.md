# P23 Medical Permit Management — Implementation Plan

**Goal:** Let parents upload a child's medical certificate (veselības apliecība) and let staff confirm receipt, track validity through September 30 of the following year, and view status across parent portals, registration admin, and the family hub. No OCR, no automatic expiry enforcement, no reminder emails.

**Architecture:** A new `MedicalPermit` model with `OneToOne` to `RegistrationApplication` and nullable `OneToOne` to `Member`. Private file storage with opaque paths. Service layer enforces format/size validation, safety-first write ordering (validate → write storage → persist metadata → delete old file), and redacted audit events. Parent-facing upload/preview/download through ownership-gated proxy views. Staff actions on the registration change page, family hub, and member changelist.

**Tech Stack:** Python 3.12, Django 5, Django admin, `FileField` on private storage, pytest-django. No OCR, no django-q2 jobs, no email, no reminder infrastructure.

---

## File structure and contracts

| File | Responsibility |
|---|---|
| `apps/documents/models.py` | Add `MedicalPermit` model with `OneToOne(application)`, nullable `OneToOne(member)`, `FileField`, `source`, `valid_until`, `confirmed_by`, `confirmed_at`. |
| `apps/documents/migrations/0006_medicalpermit.py` | Create `MedicalPermit` table; depend on `documents/0005`, `registrations`, `members`, `core` (User). |
| `apps/core/models.py` + `apps/core/migrations/0010_alter_auditevent_action.py` | Add six `AuditEvent.Action` choices: `MEDICAL_PERMIT_UPLOADED`, `MEDICAL_PERMIT_REPLACED`, `MEDICAL_PERMIT_CONFIRMED`, `MEDICAL_PERMIT_CONFIRMATION_CLEARED`, `MEDICAL_PERMIT_PREVIEWED`, `MEDICAL_PERMIT_DOWNLOADED`. |
| `apps/documents/medical_permits.py` | Service layer: `validate_medical_permit_upload`, `_write_permit_file`, `replace_medical_permit`, `upload_application_medical_permit`, `upload_member_medical_permit`, `confirm_medical_permit`, `clear_medical_permit_confirmation`, `attach_application_medical_permit`, `medical_permit_status`, `medical_permit_status_label`. |
| `apps/documents/admin_filters.py` | `MedicalPermitStatusFilter` base + `RegistrationMedicalPermitStatusFilter` + `MemberMedicalPermitStatusFilter`. |
| `apps/documents/admin.py` | Add status filter to `DocumentAdmin` (deferred) or wire per-model filters in registrations/members admin. |
| `apps/registrations/services.py` | Import and call `attach_application_medical_permit` inside `approve_application` (after member creation). |
| `apps/registrations/views.py` | Parent medical permit upload (`application_medical_permit_upload`, `member_medical_permit_upload`), preview/download proxy (`medical_permit_preview`, `medical_permit_download`), portal/workspace context injection. |
| `apps/registrations/urls.py` | Register parent medical permit upload, preview, and download routes. |
| `apps/registrations/admin.py` | Registration admin change page: medical permit upload/confirm/clear POST actions, context integration via `build_review_context`. |
| `apps/registrations/admin_panels.py` | `build_review_context` adds `medical_permit_status`, `medical_permit_status_label`, `medical_permit_has_file`. |
| `apps/members/admin.py` | Member changelist `MedicalPermitStatusFilter`; family hub medical permit upload/confirm/clear actions. |
| `apps/members/family_hub.py` | Build `medical_permit_status`/`medical_permit_status_label`/`medical_permit_has_file` per child in the family hub. |
| `templates/registrations/application_workspace.html` | Medical permit section: status label, preview/download buttons (when file exists), upload form (when no file). |
| `templates/registrations/parent_portal.html` | Medical permit section per application card: status label + warning indicator, preview/download/upload. |
| `templates/registrations/admin/_medical_permit_module.html` | New admin partial: status label, upload form, confirm button, clear confirmation button. |
| `templates/admin/registrations/registrationapplication/change_form.html` | Include `_medical_permit_module.html` in the change page. |
| `templates/admin/members/guardian/family_hub.html` | Medical permit upload/confirm/clear forms per child row. |
| `tests/documents/test_medical_permit_model.py` | Model defaults, constraints, choices, cascade. |
| `tests/documents/test_medical_permit_services.py` | Service layer: upload, replace, confirm, clear, attach, status, validity, validation, safety ordering. |
| `tests/documents/test_medical_permit_parent_flow.py` | Parent upload, preview, download, ownership enforcement. |
| `tests/documents/test_medical_permit_access.py` | Proxy endpoint authorization (anonymous, non-owner, owner, staff). |
| `tests/documents/test_medical_permit_admin.py` | Admin actions on registration change page and family hub; status filters. |

---

## Shared implementation rules

```python
# apps/documents/models.py — MedicalPermit fields
class MedicalPermit(TimeStampedModel):
    application = OneToOneField(RegistrationApplication, on_delete=CASCADE)
    member = OneToOneField(Member, on_delete=SET_NULL, null=True, blank=True)
    file = FileField(upload_to=medical_permit_upload_to, storage=private_document_storage, blank=True)
    original_filename = CharField(max_length=255, blank=True, default="")
    content_type = CharField(max_length=255, blank=True, default="")
    file_size = PositiveIntegerField(default=0)
    source = CharField(max_length=32, choices=Source.choices)
    valid_until = DateField()
    confirmed_by = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True)
    confirmed_at = DateTimeField(null=True, blank=True)
```

```python
# Validity rule — every upload/confirmation in year N → 30 September N+1
def _valid_until_for(year):
    return date(year + 1, 9, 30)
```

```python
# Safety ordering — every write follows this sequence
# 1. Validate upload (extension + MIME pair, size ≤ 25 MiB).
# 2. Write candidate file to private storage.
# 3. Persist new metadata to database.
# 4. Best-effort delete old file.
# On failure before step 3: old file and row untouched.
# On failure at step 4: orphan file may remain but never contradicts persisted state.
```

```python
# Audit metadata — redacted only
# {"source": "parent_upload" | "staff_upload" | "staff_confirmation"}
# Never: filename, personal data, medical data, file bytes.
```

```python
# Allowed format pairs — extension must match MIME type
_ALLOWED_PAIRS = (
    ("pdf", "application/pdf"),
    ("jpg", "image/jpeg"),
    ("jpeg", "image/jpeg"),
    ("png", "image/png"),
    ("heic", "image/heic"),
)
```

---

### Task 1: Write full P23 red test suite

**Files:**
- Create: `tests/documents/test_medical_permit_model.py`
- Create: `tests/documents/test_medical_permit_services.py`
- Create: `tests/documents/test_medical_permit_parent_flow.py`
- Create: `tests/documents/test_medical_permit_access.py`
- Create: `tests/documents/test_medical_permit_admin.py`

- [x] **Step 1: Add failing model tests.**

```python
def test_medical_permit_defaults(application):
    permit = MedicalPermit.objects.create(
        application=application,
        source=str(MedicalPermit.Source.PARENT_UPLOAD),
        valid_until=date(2027, 9, 30),
    )
    assert permit.member is None
    assert permit.file == ""
    assert permit.original_filename == ""
    assert permit.content_type == ""
    assert permit.file_size == 0
    assert permit.confirmed_by is None
    assert permit.confirmed_at is None

def test_one_current_per_application(application):
    permit1 = MedicalPermit.objects.create(
        application=application,
        source="parent_upload",
        valid_until=date(2027, 9, 30),
    )
    with pytest.raises(IntegrityError):
        MedicalPermit.objects.create(
            application=application,
            source="parent_upload",
            valid_until=date(2027, 9, 30),
        )

def test_member_cascade(application, member):
    permit = MedicalPermit.objects.create(
        application=application,
        member=member,
        source="parent_upload",
        valid_until=date(2027, 9, 30),
    )
    member.delete()
    permit.refresh_from_db()
    assert permit.member is None
```

- [x] **Step 2: Add failing service tests.**

```python
def test_upload_application_medical_permit_creates_row(application, uploaded_pdf):
    permit = upload_application_medical_permit(
        application, uploaded_pdf, actor_label="test", actor=None
    )
    assert permit.source == str(MedicalPermit.Source.PARENT_UPLOAD)
    assert permit.valid_until == date(2027, 9, 30)
    assert permit.file.name.startswith("private/medical-permits/")
    event = AuditEvent.objects.get(action="medical_permit_uploaded")
    assert event.metadata == {"source": "parent_upload"}

def test_replace_medical_permit_deletes_old_file(application, uploaded_pdf):
    permit = upload_application_medical_permit(
        application, uploaded_pdf, actor_label="test", actor=None
    )
    old_name = permit.file.name
    permit.refresh_from_db()
    upload_application_medical_permit(
        application, uploaded_pdf, actor_label="test", actor=None
    )
    permit.refresh_from_db()
    assert permit.file.name != old_name
    assert not permit.file.storage.exists(old_name)

def test_confirm_medical_permit_clears_file(application, uploaded_pdf):
    permit = upload_application_medical_permit(
        application, uploaded_pdf, actor_label="test", actor=None
    )
    confirm_medical_permit(permit, actor=staff_user)
    permit.refresh_from_db()
    assert permit.file == ""
    assert permit.source == str(MedicalPermit.Source.STAFF_CONFIRMATION)
    assert permit.confirmed_by == staff_user

def test_medical_permit_status_missing_current_expiring_expired(...):
    # missing: no permit row
    # missing: permit with no file and no confirmed_by
    # current: today < valid_until.replace(month=8, day=1)
    # expiring: 1 Aug ≤ today ≤ valid_until
    # expired: today > valid_until
    ...

def test_attach_application_medical_permit_idempotent(application, member, uploaded_pdf):
    permit = upload_application_medical_permit(application, uploaded_pdf, ...)
    result = attach_application_medical_permit(application, member)
    assert result is permit
    permit.refresh_from_db()
    assert result.member == member
    # Second call is a no-op
    result2 = attach_application_medical_permit(application, member)
    assert result2 is permit
```

Add safety-ordering tests: patch DB save to raise after storage write → assert old file and row survive; patch storage delete to raise after DB save → assert new metadata persisted and orphan file exists; patch validate to raise → assert no storage write and no DB change.

- [x] **Step 3: Add failing parent-flow tests.**

```python
def test_parent_upload_requires_ownership(verified_client, application, other_parent):
    # Verified parent must own the application's parent_account
    ...

def test_parent_preview_enforces_ownership(verified_client, application):
    # Non-owner gets 404; owner gets 200 with correct Content-Type
    ...

def test_parent_download_enforces_ownership(...):
    ...

def test_upload_rejects_unsupported_format(verified_client, application):
    # .docx → 400
    # oversized file → 400
    # extension/MIME mismatch → 400
    ...
```

- [x] **Step 4: Add failing access tests.**

```python
def test_anonymous_preview_is_redirect_to_admin_login(client, application):
    ...

def test_non_admin_authenticated_preview_is_404(staff_client_without_perm, application):
    ...

def test_staff_preview_is_200(staff_client, application):
    ...
```

- [x] **Step 5: Add failing admin-action tests.**

```python
def test_registration_admin_medical_permit_upload(staff_client, application):
    # POST with file → 200/302; audit event emitted
    ...

def test_registration_admin_confirm_medical_permit(staff_client, application):
    # POST confirm → 200/302; file cleared; audit emitted
    ...

def test_registration_admin_clear_confirmation(staff_client, application):
    # POST clear → 200/302; confirmed_by/confirmed_at cleared
    ...

def test_member_changelist_medical_permit_filter(...):
    # Filter options: missing, expiring, expired
    # Queryset returns correct rows per selected status
    ...
```

- [x] **Step 6: Run red phase.**

```bash
uv run pytest -q \
  tests/documents/test_medical_permit_model.py \
  tests/documents/test_medical_permit_services.py \
  tests/documents/test_medical_permit_parent_flow.py \
  tests/documents/test_medical_permit_access.py \
  tests/documents/test_medical_permit_admin.py
```

Expected: fail during collection or assertions. Do not implement before this red result is recorded.

---

### Task 2: Add MedicalPermit model, migrations, and audit vocabulary

**Files:**
- Modify: `apps/documents/models.py`
- Create: `apps/documents/migrations/0006_medicalpermit.py`
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/0010_alter_auditevent_action.py`

- [x] **Step 1: Add MedicalPermit model.**

Import `PrivateDocumentStorage` from `apps.documents.storage`, instantiate module-level storage. Add `medical_permit_upload_to` helper that generates `private/medical-permits/<uuid4.hex>.<ext>` with extension validation. Add the `MedicalPermit` model with all fields listed above. Add `Source` TextChoices: `PARENT_UPLOAD`, `STAFF_UPLOAD`, `STAFF_CONFIRMATION`.

- [x] **Step 2: Add audit choices.**

Add six actions to `AuditEvent.Action`:

```python
MEDICAL_PERMIT_UPLOADED = "medical_permit_uploaded", "Veselības apliecība augšupielādēta"
MEDICAL_PERMIT_REPLACED = "medical_permit_replaced", "Veselības apliecība aizvietota"
MEDICAL_PERMIT_CONFIRMED = "medical_permit_confirmed", "Veselības apliecība apstiprināta"
MEDICAL_PERMIT_CONFIRMATION_CLEARED = (
    "medical_permit_confirmation_cleared",
    "Veselības apliecības apstiprinājums noņemts",
)
MEDICAL_PERMIT_PREVIEWED = "medical_permit_previewed", "Veselības apliecība priekšskatīta"
MEDICAL_PERMIT_DOWNLOADED = "medical_permit_downloaded", "Veselības apliecība lejupielādēta"
```

- [x] **Step 3: Generate and inspect migrations.**

```bash
uv run python manage.py makemigrations documents
uv run python manage.py makemigrations core
uv run python manage.py makemigrations --check
uv run python manage.py migrate
```

Expected: migration check reports no additional model changes; migrations apply locally.

- [x] **Step 4: Run model tests.**

```bash
uv run pytest -q tests/documents/test_medical_permit_model.py
```

Expected: model default/constraint/cascade tests pass; service tests still fail.

---

### Task 3: Implement service layer

**Files:**
- Create: `apps/documents/medical_permits.py`
- Test: `tests/documents/test_medical_permit_services.py`

- [x] **Step 1: Add format/size validator.**

`validate_medical_permit_upload(upload)` checks: non-null, size ≤ 25 MiB, extension/MIME pair is in `_ALLOWED_PAIRS`. Raises `ValueError` with Latvian messages.

- [x] **Step 2: Add `_write_permit_file` with safety ordering.**

Writes candidate to storage → persists metadata → deletes old file. On failure before persist, restores old state. On failure at delete, re-raises after best-effort orphan cleanup.

- [x] **Step 3: Add public service functions.**

`replace_medical_permit`, `upload_application_medical_permit`, `upload_member_medical_permit`, `confirm_medical_permit`, `clear_medical_permit_confirmation`, `attach_application_medical_permit`. Each emits the correct `AuditEvent` with redacted metadata.

- [x] **Step 4: Add status helpers.**

`medical_permit_status(permit, on=today)` → `missing`/`current`/`expiring`/`expired`. `medical_permit_status_label(status)` → Latvian label map.

- [x] **Step 5: Run service tests.**

```bash
uv run pytest -q tests/documents/test_medical_permit_services.py
```

Expected: all service tests pass.

---

### Task 4: Wire registration admin and parent-facing endpoints

**Files:**
- Modify: `apps/registrations/admin_panels.py`
- Modify: `apps/registrations/admin.py`
- Modify: `apps/registrations/views.py`
- Modify: `apps/registrations/urls.py`
- Modify: `apps/registrations/services.py`
- Create: `templates/registrations/admin/_medical_permit_module.html`
- Modify: `templates/admin/registrations/registrationapplication/change_form.html`
- Modify: `templates/registrations/application_workspace.html`
- Modify: `templates/registrations/parent_portal.html`
- Test: `tests/documents/test_medical_permit_parent_flow.py`
- Test: `tests/documents/test_medical_permit_access.py`
- Test: `tests/documents/test_medical_permit_admin.py`

- [x] **Step 1: Wire `attach_application_medical_permit` into approval.**

In `approve_application`, after `Member.objects.create(...)`, call `attach_application_medical_permit(application, member)`. This is idempotent and safe for re-approval.

- [x] **Step 2: Add `build_review_context` annotations.**

In `build_review_context`, after existing panel context:

```python
medical_permit = getattr(application, "medical_permit", None)
medical_permit_status_value = medical_permit_status(medical_permit)
# Add to return dict:
"medical_permit_status": medical_permit_status_value,
"medical_permit_status_label": medical_permit_status_label(medical_permit_status_value),
"medical_permit_has_file": bool(medical_permit is not None and medical_permit.file),
```

- [x] **Step 3: Add admin change-page actions.**

In `RegistrationApplicationAdmin`, add `get_urls()` with POST endpoints for `medical_permit_upload`, `confirm_medical_permit`, `clear_medical_permit_confirmation`. Each requires `has_change_permission`, loads the application, dispatches to the service, records a success/warning message, and redirects back to the change page.

- [x] **Step 4: Render `_medical_permit_module.html` in change form.**

Include the partial in `templates/admin/registrations/registrationapplication/change_form.html` after the existing agreement/training-group modules.

- [x] **Step 5: Add parent upload/preview/download views.**

`application_medical_permit_upload` and `member_medical_permit_upload` — POST only, validate ownership, call service, return JSON `201` (success) or `400` (validation error). `medical_permit_preview` and `medical_permit_download` — enforce ownership, stream file with correct `Content-Type` and disposition.

- [x] **Step 6: Wire parent URLs.**

Register routes in `apps/registrations/urls.py`:

```python
path("applications/<int:application_id>/medical-permit/upload/", ...),
path("members/<int:member_id>/medical-permit/upload/", ...),
path("medical-permit/<int:permit_id>/preview/", ...),
path("medical-permit/<int:permit_id>/download/", ...),
```

- [x] **Step 7: Render medical permit sections in parent templates.**

`application_workspace.html`: after the application-status banner, render the medical permit section with status label, preview/download buttons, and upload form.

`parent_portal.html`: per application card, render status label + warning indicator, preview/download/upload buttons.

- [x] **Step 8: Run parent and access tests.**

```bash
uv run pytest -q \
  tests/documents/test_medical_permit_parent_flow.py \
  tests/documents/test_medical_permit_access.py
```

Expected: all parent-flow and access tests pass.

---

### Task 5: Add admin filters, family hub, and member admin

**Files:**
- Modify: `apps/documents/admin_filters.py`
- Modify: `apps/members/admin.py`
- Modify: `apps/members/family_hub.py`
- Modify: `templates/admin/members/guardian/family_hub.html`
- Test: `tests/documents/test_medical_permit_admin.py`

- [x] **Step 1: Add status filters.**

`RegistrationMedicalPermitStatusFilter` (binds to `application_id`) and `MemberMedicalPermitStatusFilter` (binds to `member_id`). Add to respective admin `list_filter`.

- [x] **Step 2: Add family hub medical permit actions.**

In `family_hub.py`, build `medical_permit_status`/`medical_permit_status_label`/`medical_permit_has_file` per child. In `family_hub.html`, add upload/confirm/clear forms per child row. In `members/admin.py`, add POST handlers for the three actions.

- [x] **Step 3: Run admin tests.**

```bash
uv run pytest -q tests/documents/test_medical_permit_admin.py
```

Expected: all admin action and filter tests pass.

---

### Task 6: Run integration, migration, style, and documentation gates

**Files:**
- Modify only if verification exposes a defect: files from Tasks 2–5.
- Modify after all code acceptance: `AGENTS.md`, `docs/milestones.md`.

- [x] **Step 1: Execute focused regression suite.**

```bash
uv run pytest -q \
  tests/documents/test_medical_permit_model.py \
  tests/documents/test_medical_permit_services.py \
  tests/documents/test_medical_permit_parent_flow.py \
  tests/documents/test_medical_permit_access.py \
  tests/documents/test_medical_permit_admin.py
```

Expected: all selected tests pass.

- [x] **Step 2: Run full repository verification.**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: all commands exit `0`. Stop and fix failures.

- [x] **Step 3: Update graph and documentation.**

```bash
graphify update .
```

Then update `AGENTS.md` and `docs/milestones.md` with actual verification evidence. Do not claim LAN sign-off.

- [x] **Step 4: Do not commit automatically.**

Present verification output and scoped diff for review.

---

## Spec coverage self-check

| Approved requirement | Implementing task |
|---|---|
| `MedicalPermit` model with `OneToOne(application)`, nullable `OneToOne(member)` | Tasks 1–2 |
| Private storage with opaque non-PII paths | Tasks 1–2 |
| Format/size validation (PDF/JPG/JPEG/PNG/HEIC, max 25 MiB) | Tasks 1–3 |
| Validity year N → 30 September N+1 | Tasks 1–3 |
| Status: missing/current/expiring/expired | Tasks 1–3 |
| Parent upload, preview, download with ownership | Tasks 1, 4 |
| Staff admin actions (upload/confirm/clear) | Tasks 1, 4, 5 |
| Registration change page + family hub integration | Tasks 1, 4, 5 |
| Member changelist status filters | Task 5 |
| Six `AuditEvent` actions with redacted metadata | Tasks 1–3 |
| No OCR/medical extraction | (out of scope) |
| No automatic expiry enforcement | (out of scope) |
| No reminder emails | (out of scope) |
| No permit history | (out of scope) |
| No public URLs | Tasks 1, 4 |

No implementation action is authorized until this plan is approved.

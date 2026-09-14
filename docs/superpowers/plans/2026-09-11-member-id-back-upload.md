# Member ID Card Back Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, privately stored child ID-card back upload to registration, Django admin review, and Admin Hub cockpit.

**Architecture:** Add one `Document.Kind` value, `member_identity_back`; no new model or storage path. Form, presentation mappings, upload paths, and staff panel builders treat it as a fourth document. Existing `OCR_SUPPORTED_KINDS` remains unchanged, so both synchronous draft upload and async upload persist this kind with `NOT_REQUESTED` and never enqueue OCR.

**Tech Stack:** Python 3.12, Django 5, pytest/pytest-django, Django migrations, server-rendered Django templates, existing private document proxy endpoints.

---

## 1. Design decisions

| Decision | Why |
|---|---|
| Separate `Document.Kind.MEMBER_IDENTITY_BACK` | Preserves independent upload, replacement history, and staff visibility for front/passport and ID-card back. |
| `member_identity_back_document` stays optional | A passport has no separate card back; requiring it would incorrectly block submission. |
| Reuse existing private `Document` storage/proxies | Keeps authorization, audit events, retention posture, and file handling consistent without public URLs or new endpoints. |
| Exclude back kind from OCR | Back images are supporting evidence only; no agreed OCR fields or prefill behavior exist. |
| Add fourth panel/tab explicitly | Admin and Hub lists are fixed today; enum expansion alone updates parent workspace but not staff surfaces. |

## 2. File map

| File | Change |
|---|---|
| `apps/documents/models.py` | Add `Document.Kind.MEMBER_IDENTITY_BACK = "member_identity_back", "Bērna ID kartes aizmugure"`. |
| `apps/documents/migrations/0006_alter_document_kind.py` | Migration generated from updated `Document.kind` choices. |
| `apps/registrations/forms.py` | Add optional back `FileField`, documents-section ordering, async attributes, and hidden-input class. Do not add submit requirement or wizard gate. Rename front label exactly. |
| `apps/registrations/presentation.py` | Add back kind to `DOCUMENT_KIND_LABELS`, `DOCUMENT_FIELD_ID_MAP`, and `_FIELD_TO_KIND`/`FIELD_NAME_BY_KIND`. |
| `apps/registrations/services.py` | Route posted `member_identity_back_document` to `_handle_document_upload(..., Document.Kind.MEMBER_IDENTITY_BACK)`. |
| `apps/registrations/admin_panels.py` | Include `member_back_panel` in `build_review_context`. |
| `templates/admin/registrations/registrationapplication/change_form.html` | Render fourth `_doc_panel.html` panel. |
| `apps/admin_hub/views.py` | Add `"Aizmugure"` and `MEMBER_IDENTITY_BACK` panel to `viewer_tabs`. |
| `tests/registrations/test_registration_form_contract.py` | Pin enum, form fields, ordering, exact labels, optional status, and lack of required/gate behavior. |
| `tests/registrations/test_async_document_upload.py` | Verify async back upload creates private kind with `not_requested`, no OCR enqueue, and replacement works. |
| `tests/registrations/test_document_state_presentation.py` | Verify workspace displays back card, exact Latvian card label, active filename, and renamed front label. |
| `tests/registrations/test_admin_review_context.py` | Verify fourth panel exists, has back kind, and no OCR summary. |
| `tests/admin_hub/test_hub_cockpit.py` | Verify staff cockpit shows `Aizmugure` tab and authorized preview/download proxy URLs for uploaded back image. |

## 3. Test strategy

**Framework:** pytest + pytest-django. Use existing `SimpleUploadedFile`, staff fixtures, and authorized URL reversals.

**Test:** enum/migration contract; form copy/order/optional behavior; synchronous and async upload persistence; `NOT_REQUESTED` and zero enqueue calls; soft-delete replacement; parent workspace labels/state; Django-admin panel; staff Hub tab/proxy links.

**Do not test:** OCR provider behavior, camera browser APIs, private proxy implementation, billing/agreement workflows, or unrelated document kinds. Existing suites already own those contracts.

## 4. Implementation tasks

### Task 1: Write red tests for form, storage, and upload behavior

**Files:**
- Modify: `tests/registrations/test_registration_form_contract.py`
- Modify: `tests/registrations/test_async_document_upload.py`
- Modify: `tests/registrations/test_document_state_presentation.py`

- [ ] **Step 1: Add form/enum contract tests.**

```python
def test_member_identity_back_is_an_optional_document_field():
    form = RegistrationApplicationForm()
    assert form.fields["member_identity_document"].label == (
        "Bērna personas dokuments — pase vai ID kartes priekšpuse"
    )
    assert form.fields["member_identity_back_document"].label == (
        "Bērna ID kartes aizmugure (ja ielādēta ID kartes priekšpuse; "
        "nav nepieciešams ja ielādēta pase)"
    )
    assert form.fields["member_identity_back_document"].required is False
    assert "member_identity_back_document" not in form.submit_required_fields
    assert "data-step-required" not in form.fields["member_identity_back_document"].widget.attrs
    assert "member_identity_back" in {value for value, _ in Document.Kind.choices}
```

Also assert documents order is front → back → portrait, async attrs are `member_identity_back` / `id_member_identity_back_document_progress`, and class contains `fk-visually-hidden`.

- [ ] **Step 2: Add async upload and replacement tests.**

```python
with patch("apps.registrations.views.enqueue_ocr_job") as enqueue:
    response = client.post(url, {
        "kind": "member_identity_back",
        "file": SimpleUploadedFile("back.png", _png_bytes(), content_type="image/png"),
    })
assert response.status_code == 201
doc = Document.objects.get(pk=response.json()["document_id"])
assert doc.kind == Document.Kind.MEMBER_IDENTITY_BACK
assert doc.ocr_status == Document.OcrStatus.NOT_REQUESTED
enqueue.assert_not_called()
```

POST a second back file; assert first has `deleted_at is not None`, second stays active, and both rows retain the back kind.

- [ ] **Step 3: Add workspace presentation test.**

Create a draft with `files={"member_identity_back_document": SimpleUploadedFile(...)}`. As verified owner, GET workspace and assert exact parent-card label `Bērna ID kartes aizmugure`, uploaded filename, new field id, and renamed front form label appear. Assert `DocumentExtraction.objects.filter(document=back_doc).exists()` is false.

- [ ] **Step 4: Run red tests.**

Run: `uv run pytest -q tests/registrations/test_registration_form_contract.py tests/registrations/test_async_document_upload.py tests/registrations/test_document_state_presentation.py`

Expected: failures naming missing `MEMBER_IDENTITY_BACK` and `member_identity_back_document`; no unrelated failures.

### Task 2: Add document kind and registration upload wiring

**Files:**
- Modify: `apps/documents/models.py`
- Create: `apps/documents/migrations/0006_alter_document_kind.py`
- Modify: `apps/registrations/forms.py`
- Modify: `apps/registrations/presentation.py`
- Modify: `apps/registrations/services.py`

- [ ] **Step 1: Add model choice and generate migration.**

```python
class Kind(models.TextChoices):
    GUARDIAN_IDENTITY = "guardian_identity", "Guardian identity"
    MEMBER_IDENTITY = "member_identity", "Member identity"
    MEMBER_IDENTITY_BACK = "member_identity_back", "Bērna ID kartes aizmugure"
    MEMBER_PORTRAIT = "member_portrait", "Member portrait"
```

Run: `uv run python manage.py makemigrations documents`

Expected: one `0006_alter_document_kind.py` migration changing only `Document.kind` choices.

- [ ] **Step 2: Add form and presentation mappings.**

```python
# forms.py documents section
"member_identity_document",
"member_identity_back_document",
"member_portrait_document",

member_identity_document = forms.FileField(
    required=False,
    label="Bērna personas dokuments — pase vai ID kartes priekšpuse",
)
member_identity_back_document = forms.FileField(
    required=False,
    label=(
        "Bērna ID kartes aizmugure (ja ielādēta ID kartes priekšpuse; "
        "nav nepieciešams ja ielādēta pase)"
    ),
)
```

Add back field to the async-hook loop and hidden-file-input loop. Add mappings:

```python
"member_identity_back": "Bērna ID kartes aizmugure"
"member_identity_back": "id_member_identity_back_document"
"member_identity_back_document": "member_identity_back"
```

Do not add it to `submit_required_fields` or `_field_step_map`.

- [ ] **Step 3: Persist regular form upload without OCR.**

```python
member_back_doc = files.get("member_identity_back_document")
if member_back_doc is not None:
    _handle_document_upload(
        application,
        member_back_doc,
        Document.Kind.MEMBER_IDENTITY_BACK,
    )
```

Place after member front upload and before portrait upload. Do not add kind to `OCR_SUPPORTED_KINDS`; `_handle_document_upload` therefore saves `NOT_REQUESTED` and never calls `enqueue_ocr_job`.

- [ ] **Step 4: Run targeted tests green.**

Run: `uv run pytest -q tests/registrations/test_registration_form_contract.py tests/registrations/test_async_document_upload.py tests/registrations/test_document_state_presentation.py`

Expected: all pass.

### Task 3: Write red staff-surface tests

**Files:**
- Modify: `tests/registrations/test_admin_review_context.py`
- Modify: `tests/admin_hub/test_hub_cockpit.py`

- [ ] **Step 1: Add admin-review context test.**

```python
ctx = build_review_context(application_with_back_document)
assert ctx["member_back_panel"]["kind"] == Document.Kind.MEMBER_IDENTITY_BACK
assert ctx["member_back_panel"]["active"] == back_document
assert ctx["member_back_panel"]["ocr_summary"] == []
```

GET the registration admin change page as staff; assert the Latvian back label and its authorized `documents:admin-document-preview` URL appear.

- [ ] **Step 2: Add Admin Hub cockpit test.**

Create an active back image on `submitted_application`, force-login `reviewer`, then GET `admin_hub:cockpit`.

```python
assert "Aizmugure" in body
assert reverse("documents:admin-document-preview", args=[back_doc.id]) in body
assert reverse("documents:admin-document-download", args=[back_doc.id]) in body
```

Also GET with no back image and assert `Aizmugure` tab is present and disabled, matching existing viewer empty-document behavior.

- [ ] **Step 3: Run red staff tests.**

Run: `uv run pytest -q tests/registrations/test_admin_review_context.py tests/admin_hub/test_hub_cockpit.py`

Expected: failures for missing `member_back_panel` and absent `Aizmugure` tab.

### Task 4: Add Django admin and Admin Hub visibility

**Files:**
- Modify: `apps/registrations/admin_panels.py`
- Modify: `templates/admin/registrations/registrationapplication/change_form.html`
- Modify: `apps/admin_hub/views.py`

- [ ] **Step 1: Build and expose fourth admin panel.**

```python
member_back_panel = build_doc_panel(
    application,
    str(Document.Kind.MEMBER_IDENTITY_BACK),
)

# return dict
"member_back_panel": member_back_panel,
```

Add this after `member_panel`; it inherits existing private preview and no-extraction behavior from `build_doc_panel`.

- [ ] **Step 2: Render fourth Django-admin panel.**

```django
{% include "registrations/admin/_doc_panel.html" with panel=member_back_panel %}
```

Place immediately after the member front panel and before portrait panel.

- [ ] **Step 3: Add fourth Hub viewer tab.**

```python
[
    "Bērna ID",
    "Aizmugure",
    "Vecāka ID",
    "Portrets",
],
[
    build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY)),
    build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY_BACK)),
    build_doc_panel(application, str(Document.Kind.GUARDIAN_IDENTITY)),
    build_doc_panel(application, str(Document.Kind.MEMBER_PORTRAIT)),
],
```

Keep `_viewer.html` unchanged: it iterates `viewer_tabs`, disables missing documents, and builds existing staff-authorized preview/download URLs.

- [ ] **Step 4: Run targeted staff tests green.**

Run: `uv run pytest -q tests/registrations/test_admin_review_context.py tests/admin_hub/test_hub_cockpit.py`

Expected: all pass.

### Task 5: Migration and full verification

**Files:**
- Verify only: all files above

- [ ] **Step 1: Validate migration state.**

Run: `uv run python manage.py makemigrations --check`

Expected: `No changes detected`.

- [ ] **Step 2: Run focused regression suite.**

Run: `uv run pytest -q tests/registrations/test_registration_form_contract.py tests/registrations/test_async_document_upload.py tests/registrations/test_document_state_presentation.py tests/registrations/test_admin_review_context.py tests/admin_hub/test_hub_cockpit.py`

Expected: all pass.

- [ ] **Step 3: Run repository gate.**

Run: `uv run pytest -q && uv run ruff check . && uv run mypy .`

Expected: all commands exit 0.

## 5. Acceptance criteria per unit

1. **Data model:** `member_identity_back` is valid `Document.Kind`; migration applies cleanly.
2. **Parent form:** exact agreed labels render; front remains mandatory; back neither blocks wizard nor submit.
3. **Upload:** both form submit and async upload create private active back documents; replacement soft-deletes only prior back document; OCR stays untouched.
4. **Admin:** back document has a distinct thumbnail/panel, secure staff proxy URLs, and no OCR section.
5. **Admin Hub:** cockpit has an `Aizmugure` viewer tab, disabled when empty and using preview/download proxy URLs when present.
6. **Regression:** all test, lint, type, and migration checks succeed.

## 6. Documentation scope

- Keep `docs/superpowers/specs/2026-09-11-member-id-back-upload-design.md` as approved design record.
- Add no README or operator-guide changes: no endpoint, configuration, security model, or staff workflow changes beyond an already self-explanatory fourth viewer tab.

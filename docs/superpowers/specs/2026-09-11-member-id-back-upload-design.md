# Member Identity-Card Back Image Upload — Design Specification

**Date:** 2026-09-11
**Status:** Design approved; written-spec review pending

---

## 1. Problem

FK Cēsis MMS requires parents to upload a member identity document to confirm a child's identity. The current single-upload field (`member_identity_document`) serves both passports and ID cards, but staff have noted that an ID card back image is often needed to verify the card number and expiry date. Currently staff must request this separately or read it from the front image when visible.

The club needs a simple, optional back-image upload that follows the existing document-card UX, is stored under the same private-storage safeguards, and is visible to staff in the admin review surfaces and the Admin Hub review cockpit. No OCR, no merging, no guardian-document changes.

---

## 2. Scope

### 2.1 In scope

| # | Capability |
|---|-----------|
| S1 | Registration form retains a required member identity document. Its displayed Latvian label changes to: `Bērna personas dokuments — pase vai ID kartes priekšpuse`. |
| S2 | A second, optional member identity back image upload is added. Its card title is `Bērna ID kartes aizmugure`; helper text below the title: `Nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai.` |
| S3 | The back image uses a distinct private `Document` kind: `member_identity_back`. It follows the existing `Document` model schema (no new model). |
| S4 | The back image card uses the existing document-card UX: async file upload, camera affordance on supported mobile devices, active/replaced state indicators, and safe replacement. |
| S5 | The back image is **optional** at submission. The front/passport document remains **required**. |
| S6 | The back image is stored and served under existing private-document safeguards: private storage, staff-only preview/download proxy views, access auditing via `AuditEvent`. |
| S7 | No OCR is performed on the back image. No OCR request, extraction, prefill, or summary. The `ocr_status` stays at `NOT_REQUESTED`. |
| S8 | The back image is visible to staff in Django admin review surfaces (registration admin change page) and in the Admin Hub application review cockpit (`/hub/pieteikumi/<pk>/`). The hub shows it as a distinct document panel/card with normal secure preview behavior. |

### 2.2 Out of scope

- Changing guardian documents (`guardian_identity`).
- Billing, agreements, or any downstream domain mutation triggered by the back image.
- OCR, OCR extraction, OCR prefill, or OCR summary for the back image.
- Merging the front and back images into a single document or PDF.
- Parent-facing changes beyond the existing registration workspace document card.
- Automated document validation (e.g., "front is a passport, back is missing").
- Bulk operations on the back image.

---

## 3. Requirements and Exact UI Copy

### 3.1 Required fields

| Surface | Field | Title (Latvian) | Helper text (Latvian) | Required |
|---------|-------|-----------------|----------------------|----------|
| Registration form | `member_identity_document` | `Bērna personas dokuments — pase vai ID kartes priekšpuse` | — | **Yes** |
| Registration form | `member_identity_back_document` | `Bērna ID kartes aizmugure (nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai)` | — | **No** |

### 3.2 Document kind

| Constant | Value | Display label (admin) |
|----------|-------|----------------------|
| `Document.Kind.MEMBER_IDENTITY_BACK` | `"member_identity_back"` | `Bērna ID kartes aizmugure` |

Parent-facing surfaces use `DOCUMENT_KIND_LABELS` mapping (short title only; helper text is rendered separately):

```python
DOCUMENT_KIND_LABELS = {
    ...
    "member_identity_back": "Bērna ID kartes aizmugure",
}
```

Helper text is injected into the document card template below the title, not embedded in the label string.

### 3.3 Form field behavior

- The new field is a `FileField` with `required=False`.
- It participates in the existing `documents` section of the form, positioned after `member_identity_document` and before `member_portrait_document`.
- It carries the same async-upload hooks as other document fields: `data-async-upload="member_identity_back"`, `data-progress-slot="id_member_identity_back_document_progress"`.
- It is visually hidden (`fk-visually-hidden` class) with visible upload/camera labels in the document card.
- No step-gating participation — the document card shows "Nav augšupielādēts" / "Aktīvs" but does not block wizard step advance.

---

## 4. Design and Data Flow

### 4.1 Data model

The existing `Document` model is extended with one new `Kind` enum value. No new columns, no new model.

```python
# apps/documents/models.py

class Document(TimeStampedModel):
    class Kind(models.TextChoices):
        GUARDIAN_IDENTITY = "guardian_identity", "Guardian identity"
        MEMBER_IDENTITY = "member_identity", "Member identity"
        MEMBER_PORTRAIT = "member_portrait", "Member portrait"
        MEMBER_IDENTITY_BACK = "member_identity_back", "Member identity back"
```

One migration: add the new choice. No data migration needed (no pre-existing back images).

### 4.2 Document lifecycle

The back image follows the same lifecycle as other document kinds:

1. **Upload** (parent, draft flow): The parent uploads an image file via the document card. The file is stored in private storage under the existing `private/documents/` path, tagged with `kind="member_identity_back"`.
2. **Async processing**: The existing async-upload flow handles the file. The document is created with `ocr_status=NOT_REQUESTED`. No OCR job is enqueued.
3. **Active state**: When uploaded, the card badge changes to "Aktīvs". The filename is displayed.
4. **Replacement**: The parent can replace the back image (same as existing replace flow). The previous version is soft-deleted (`deleted_at` set). The card shows the new active document; replaced versions appear in the document history within the admin review surface.
5. **No OCR**: `ocr_status` remains `NOT_REQUESTED`. No `DocumentExtraction` row is created. No field-source tags are set.

### 4.3 Form integration

The `RegistrationApplicationForm` is updated:

- `section_order`: the `documents` section gains `"member_identity_back_document"` after `"member_identity_document"`.
- A new `member_identity_back_document = forms.FileField(required=False, label="Bērna ID kartes aizmugure (nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai)")` field. The card title (`Bērna ID kartes aizmugure`) and helper text (`Nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai.`) are rendered separately in the document card template, not embedded in the form label.
- The field is tagged with async-upload hooks in `__init__`.
- It is visually hidden via the existing `fk-visually-hidden` class pattern.
- It is **not** included in `submit_required_fields` (no server-side required check).
- It is **not** included in `_field_step_map` (no wizard step-gating).
- The `cleaned_data` flow: the existing `_handle_document_upload` service routes the new field to `_handle_document_upload(application, files.get("member_identity_back_document"), "member_identity_back")`.

### 4.4 Presentation layer

**`apps/registrations/presentation.py`:**

- `DOCUMENT_KIND_LABELS` gains `"member_identity_back": "Bērna ID kartes aizmugure"`.
- `DOCUMENT_FIELD_ID_MAP` gains `"member_identity_back": "id_member_identity_back_document"`.
- `FIELD_NAME_BY_KIND` (inverse of `_FIELD_TO_KIND`) gains `"member_identity_back": "member_identity_back_document"`.
- `_FIELD_TO_KIND` gains `"member_identity_back_document": "member_identity_back"`.

**`templates/parent_ui/includes/document_card.html`:**

- The existing loop over `document_state.items` automatically renders the new kind because `document_state` is built from `active_documents_by_kind(application)` which iterates over all `Document.Kind` values.
- No template changes needed — the card renders any kind that has a label in `DOCUMENT_KIND_LABELS`.

**`templates/registrations/application_workspace.html`:**

- No changes needed — the workspace already iterates `document_state` dynamically. The new card appears automatically in the documents section.

### 4.5 Admin review surface

**`apps/registrations/admin_panels.py::build_review_context`:**

- A new `member_back_panel = build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY_BACK))` is added.
- `build_review_context` returns it in the context dict as `"member_back_panel"`.

**`templates/registrations/admin/_doc_panel.html`:**

- No changes needed — the partial renders any panel dict with the same structure. The new panel carries `kind="member_identity_back"`, `panel_title="Member identity back"` (admin uses `get_kind_display()`), and the same active/replaced/OCR structure.

**`templates/admin/registrations/registrationapplication/change_form.html`:**

- A new `{% include "registrations/admin/_doc_panel.html" with panel=member_back_panel %}` is added immediately after the `member_panel` include and before the `portrait_panel` include.

### 4.6 Admin Hub review cockpit

**`apps/admin_hub/views.py::cockpit_view`:**

- The `viewer_tabs` list is extended with a new `(label, panel)` tuple: `("Aizmugure", build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY_BACK)))`.
- The existing `_viewer.html` partial renders this as a fourth tab alongside "Bērna ID", "Vecāka ID", "Portrets".

**`templates/admin_hub/_viewer.html`:**

- No changes needed — the viewer iterates `viewer_tabs` dynamically. The new tab renders with the same viewer frame, toolbar, and zoom/rotate controls.

### 4.7 Authorization and access auditing

- **Preview/download**: Existing proxy views (`documents:admin-document-preview`, `documents:admin-document-download`) enforce staff-only access. No new endpoints.
- **Audit**: The existing document `previewed` and `downloaded` `AuditEvent` actions fire for the back image when staff preview/download it. The `deleted` event fires on replacement. No new audit actions needed.

---

## 5. Security

### 5.1 Private storage

- The back image is stored in the same private storage root (`PRIVATE_DOCUMENTS_ROOT`) as all other registration documents.
- No public URL is generated. `FileField.url` is never exposed to templates.
- All access is through Django proxy views that enforce staff authorization.

### 5.2 Authorization

| Surface | Access |
|---------|--------|
| Parent upload/replace | Verified `ParentAccount` owning the application (same as existing document upload) |
| Admin preview/download | Staff user (existing proxy view enforcement) |
| Hub preview | Staff user (existing viewer enforcement) |
| Non-staff / non-owner | 404 (existing behavior) |

### 5.3 OCR exclusion

- The back image is explicitly excluded from the OCR pipeline. No OCR job is enqueued. No `DocumentExtraction` row is created. `ocr_status` remains `NOT_REQUESTED`.
- The existing OCR service dispatch (`_handle_document_upload`) routes by kind; the new kind is not in the OCR dispatch map and is silently skipped.

---

## 6. Error and Optional Behavior

### 6.1 Submission validation

- The front/passport document (`member_identity_document`) remains **required** at submission. Validation is unchanged.
- The back image (`member_identity_back_document`) is **optional**. No validation error if missing. No validation error if present.
- Saving a draft with or without the back image succeeds.

### 6.2 Upload errors

- File-size limits: the existing `Document.file` field constraints apply (no custom limit for the back image).
- Unsupported file types: the existing upload handler stores whatever the browser sends (no MIME validation for registration documents). The existing admin preview/download handles unknown types via the `"other"` preview kind.
- Upload failure: the existing async-upload flow handles failures (toast notification, card stays in "Nav augšupielādēts" state).

### 6.3 Optional visibility

- When the back image is not uploaded, the document card shows "Nav augšupielādēts" (inactive badge).
- When uploaded, the card shows "Aktīvs" (active badge) + filename.
- In the admin review surface, the back panel shows "Dokuments nav iesniegts." when no document exists.
- In the Admin Hub cockpit, the "Aizmugure" tab is rendered but disabled (same as other empty-document tabs).

The parent-form label text is guidance only — the platform does not detect document type (passport vs. ID card vs. birth certificate) and therefore cannot enforce or refuse the back image based on the document kind.

---

## 7. Admin and Admin Hub Visibility

### 7.1 Django admin review surface

The registration admin change page (which hosts the review panels) gains a fourth document panel for `member_identity_back`:

- Panel title: `Bērna ID kartes aizmugure`.
- Active document: thumbnail preview (image kinds render `<img>`; PDFs render `<iframe>`; other kinds show fallback + download link).
- Replaced documents: shown in the `<details class="mms-review-history">` disclosure.
- No OCR readout (the panel builder skips OCR for kinds without extractions; the back image has none).
- Preview opens in the lightbox. Download links to the existing proxy endpoint.

### 7.2 Admin Hub cockpit

The Admin Hub review cockpit (`/hub/pieteikumi/<pk>/`) gains a fourth viewer tab:

- Tab label: "Aizmugure".
- Tab state: disabled when no back image is uploaded (same as "Portrets" when empty).
- Viewer frame: renders the document using the same viewer infrastructure as the other tabs. Image documents render as `<img>`; non-image documents show a hint to open/download.
- Toolbar: rotate, zoom, reset, open-in-new-tab, download — all functional for the back image when present.

---

## 8. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | Registration form displays the front/passport title as `Bērna personas dokuments — pase vai ID kartes priekšpuse`; the back image card shows title `Bērna ID kartes aizmugure` with helper text `Nav obligāta, bet nepieciešama, ja augšupielādēta bērna ID karte; nav vajadzīga pasei vai dzimšanas apliecībai.` immediately below the title. |
| AC2 | The front/passport document remains **required** at submission. The back image is **optional** — submission succeeds with or without it. |
| AC3 | The back image uses a distinct `Document.Kind.MEMBER_IDENTITY_BACK` kind. It is stored under existing private-document safeguards. |
| AC4 | The back image card uses the existing document-card UX: async upload, camera affordance on mobile, active/replaced state, safe replacement. |
| AC5 | No OCR is performed on the back image. `ocr_status` is `NOT_REQUESTED`. No `DocumentExtraction` row is created. |
| AC6 | The back image is visible to staff in the Django admin review surface (fourth document panel) and in the Admin Hub review cockpit (fourth viewer tab labeled "Aizmugure"). |
| AC7 | Staff preview/download of the back image uses existing proxy views with staff-only authorization. Access is audited via existing `AuditEvent` actions. |
| AC8 | No changes to guardian documents, billing, agreements, or other out-of-scope domains. |

---

## 9. Migration Strategy

One migration alters the `Document.kind` choices to add `member_identity_back`.

Adds `MEMBER_IDENTITY_BACK = "member_identity_back", "Member identity back"` to `Document.Kind`. No data migration needed.

---

*End of design specification.*

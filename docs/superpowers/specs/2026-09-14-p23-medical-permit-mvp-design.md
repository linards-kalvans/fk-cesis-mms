# P23 — Medical Permit MVP — Design Specification

**Status:** DEV complete + LAN acceptance COMPLETE — signed off 2026-09-18. Full automated verification passed (2632 tests; ruff, mypy, makemigrations check clean).

**LAN acceptance evidence (2026-09-18):** Portal/workspace auto-upload works after hard reload; card transitions to active state with filename and private preview/download links; no normal manual-upload submit path; portal card renders as full-width row; automated gate 2632 passed, ruff/mypy/makemigrations clean.

**Slice:** P23 (of P23, original scope)

**Supersedes:** `docs/superpowers/specs/2026-09-03-medical-permit-management-design.md`

**Rebased on:** `dev` branch; P16-A (Signed-agreement upload + secure serving) is already LAN complete and merged.

---

## 1. Purpose

Youth-club members require a valid medical certificate (`veselības apliecība`) to participate in training. Previously handled ad-hoc with paper or informal email exchanges. P23 introduces structured tracking of permit validity, expiry status, and parent/staff upload workflow.

---

## 2. Scope

### In scope

- A `MedicalPermit` model with `OneToOne` linkage to `RegistrationApplication` and nullable `OneToOne` linkage to `Member` (attached during approval).
- Private file storage with opaque non-PII paths (`private/medical-permits/<uuid4.hex>.<ext>`).
- Format/size validation (PDF/JPG/JPEG/PNG/HEIC; matching extension + MIME; max 25 MiB).
- Validity rule: upload/confirmation in calendar year N → valid through 30 September N+1.
- Status classification: `missing` / `current` / `expiring` (1 Aug – 30 Sep) / `expired` (1 Oct onwards).
- Three sources: `parent_upload`, `staff_upload`, `staff_confirmation`.
- Parent-facing upload, preview, and download endpoints with ownership protection.
- Staff admin actions on the registration change page and family hub (upload, confirm, clear confirmation).
- Member changelist status filters.
- Six `AuditEvent` actions with generic redacted metadata.
- Safety-first write ordering on every file mutation: validate → write storage → persist metadata → best-effort delete old file.

### Out of scope

- OCR / medical data extraction from uploaded files.
- Automatic expiry enforcement (no cron, no daily sweep).
- Reminder emails or scheduled notifications.
- Permit history / versioning.
- Public URLs.
- Invoice Ninja integration.
- DocuSeal integration.

---

## 3. Model Design

### 3.1 MedicalPermit

```python
class MedicalPermit(TimeStampedModel):
    class Source(models.TextChoices):
        PARENT_UPLOAD = "parent_upload", "Parent upload"
        STAFF_UPLOAD = "staff_upload", "Staff upload"
        STAFF_CONFIRMATION = "staff_confirmation", "Staff confirmation"

    application = OneToOneField(RegistrationApplication, on_delete=CASCADE, related_name="medical_permit")
    member = OneToOneField(Member, on_delete=SET_NULL, null=True, blank=True, related_name="medical_permit")
    file = FileField(storage=PrivateDocumentStorage(), upload_to=medical_permit_upload_to, blank=True)
    original_filename = CharField(max_length=255, blank=True, default="")
    content_type = CharField(max_length=255, blank=True, default="")
    file_size = PositiveIntegerField(default=0)
    source = CharField(max_length=32, choices=Source.choices)
    valid_until = DateField()
    confirmed_by = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True, related_name="confirmed_medical_permits")
    confirmed_at = DateTimeField(null=True, blank=True)
```

**Key decisions:**

- `OneToOne(application)` — one permit per registration application.
- Nullable `OneToOne(member)` — linked during approval via `attach_application_medical_permit`; remains `None` until approval.
- `file` is a `FileField` on private storage; `blank=True` because a confirmation-only permit has no file.
- `source` distinguishes who performed the last mutation.
- `valid_until` is computed at write time, not persisted as a rule.
- `confirmed_by` / `confirmed_at` track the staff member who confirmed receipt without a file.

### 3.2 Storage path

`medical_permit_upload_to(instance, filename)` generates `private/medical-permits/<uuid4.hex>.<ext>` where `<ext>` is the validated lowercase extension (`.pdf`, `.jpg`, `.jpeg`, `.png`, `.heic`) or empty. No PII in the stored name.

### 3.3 Validity rule

```python
def _valid_until_for(year: int) -> date:
    return date(year + 1, 9, 30)
```

Every upload or confirmation in calendar year N sets `valid_until` to 30 September of year N+1.

### 3.4 Status classification

```python
def medical_permit_status(permit, *, on=None) -> str:
    # on defaults to timezone.localdate()
    if permit is None:
        return "missing"
    if not permit.file and not permit.confirmed_by_id:
        return "missing"
    if on < permit.valid_until.replace(month=8, day=1):
        return "current"
    if on <= permit.valid_until:
        return "expiring"
    return "expired"
```

- `missing`: no permit row, or a row with neither a stored file nor a staff confirmation.
- `current`: today is before 1 August of the validity year.
- `expiring`: 1 August through 30 September inclusive.
- `expired`: 1 October onwards.

---

## 4. Service Layer

All services live in `apps/documents/medical_permits.py`.

### 4.1 Format/size validation

`validate_medical_permit_upload(upload)` — checks: non-null, size ≤ 25 MiB, extension/MIME pair is in the allowed set (`("pdf", "application/pdf")`, `("jpg", "image/jpeg")`, `("jpeg", "image/jpeg")`, `("png", "image/png")`, `("heic", "image/heic")`). Raises `ValueError` with Latvian messages.

### 4.2 Safety-first write ordering

`_write_permit_file(permit, upload, *, source)` — the canonical write primitive used by all mutation services:

1. Write candidate file to private storage.
2. Persist new metadata to database.
3. Best-effort delete old file.

On failure before step 2: old file and row untouched. On failure at step 3: orphan file may remain but never contradicts persisted state.

### 4.3 Public service functions

| Function | Purpose | Audit event |
|---|---|---|
| `replace_medical_permit(permit, upload, *, actor_label, actor)` | Replace stored file; clears prior staff confirmation | `medical_permit_replaced` |
| `upload_application_medical_permit(application, upload, *, actor_label, actor)` | Create or fill application permit; creates member link if approved | `medical_permit_uploaded` (first write) / `medical_permit_replaced` |
| `upload_member_medical_permit(member, upload, *, actor_label, actor)` | Create or replace member-linked permit; requires source application | `medical_permit_uploaded` (first write) / `medical_permit_replaced` |
| `confirm_medical_permit(permit, *, actor)` | Record staff confirmation (no file); clears stored file | `medical_permit_confirmed` |
| `clear_medical_permit_confirmation(permit, *, actor)` | Remove staff confirmation; never touches stored file | `medical_permit_confirmation_cleared` |
| `attach_application_medical_permit(application, member)` | Link application permit to approved member (idempotent) | None |

### 4.4 Parent upload gating

`can_parent_upload_application_medical_permit(application)` — returns `True` for `draft`, `fix_requested`, `submitted`, and `approved` statuses. Returns `False` for `rejected` and any other status. This is the policy gate; ownership and HTTP status are enforced at the view layer.

### 4.5 Approval integration

`approve_application` calls `attach_application_medical_permit(application, member)` after `Member.objects.create(...)`. Idempotent: if the permit is already linked to the member, no-op. If the permit exists but is linked to a different member, no-op (never repoints).

---

## 5. Parent-Facing Endpoints

All routes live under the `registrations` namespace.

### 5.1 Upload

- `POST /applications/<id>/medical-permit/upload/` — application-scoped upload. Ownership-scoped to the application's `parent_account`. Creates permit row if missing; replaces stored file if present.
- `POST /portal/members/<id>/medical-permit/upload/` — member-scoped upload. Guardian owner only. Creates permit row linked to both member and source application if missing; replaces stored file if present.

Both return JSON `201` on success, `400` on validation error. Rejected applications return `404` for the application endpoint.

### 5.2 Preview / Download

- `GET /portal/medical-permits/<id>/preview/` — streams file inline (`Content-Disposition: inline`).
- `GET /portal/medical-permits/<id>/download/` — streams file as attachment (`Content-Disposition: attachment`).

Ownership enforcement: verified guardian of the linked application's parent account; anonymous → redirect to registration start; foreign/missing/file-less → `404`.

### 5.3 Surface rendering

**Reusable card partial** (`templates/parent_ui/includes/medical_permit_card.html`): shared parent-UI component that renders the medical permit using the same `fk-document-card` grammar as the identity-document and portrait cards (`document_card.html`). One partial consumed by both workspace and portal surfaces.

**Async upload behavior (P23 async UI refinement):**
- Normal parent permit upload auto-starts on file selection in both portal and editable workspace. There is no separate manual submit button for normal uploads — the upload triggers immediately when the user selects a file.
- The existing parent upload endpoints (`POST /applications/<id>/medical-permit/upload/` and `POST /portal/members/<id>/medical-permit/upload/`) still authorize the same way and return HTTP 201 JSON containing safe UI data: `filename`, `status`/`status_label`, and private `preview_url`/`download_url`.
- The browser updates the permit card in place after upload completes — no full page reload, no OCR dependency. Errors render as Latvian inline alerts. The card shows active state, replacement links, and private preview/download actions.

**Application workspace** (`application_workspace.html`): renders the medical permit card immediately after the parent ID, child ID, and portrait document cards (step 1 of the wizard). The card shows a visible `Neobligāti` label. No submit/wizard gate — the permit is optional and does not block step advancement. The native file input is hidden (`.fk-visually-hidden`); upload is triggered via a full-width `<label>` control. Uploaded state displays the filename, replace link, and secure preview/download links.

- **No-JS fallback (editable workspace):** a `<noscript>` form rendered after the wizard close, never nested inside the wizard `<form>`. The normal JS-visible workspace has no external permit form and no `form=` association.
- **JS-visible workspace:** upload auto-starts on file selection; no standalone permit form exists in the DOM.

**Parent portal** (`parent_portal.html`): permit card renders as a dedicated full-width row after the progress bar and before the CTA buttons, for every policy-allowed application (draft/fix_requested/submitted/approved) with status label + August-starting expiry warning (`data-medical-permit-warning`), preview/download/upload buttons. Confirmation-only permits show no file links. After approval the member-scoped upload route (`/portal/members/<id>/medical-permit/upload/`) becomes available; before approval only the application-scoped route (`/applications/<id>/medical-permit/upload/`) is used.

- **No-JS fallback (portal):** the portal card includes a standalone multipart fallback form so upload works without JavaScript.

**Rejected applications**: upload controls hidden; application endpoint returns `404` for the owning parent.

**Approved with signed agreement**: member upload route stays available; agreement state does not block upload.

**CSS**: all styling is inherited from the existing `fk-document-card` / `fk-upload-slot` / `fk-visually-hidden` rules in `static/css/parent_theme.css`. No new CSS file or CSS additions are required.

### 5.4 No email on upload

Uploads are silent — no email is sent. Verified by outbox assertions in parent-flow tests.

---

## 6. Admin Surfaces

### 6.1 Registration application change page

The medical permit module renders status label, upload form, confirm button (without file), and clear confirmation button. Actions dispatch through the existing review-action POST endpoint.

### 6.2 Guardian family hub

Per-child medical permit status + upload/confirm/clear actions. Status computed per child via `medical_permit_status` helper.

### 6.3 Changelist filters

- `RegistrationMedicalPermitStatusFilter` on `RegistrationApplicationAdmin` — binds to `application_id`, options: `Trūkst` / `Beidzas` / `Beidzies`.
- `MemberMedicalPermitStatusFilter` on `MemberAdmin` — binds to `member_id`, same options.

Both use the shared `MedicalPermitStatusFilter` base class.

---

## 7. Audit Contract

Six `AuditEvent.Action` choices added to `AuditEvent.Action`:

| Action | Latvian label |
|---|---|
| `MEDICAL_PERMIT_UPLOADED` | Veselības apliecība augšupielādēta |
| `MEDICAL_PERMIT_REPLACED` | Veselības apliecība aizvietota |
| `MEDICAL_PERMIT_CONFIRMED` | Veselības apliecība apstiprināta |
| `MEDICAL_PERMIT_CONFIRMATION_CLEARED` | Veselības apliecības apstiprinājums noņemts |
| `MEDICAL_PERMIT_PREVIEWED` | Veselības apliecība priekšskatīta |
| `MEDICAL_PERMIT_DOWNLOADED` | Veselības apliecība lejupielādēta |

**Metadata contract:** `{"source": "parent_upload" | "staff_upload" | "staff_confirmation"}`. Never includes filename, personal data, medical data, or file bytes.

---

## 8. Migration Chain

- `core/0012_alter_auditevent_action.py` — final state-altering audit-choice migration; retains all earlier choices and adds six P23 medical-permit choices. Depends on `core/0011_audit_application_data_edited`.
- `documents/0007_medicalpermit.py` — creates `MedicalPermit` table. Depends on `documents/0006_alter_document_kind`, `members/0012_memberexporttemplate`, `registrations/0012_submission_digest_settings`, and `AUTH_USER_MODEL`.

---

## 9. Files Changed

| File | Responsibility |
|---|---|
| `apps/documents/models.py` | `MedicalPermit` model + `medical_permit_upload_to` helper |
| `apps/documents/medical_permits.py` | Service layer (all public functions + status helpers + upload gating) |
| `apps/documents/admin_filters.py` | `MedicalPermitStatusFilter` base + `RegistrationMedicalPermitStatusFilter` + `MemberMedicalPermitStatusFilter` |
| `apps/core/models.py` | Six `AuditEvent.Action` choices (in the `Action` nested class) |
| `templates/parent_ui/includes/medical_permit_card.html` | Reusable parent-UI card partial: `fk-document-card` grammar, `Neobligāti` label, hidden native input + full-width label, uploaded state (filename/replace/preview/download). Workspace uses HTML `form` attribute for upload form; portal uses standalone multipart form. |
| `apps/registrations/views.py` | Parent upload/preview/download views; portal/workspace context injection |
| `apps/registrations/urls.py` | Parent medical permit routes |
| `apps/registrations/admin.py` | Registration admin change page actions (upload/confirm/clear) |
| `apps/registrations/admin_panels.py` | `build_review_context` adds permit status/label/has_file |
| `apps/registrations/services.py` | `attach_application_medical_permit` called in `approve_application` |
| `apps/members/admin.py` | Member changelist filter; family hub medical permit actions |
| `apps/members/family_hub.py` | Per-child permit status in family hub |
| `tests/documents/test_medical_permit_model.py` | Model shape, constraints, cascade, status boundaries |
| `tests/documents/test_medical_permit_services.py` | Service layer: upload, replace, confirm, clear, attach, status, validation, safety ordering |
| `tests/documents/test_medical_permit_parent_flow.py` | Parent upload, portal rendering, status-scoped surfaces, rejected-app blocking, signed-agreement upload |
| `tests/documents/test_medical_permit_access.py` | Proxy endpoint authorization, audit metadata redaction |
| `tests/documents/test_medical_permit_admin.py` | Admin filters, change-page actions, family hub actions |

---

## 10. Future Milestones / Follow-ups

- **Admin Hub medical permit status and actions** — medical permit status visibility and staff controls in the Admin Hub (`/hub/`), consistent with the existing family hub and registration admin surfaces.

---

*End of P23 medical permit MVP design specification.*

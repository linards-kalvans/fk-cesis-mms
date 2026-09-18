# P23 — Medical Permit Management

**Date:** 2026-09-03
**Status:** DEV complete — implementation delivered, full automated verification passed (2235 tests; ruff, mypy, makemigrations check clean). LAN acceptance not performed.

---

## 1. Problem

Youth-club members require a valid medical certificate (veselības apliecība) to participate in training. The club needs a way for parents to upload certificates, for staff to confirm receipt (even without a file), and to track validity across the September–August sports year. Previously this was handled ad-hoc with paper or informal email exchanges.

## 2. Scope

**In scope**

- A new `MedicalPermit` model with OneToOne linkage to `RegistrationApplication` and nullable OneToOne linkage to `Member` (attached during approval).
- Private file storage with opaque, non-PII paths (`private/medical-permits/<uuid>.<ext>`).
- Format/size validation (PDF, JPG/JPEG, PNG, HEIC; matching extension + MIME; max 25 MiB).
- Validity rule: year N upload/confirmation → valid through 30 September N+1.
- Status classification: `missing` / `current` / `expiring` (1 Aug – 30 Sep) / `expired` (1 Oct onwards).
- Three sources: `parent_upload`, `staff_upload`, `staff_confirmation`.
- Parent-facing upload, preview, and download endpoints with ownership protection.
- Staff admin actions on the registration change page and family hub (upload, confirm, clear confirmation).
- Member changelist status filters.
- Six `AuditEvent` actions with generic redacted metadata.

**Explicitly out of scope**

- OCR / medical-data extraction from uploaded files.
- Automatic expiry enforcement (no billing or registration block on expired permits).
- Reminder emails or notifications for expiring/expired permits.
- Permit history tracking (no audit trail of past permits beyond the current row).
- Public URLs for permit access (all access is through authenticated proxies).
- Parent self-service confirmation (only staff can confirm without a file).

## 3. Data Model

### `MedicalPermit` (`apps/documents/models.py`)

| Field | Type | Notes |
|---|---|---|
| `application` | `OneToOneField(RegistrationApplication)` | Always set; permit originates on the application |
| `member` | `OneToOneField(Member, null=True, blank=True)` | Set during approval via `attach_application_medical_permit()` |
| `file` | `FileField` (private storage) | Blank when no file stored (staff confirmation case) |
| `original_filename` | `CharField` | Blank when no file |
| `content_type` | `CharField` | Blank when no file |
| `file_size` | `PositiveIntegerField` | 0 when no file |
| `source` | `CharField` (TextChoices) | `parent_upload` / `staff_upload` / `staff_confirmation` |
| `valid_until` | `DateField` | 30 September of the year after the upload/confirmation year |
| `confirmed_by` | `ForeignKey(User, null=True)` | Staff user who confirmed without a file |
| `confirmed_at` | `DateTimeField (nullable)` | When the staff confirmation was recorded |

### `medical_permit_upload_to` helper

Generates opaque paths: `private/medical-permits/<uuid4.hex>.<ext>`. Extension is validated against the allowed set; mismatched extensions are dropped (empty string). The path contains no PII.

### `AuditEvent.Action` additions (migration `core/0010`)

- `MEDICAL_PERMIT_UPLOADED` — first upload or member-attachment upload
- `MEDICAL_PERMIT_REPLACED` — subsequent file replacement
- `MEDICAL_PERMIT_CONFIRMED` — staff confirmation (no file)
- `MEDICAL_PERMIT_CONFIRMATION_CLEARED` — staff removes a confirmation
- `MEDICAL_PERMIT_PREVIEWED` — parent preview
- `MEDICAL_PERMIT_DOWNLOADED` — parent download

Metadata is redacted: only `source` and permit PK are recorded; never filenames, medical data, or file bytes.

## 4. Validity and Status Rules

### Validity calculation

`_valid_until_for(year)` returns `date(year + 1, 9, 30)`. Every upload or staff confirmation resets the validity to 30 September of the following calendar year.

### Status classification

`medical_permit_status(permit, on=today)` returns one of:

| Status | Condition |
|---|---|
| `missing` | No permit row, or no file and no `confirmed_by` |
| `current` | `today < valid_until.replace(month=8, day=1)` (before 1 August of the validity year) |
| `expiring` | `today >= 1 August of validity year` AND `today <= valid_until` |
| `expired` | `today > valid_until` (1 October onwards) |

No automatic file deletion occurs on expiry. Expired permits remain in the database; they just show the `expired` status label.

## 5. Service Layer

### `apps/documents/medical_permits.py`

| Function | Purpose |
|---|---|
| `validate_medical_permit_upload(upload)` | Validates format/size; raises `ValueError` on failure |
| `_write_permit_file(permit, upload, source)` | Safe replacement: write storage → persist metadata → delete old file |
| `replace_medical_permit(permit, upload, actor_label, actor)` | Replace with a validated upload; emits `medical_permit_replaced` |
| `upload_application_medical_permit(application, upload, actor_label, actor)` | First upload for an application permit; creates row if missing; emits `medical_permit_uploaded` |
| `upload_member_medical_permit(member, upload, actor_label, actor)` | Upload for a member-linked permit; requires source application; emits `medical_permit_uploaded` or `medical_permit_replaced` |
| `confirm_medical_permit(permit, actor)` | Staff confirmation without file; clears stored file best-effort; emits `medical_permit_confirmed` |
| `clear_medical_permit_confirmation(permit, actor)` | Remove staff confirmation; never touches stored file; emits `medical_permit_confirmation_cleared` |
| `attach_application_medical_permit(application, member)` | Idempotent link of application permit to approved member; never repoints an existing link |

### Safety ordering (replacement)

Every write follows a strict order:
1. Validate the upload (format, size, MIME/extension match).
2. Write the candidate file to private storage.
3. Persist the new metadata to the database.
4. Best-effort delete the old file.

On any failure before step 3, the old file and row reference are untouched. On failure at step 4, an orphan file may remain on disk but never contradicts the persisted state.

### Safety ordering (confirmation)

Confirmation persists the database row first (file cleared, source = `staff_confirmation`, validity reset), then best-effort deletes the stored file. A DB failure leaves the original row and file intact. A storage-delete failure may leave an orphan file but never contradicts the persisted confirmation state.

## 6. Parent UX

### Application workspace (`/applications/<id>/`)

- After approval, the medical permit section shows the current status label (`Derīga` / `Darbības termiņš drīz beigsies` / `Darbības termiņš beidzies` / `Vēl nav iesniegta`).
- When a file exists: "Skatīt" (preview) and "Lejupielādēt" (download) buttons link through private proxy endpoints (`medical_permit_preview`, `medical_permit_download`) that enforce parent ownership.
- When no file exists: a file upload form (`accept=".pdf,.jpg,.jpeg,.png,.heic"`) posts to `application_medical_permit_upload`.
- First child permit after approval is supported (the application's permit row is auto-created on first upload).

### Parent portal (`/portal/`)

- Each application card shows the medical permit status label and a warning indicator (`data-medical-permit-warning`) for `expiring` / `expired`.
- When a file exists: "Skatīt" / "Lejupielādēt" buttons.
- When no file exists: a file upload form identical to the workspace form.

### Ownership protection

All preview/download endpoints (`medical_permit_preview`, `medical_permit_download`) enforce that the requesting parent owns the linked application's `parent_account`. Non-owning requests receive `404`. Anonymous requests are redirected to admin login.

### Current UX note

Parent upload endpoints currently return JSON `201` on success and `400` on validation failure. The workspace/portal templates post forms normally (non-AJAX). The async upload UX (spinner, toast, polling) used for identity documents is **not** implemented for medical permits — this is a deferred MINOR polish item.

## 7. Staff UX

### Registration admin change page

The `build_review_context()` function annotates the change page with:
- `medical_permit_status` (machine value: `missing`/`current`/`expiring`/`expired`)
- `medical_permit_status_label` (Latvian label)
- `medical_permit_has_file` (boolean)

The `_medical_permit_module.html` partial renders:
- Status label
- "Pievienot failu" button (file upload → `staff_upload`)
- "Apstiprināt bez faila" button (staff confirmation → `staff_confirmation`)
- "Noņemt apstiprinājumu" button (clear confirmation, only when `confirmed_by` is set)

### Registration changelist

`RegistrationMedicalPermitStatusFilter` adds a "Veselības apliecība" filter with options: "Trūkst", "Beidzas", "Beidzies".

### Member changelist

`MemberMedicalPermitStatusFilter` provides the same three status options on the Member admin list.

### Family hub (Guardian admin page)

Each child row in the family hub shows the medical permit status label. Staff can:
- Upload a file for a specific child
- Confirm without a file
- Clear an existing confirmation

All actions are POSTed to the guardian change page with hidden `action` fields.

## 8. Private Storage and Access Posture

- Medical permit files live in `PrivateDocumentStorage` under `private/medical-permits/`.
- Stored names are opaque: `private/medical-permits/<uuid4.hex>.<ext>`. No PII.
- Preview and download are served through Django proxy views (`medical_permit_preview`, `medical_permit_download`) that:
  - Open the file from private storage.
  - Stream it with the correct `Content-Type`.
  - Enforce ownership (parent) or staff authentication (admin).
- The raw external file URL is never exposed or bookmarkable.

## 9. Audit Events

Six `AuditEvent.Action` values added in migration `core/0010`:

| Action | When emitted | Metadata |
|---|---|---|
| `MEDICAL_PERMIT_UPLOADED` | First upload (application or member) | `{"source": "parent_upload" | "staff_upload"}` |
| `MEDICAL_PERMIT_REPLACED` | Subsequent upload (application or member) | `{"source": "parent_upload" | "staff_upload"}` |
| `MEDICAL_PERMIT_CONFIRMED` | Staff confirms without file | `{"source": "staff_confirmation"}` |
| `MEDICAL_PERMIT_CONFIRMATION_CLEARED` | Staff removes confirmation | `{"source": "parent_upload" | "staff_confirmation"}` |
| `MEDICAL_PERMIT_PREVIEWED` | Parent previews permit | (none) |
| `MEDICAL_PERMIT_DOWNLOADED` | Parent downloads permit | (none) |

All metadata is generic and redacted. Never includes filenames, medical data, or file bytes.

## 10. Migrations

- `documents/0006_medicalpermit.py` — creates the `MedicalPermit` model with `OneToOne` to `RegistrationApplication`, nullable `OneToOne` to `Member`, and nullable `ForeignKey` (confirmation) to `User`, plus all metadata fields.
- `core/0010_alter_auditevent_action.py` — adds six new `AuditEvent.Action` choices.

## 11. Verification

Full automated verification evidence (as reported by the implementation agent):
- `uv run pytest -q` → **2235 passed**
- `uv run ruff check .` → clean
- `uv run mypy .` → clean
- `uv run python manage.py makemigrations --check` → no changes

Test files:
- `tests/documents/test_medical_permit_model.py` — model defaults, constraints, choices, cascade
- `tests/documents/test_medical_permit_services.py` — service layer: upload, replace, confirm, clear, attach, status classification, validity calculation, format validation, safety ordering
- `tests/documents/test_medical_permit_parent_flow.py` — parent upload, preview, download, ownership enforcement
- `tests/documents/test_medical_permit_access.py` — proxy endpoint authorization (anonymous, non-owner, owner, staff)
- `tests/documents/test_medical_permit_admin.py` — admin actions on registration change page and family hub, status filters on changelist

No LAN/manual acceptance was performed in this session.

## 12. Deferred / Non-Blocking Items

- **Parent async upload UX:** Medical permit upload currently uses a synchronous form POST (JSON 201/400 responses). The async upload UX (spinner, toast, polling) used for identity documents is not implemented. This is a MINOR polish item — the current synchronous flow is functional.
- **Expiry enforcement:** Expired permits are visible but do not block any workflow (billing, registration, training). Enforcement is deferred.
- **Reminder emails:** No automated reminders for expiring/expired permits. Deferred.
- **Permit history:** Only the current permit is stored. A replacement overwrites the previous file. History is deferred.

## 13. Related Documentation

- Plan: `docs/superpowers/plans/2026-09-03-medical-permit-management.md`
- Milestones: `docs/milestones.md` (P23 entry)
- AGENTS.md: Current Status section (P23 bullet)

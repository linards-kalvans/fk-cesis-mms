# P16-A — Signed-Agreement Artifact Upload and Serve — Design Specification

**Date:** 2026-09-02
**Status:** DEV complete — targeted verification passed (85 P16-A tests; code review approved; mypy and migration check clean). Repository-wide pytest/ruff gates are currently blocked by unrelated unimplemented MedicalPermit work; LAN acceptance pending.
**Slice:** P16-A (of P16, split from original "Signed-agreement upload + verification")
**Parent milestone:** M3 — Approval-to-membership and agreement completion
**Supersedes:** `docs/superpowers/specs/2026-08-25-roadmap-p16-p18-design.md` §1 (P16 scope replaced by P16-A + P16-B)

---

## 0. Table of Contents

1. [Problem](#1-problem)
2. [Scope](#2-scope)
3. [Design Decisions with Rationale](#3-design-decisions-with-rationale)
4. [Components and Data Flow](#4-components-and-data-flow)
5. [Authorization, Security, and Privacy](#5-authorization-security-and-privacy)
6. [Error and Retry Behavior](#6-error-and-retry-behavior)
7. [Migration and Rollout Strategy](#7-migration-and-rollout-strategy)
8. [Acceptance Criteria](#8-acceptance-criteria)
9. [Test Strategy](#9-test-strategy)
10. [Relationship to P16-B](#10-relationship-to-p16-b)

---

## 1. Problem

FK Cēsis MMS generates agreements through DocuSeal (electronic path) or paper (manual path). The `Agreement` model tracks a lifecycle state (`generated → sent → signed → void → superseded / discontinued`) but does **not** store the signed artifact itself. Staff currently keep signed PDFs or `.edoc` files externally (email, shared drives, physical files) with no platform-side custody.

The family hub and parent portal need a reliable, private, authorization-checked way to present the signed agreement to guardians. Staff need a simple, audited upload path in the admin review panel. The system must enforce exactly-one-current-artifact-per-agreement semantics, reject unsupported files, and preserve prior artifacts until replacement succeeds.

This slice delivers **upload + serve** only. No cryptographic verification, no provider integration, no background jobs. That work belongs to P16-B.

---

## 2. Scope

### 2.1 In scope

| # | Capability |
|---|-----------|
| S1 | Staff-only upload of a signed agreement file (PDF or `.edoc`) to any `Agreement` lifecycle state via the registration-admin agreement panel. Upload does **not** transition agreement state, create billing records, or call any provider. Registration admin must surface **every** `Agreement` for the application's approved member (current, superseded, voided, discontinued) so staff can upload/replace artifacts on historical states. |
| S2 | Exactly one current signed artifact per `Agreement`. Fields are on the `Agreement` model itself: `signed_artifact` (private `FileField`), `signed_artifact_original_filename`, `signed_artifact_content_type`, `signed_artifact_file_size`, `signed_artifact_uploaded_at` (first upload), `signed_artifact_updated_at` (every successful replacement). Replacement atomically saves new file + metadata, commits DB, then permanently deletes the old private object. If any save/persistence step fails, old artifact and metadata remain. |
| S3 | Accepted suffixes (case-insensitive): `.pdf`, `.edoc`. Maximum size from `SIGNED_ARTIFACT_MAX_BYTES` (default 20 MiB). PDF MIME/type checked where reliable; `.edoc` has no assigned MIME type. Unsupported, mismatched, oversized files fail with a Latvian user-safe error and preserve the existing file. |
| S4 | No separate artifact model. All artifact data lives on `Agreement` as a single `FileField` plus metadata columns. No reuse of the registration `Document` / `DocumentExtraction` models. No validation fields, no version token in P16-A. |
| S5 | Serve only via Django authorization-checked proxy views. Staff download/serve at registration admin, guardian family hub, and read-only agreement admin. Guardian gets only their own family artifacts through the verified parent portal, listed per member across all agreement states (current, superseded, voided, discontinued), ordered newest first. Non-owners receive not-found. No raw storage URL or public link is ever exposed. |
| S6 | PDF: staff can inline-preview or forced-download. Guardian forced-download. `.edoc` always forced-download. |
| S7 | When an artifact exists, staff and guardian show neutral Latvian `Status nav pieejams`. When no artifact exists, no signed-artifact card or status is rendered. No verification data persisted. No background job. `Status nav verificēts` is not rendered in P16-A. |
| S8 | Every upload/replacement emits a single redacted `AuditEvent.Action.SIGNED_ARTIFACT_UPLOADED` with metadata `{"agreement_id": N, "operation": "uploaded" | "replaced"}`. Never bytes, filename, signer, validation result, file size, or personal data. |
| S9 | P16-A out of scope: all validation/provider traffic/background jobs, interactive signing, verification persistence, raw external URLs. |

### 2.2 Out of scope

- eParaksts SignAPI integration, OAuth token flow, or any cryptographic validation.
- Artifact version tokens, validation records, or stale-result race safety (P16-B).
- Automatic billing/invoice creation on upload.
- Interactive in-portal signing.
- Raw provider URL exposure.
- Reusing the registration `Document` / `DocumentExtraction` models.

---

## 3. Design Decisions with Rationale

### D1. Fields on `Agreement`, not a separate model

**Decision:** Artifact fields live directly on the existing `Agreement` model: `signed_artifact` (`FileField`), `signed_artifact_original_filename`, `signed_artifact_content_type`, `signed_artifact_file_size`, `signed_artifact_uploaded_at`, `signed_artifact_updated_at`. There is exactly one current artifact because it is a single field.

**Rationale:** The artifact is conceptually part of the agreement — one signed file per agreement. A separate model would add an unnecessary ORM join for what is always a 1:1 relationship. A single `FileField` on `Agreement` enforces exactly-one-current semantics at the ORM level (no list, no unique constraint on a dynamic key) and simplifies queries. The transaction order (validate → save new → commit DB → delete old) guarantees atomicity: if any step fails, the prior artifact survives. This is the safest order for file storage — delete last, after persistence is confirmed.

### D2. No P16-B schema in P16-A

**Decision:** P16-A does **not** create `AgreementSignedArtifactValidation`, `signed_artifact_version`, or any validation-related fields. P16-B will be a separate, later slice that adds these on top of the P16-A `Agreement` fields.

**Rationale:** P16-B is blocked on eParaksts test credentials. Bundling P16-B schema into P16-A would block P16-A delivery for an indeterminate wait. P16-A is independently useful: staff can upload and serve signed artifacts today. P16-B's migration will add columns to `Agreement` and create the validation model. The two slices share the `Agreement` model but have zero cross-dependency in their implementation code.

### D3. One `FileField` with replacement semantics

**Decision:** `Agreement.signed_artifact` is a single `FileField` (not a list or related model). Replacement saves the new file, updates metadata, commits the DB, then deletes the old private object.

**Rationale:** Exactly-one-current semantics is simpler to enforce at the ORM level (no list, no unique constraint on a dynamic key). The transaction order (validate → save new → commit DB → delete old) guarantees atomicity: if any step fails, the prior artifact survives. This is the safest order for file storage — delete last, after persistence is confirmed.

### D4. Proxy views, never raw storage URLs

**Decision:** All artifact access goes through Django views that check authorization (staff permission for admin/hub; parent ownership for guardian portal) and stream the file from private storage. No `FileField.url` is exposed to templates or the browser.

**Rationale:** Private storage (`PRIVATE_DOCUMENTS_ROOT`) may be a cloud bucket with presigned URLs that are time-limited and scoped. Exposing those URLs would bypass Django's authorization checks and allow URL sharing. Proxy views ensure every access is auditable (via Django's request middleware) and permission-gated.

### D5. Status text: neutral only, no "not verified"

**Decision:** P16-A surfaces only one derived status string: `Status nav pieejams` (when an artifact exists). When no artifact exists, no signed-artifact card or status is rendered at all. No `has_artifact` boolean, no status enum, no persisted flag.

**Rationale:** P16-A has no verification data. The status is a pure function of artifact existence. Adding a "not verified" status would imply that verification is expected or imminent, which is misleading before P16-B. P16-B will add the real status values (`valid`, `invalid`, `unavailable`) when verification lands. `Status nav verificēts` is not used in P16-A.

### D6. Latvian-only user-facing copy

**Decision:** All user-visible strings (error messages, status labels, button labels) are in Latvian. No English fallback text.

**Rationale:** The parent and admin surfaces are Latvian-only. English strings would leak into the rendered page and fail the copy-contract regression test (`tests/registrations/test_parent_surface_copy_contract.py`). This is consistent with the existing pattern established in P4 Slice E.

### D7. No audit of file content or size

**Decision:** The `AuditEvent.metadata` for upload/replace contains only `agreement_id` and operation (`uploaded` / `replaced`). No filename, no file size, no signer name, no MIME type, no bytes.

**Rationale:** The audit log is append-only and retained for 730 days (configurable). Storing filenames or file sizes could be considered quasi-PII (filenames sometimes contain personal identifiers). The agreement ID is sufficient for forensic tracing (staff can look up the agreement to find the artifact). This follows the existing redaction policy established in P7.

---

## 4. Components and Data Flow

### 4.1 Data model

```python
# apps/agreements/models.py

# Fields added to the existing Agreement model:
class Agreement(models.Model):
    # ... existing fields ...

    signed_artifact = models.FileField(
        upload_to="agreement-artifacts/%Y/%m/%d/",
        storage=private_storage,
        max_length=500,
        blank=True,
        default="",
    )
    signed_artifact_original_filename = models.CharField(
        max_length=500, blank=True, default=""
    )
    signed_artifact_content_type = models.CharField(
        max_length=255, blank=True, default=""
    )
    signed_artifact_file_size = models.PositiveBigIntegerField(default=0)
    signed_artifact_uploaded_at = models.DateTimeField(null=True, blank=True)
    signed_artifact_updated_at = models.DateTimeField(null=True, blank=True)
```

- **`signed_artifact`** — `FileField` pointing at `private_storage` (the same `PrivateDocumentStorage` used by the registration `Document` model).
- **`signed_artifact_original_filename`** — snapshot of the uploaded file's basename. Preserved even if the storage backend renames the physical file.
- **`signed_artifact_content_type`** — as reported by the browser / `request.FILES` `content_type` attribute. Not validated to be authoritative (PDF MIME check is best-effort).
- **`signed_artifact_file_size`** — in bytes, from `file.size`.
- **`signed_artifact_uploaded_at`** — set on first upload.
- **`signed_artifact_updated_at`** — set on every successful replacement.
- **No `version_token`** — added by P16-B.
- **No `is_valid` / `validation_error_code`** — added by P16-B.
- **No separate artifact model** — all data is on `Agreement`.

### 4.2 Service layer

```python
# apps/agreements/services.py

def upload_signed_artifact(
    agreement: Agreement,
    file_upload: File,
    actor: User,
) -> Agreement:
    """Upload or replace the signed artifact for an agreement.

    Replacement order:
    1. Validate candidate file (suffix, size, MIME where reliable).
    2. Save new file + update Agreement metadata fields.
    3. Commit DB transaction.
    4. Permanently delete old private file object (if any).

    Raises ValueError on validation failure (old artifact preserved).
    Emits AuditEvent on success.
    Returns the updated Agreement instance.
    """
```

**Validation rules inside `upload_signed_artifact`:**

| Check | Rule | Error (Latvian) |
|-------|------|-----------------|
| Suffix | Case-insensitive `.pdf` or `.edoc` | "Neatbalstītais faila formāts. Pieņemti tikai PDF vai .edoc faili." |
| Size | `file.size <= SIGNED_ARTIFACT_MAX_BYTES` | "Faila izmērs pārsniedz atļauto robežu." |
| PDF MIME | If suffix is `.pdf`, `content_type` starts with `application/pdf` (best-effort) | "PDF failam jābūt ar 'application/pdf' tipu." |

**Note on MIME check:** Browsers may report incorrect `content_type` for PDFs (e.g., `application/octet-stream`). The check is best-effort — a mismatched MIME for a `.pdf` file is rejected, but an `.edoc` file has no assigned MIME type and passes without MIME check.

### 4.3 Admin integration

**Registration admin agreement panel** (in `apps/registrations/admin_panels.py`):

- A new panel section renders above the existing agreement module.
- Displays **every** `Agreement` for the application's approved member (ordered newest first), including current, superseded, voided, and discontinued states.
- For each agreement with an artifact: shows filename (redacted — only first 20 chars + extension), upload date, and two action buttons: "Lejupielādēt" (forced-download proxy) and "Aizvietot" (triggers the upload form).
- For each agreement without an artifact: no signed-artifact card or status is rendered.
- The upload form is a POST endpoint on the admin change page (via `get_urls()`), gated on `has_change_permission` for the `RegistrationApplication`.

**Read-only agreement admin** (in `apps/agreements/admin.py`):

- The `AgreementAdmin` change page (already read-only) renders the artifact section.
- Staff with `has_view_permission` can download/preview via proxy.
- No upload button on the agreement admin (upload is registration-admin-only).

### 4.4 Guardian family hub

- The family hub guardian detail page renders a **per-member signed-artifacts list** (ordered newest first) for every `Agreement` belonging to the guardian's members, regardless of lifecycle state (current, superseded, voided, discontinued). Each agreement with a non-empty artifact renders a card showing filename (redacted), upload date, and a proxy download link (forced-download for PDF and `.edoc`). Status text: `Status nav pieejams` (derived from artifact existence). Agreements without artifacts are not listed. DocuSeal-generated document lists (existing) remain separate and unchanged.

### 4.5 Guardian portal (parent)

- The parent portal renders a **per-member signed-artifacts list** (ordered newest first) for every `Agreement` belonging to the verified parent's members, regardless of lifecycle state (current, superseded, voided, discontinued). Each agreement with a non-empty artifact renders a card showing filename (redacted), upload date, and a proxy download link (forced-download for PDF and `.edoc`). Status text: `Status nav pieejams` (derived from artifact existence). Agreements without artifacts are not listed. When no artifacts exist for any member, no signed-artifact section is rendered. DocuSeal-generated document lists (existing) remain separate and unchanged.
- Ownership check: the proxy view verifies the requesting `ParentAccount` owns the `Member` linked to the `Agreement`. Non-owners receive a 404 (not a 403, to avoid leaking artifact existence).

### 4.6 Proxy views

```python
# apps/agreements/views.py (or apps/agreements/proxy.py)

def serve_signed_artifact(request, agreement_id):
    """Serve a signed artifact through an authorization-checked proxy.

    Staff surfaces (admin, family hub): requires staff status.
    Guardian portal: requires ParentAccount ownership of the artifact's Member.

    PDF: Content-Disposition controlled by query param (inline vs attachment).
    .edoc: Always Content-Disposition: attachment.

    Non-owners: 404 (never 403, to avoid leaking artifact existence).
    """
```

**Content-Disposition logic:**

| User type | File type | Default disposition | Override |
|-----------|-----------|---------------------|----------|
| Staff (admin/hub) | PDF | `inline` (preview) | `?download=1` → `attachment` |
| Staff (admin/hub) | .edoc | `attachment` | N/A |
| Guardian (portal) | PDF | `attachment` | N/A |
| Guardian (portal) | .edoc | `attachment` | N/A |

**404 vs 403:** Non-owners receive a 404. This prevents timing or header-based enumeration — a guardian cannot distinguish "no artifact exists" from "artifact exists but I cannot access it."

### 4.7 Audit events

```python
# apps/core/models.py — AuditEvent.Action additions

class Action(TextChoices):
    # ... existing choices ...
    SIGNED_ARTIFACT_UPLOADED = "signed_artifact_uploaded", "Parakstītā līguma augšupielāde"
```

**Metadata format:**

```json
{
    "agreement_id": 42,
    "operation": "uploaded" | "replaced"
}
```

**Actor:** The `User` who triggered the upload (staff member). `actor_label` = their email.

There is a single `SIGNED_ARTIFACT_UPLOADED` action; the `operation` field in metadata differentiates first upload from replacement. A separate `SIGNED_ARTIFACT_REPLACED` action is not used.

---

## 5. Authorization, Security, and Privacy

### 5.1 Authorization matrix

| Surface | Access | Permission check |
|---------|--------|-----------------|
| Registration admin upload | Staff with `has_change_permission` on `RegistrationApplication` | Admin `has_change_permission` gate |
| Registration admin download/preview | Staff with `has_change_permission` on `RegistrationApplication` | Proxy view: `request.user.is_staff` |
| Read-only agreement admin download/preview | Staff with `has_view_permission` on `Agreement` | Proxy view: `request.user.is_staff` |
| Guardian family hub listing + download | Staff with `has_view_permission` on `Guardian` (family hub context) | Proxy view: `request.user.is_staff`; listing queries all `Agreement`s for the guardian's members (any lifecycle state) |
| Guardian portal listing + download | Verified `ParentAccount` owning the `Member` | Proxy view: `ParentAccount` → `Guardian` → `Member` → `Agreement` ownership chain; listing queries all `Agreement`s for the parent's members (any lifecycle state, ordered newest first) |
| Non-owners (any surface) | 404 | Not found — no artifact existence leak |

### 5.2 Private storage

- Artifacts are stored under `PRIVATE_DOCUMENTS_ROOT` (`private-uploads/agreement-artifacts/`).
- No public URL is generated. `FileField.url` is never exposed to templates.
- All access is through Django proxy views that stream the file from storage after authorization.

### 5.3 File-size enforcement

- `SIGNED_ARTIFACT_MAX_BYTES` defaults to 20 MiB (20 × 1024 × 1024 = 20971520 bytes).
- Enforced at the service layer (before saving to storage).
- Configurable via environment variable: `SIGNED_ARTIFACT_MAX_BYTES`.
- Stored in `apps/core/settings.py` or read from `os.environ` at module load time.

### 5.4 Privacy

- Audit metadata never contains file bytes, filename, signer name, validation results, or file size.
- Proxy views never log file contents or paths.
- No raw storage URLs are exposed to any surface.
- Guardian portal non-owners receive 404 (not 403) to avoid leaking artifact existence.

---

## 6. Error and Retry Behavior

### 6.1 Upload validation failures

| Failure | Behavior |
|---------|----------|
| Unsupported suffix | `ValueError` raised; old artifact and metadata preserved; Latvian error shown to staff. |
| Oversized file | `ValueError` raised; old artifact and metadata preserved; Latvian error shown. |
| PDF MIME mismatch | `ValueError` raised; old artifact and metadata preserved; Latvian error shown. |
| Storage write failure | Transaction rolls back; old artifact and metadata preserved; Django error logged. |

### 6.2 No retry mechanism

P16-A has no background job or retry loop. Upload is a synchronous, staff-initiated action. If the upload fails, the staff member retries manually. This is intentional — P16-B will add the background verification job; P16-A upload is a simple admin action.

### 6.3 Replacement failure semantics

The replacement transaction order is:

1. Validate candidate file (suffix, size, MIME).
2. Save new `Agreement` fields + update metadata.
3. Commit DB transaction.
4. Permanently delete old private file object.

If step 1 fails: no DB change, old artifact intact.
If step 2 fails: transaction rolls back, old artifact intact.
If step 3 fails: DB not committed, old artifact intact (step 4 never runs).
If step 4 fails: new artifact is committed but old file not deleted — a stale artifact remains in storage. This is a low-risk edge case (the new artifact is current; the old file is orphaned and can be cleaned up manually or via a periodic storage cleanup job in a future slice). The DB metadata is correct.

---

## 7. Migration and Rollout Strategy

### 7.1 Migrations

One migration: `apps/agreements/migrations/0007_p16a_signed_artifact.py` (current migrations end at `0006_agreement_number.py`).

Adds `signed_artifact`, `signed_artifact_original_filename`, `signed_artifact_content_type`, `signed_artifact_file_size`, `signed_artifact_uploaded_at`, `signed_artifact_updated_at` to the `Agreement` model. No data migration needed (no existing artifacts to migrate).

### 7.2 Rollout order

1. Deploy migrations (adds fields to `Agreement`, no data impact).
2. Deploy code (service, admin panel, proxy views).
3. Verify: staff can upload a PDF artifact from registration admin; artifact appears in the agreement panel; proxy download works; audit event is emitted.
4. Verify: guardian portal shows artifact (when artifact exists); ownership check works (non-owner gets 404).
5. P16-B can be implemented and deployed independently at any time after P16-A.

### 7.3 No backward compatibility concerns

- No existing code references the new `Agreement` artifact fields.
- No existing `Agreement` fields are modified beyond the additions.
- P16-B will add `signed_artifact_version` to `Agreement` and create the validation model — this is additive and does not conflict with P16-A.

---

## 8. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | Staff can upload a `.pdf` or `.edoc` file to any `Agreement` state from the registration-admin agreement panel. Upload does not change agreement state, create billing records, or call any provider. |
| AC2 | Exactly one current signed artifact per `Agreement`. Replacing an artifact saves the new file, commits the DB, then deletes the old private object. If any save/persistence step fails, the old artifact and metadata remain. |
| AC3 | Accepted suffixes are case-insensitive: `.pdf`, `.edoc`. Maximum size is `SIGNED_ARTIFACT_MAX_BYTES` (default 20 MiB). PDF MIME check is best-effort. `.edoc` has no MIME check. Unsupported, mismatched, or oversized files fail with a Latvian error and preserve the existing file. |
| AC4 | Artifact fields (`signed_artifact`, `signed_artifact_original_filename`, `signed_artifact_content_type`, `signed_artifact_file_size`, `signed_artifact_uploaded_at`, `signed_artifact_updated_at`) are on the `Agreement` model. No separate artifact model. No validation fields or version token in P16-A. |
| AC5 | All artifact access goes through Django authorization-checked proxy views. Staff access is gated on staff status; guardian access is gated on parent ownership of the linked `Member`. Non-owners receive 404. No raw storage URL or public link is exposed. Guardian portal and family hub list artifacts per member across all agreement states (current, superseded, voided, discontinued), ordered newest first. |
| AC6 | PDF: staff can inline-preview (default) or forced-download (`?download=1`). Guardian forced-download. `.edoc` always forced-download. |
| AC7 | When an artifact exists, staff and guardian show neutral Latvian `Status nav pieejams`. When no artifact exists, no signed-artifact card or status is rendered. No verification data persisted. No background job. `Status nav verificēts` is not rendered in P16-A. |
| AC8 | Every upload/replacement emits a single `SIGNED_ARTIFACT_UPLOADED` `AuditEvent` with metadata `{"agreement_id": N, "operation": "uploaded" | "replaced"}`. No bytes, filename, signer, validation result, file size, or personal data in metadata. |
| AC9 | P16-A out of scope confirmed: no validation/provider traffic, no background jobs, no interactive signing, no verification persistence, no raw external URLs. |

---

## 9. Test Strategy

### 9.1 Service tests (`tests/agreements/test_signed_artifact_upload.py`)

| Test | What it verifies |
|------|-----------------|
| Upload a valid PDF | Creates `Agreement` artifact fields, sets metadata, emits `SIGNED_ARTIFACT_UPLOADED` audit event with `operation=uploaded`. |
| Upload a valid `.edoc` | Same as PDF but no MIME check. |
| Reject unsupported suffix | `ValueError` raised, old artifact preserved, no audit event. |
| Reject oversized file | `ValueError` raised, old artifact preserved. |
| Reject PDF with wrong MIME | `ValueError` raised, old artifact preserved. |
| Replace existing artifact | `Agreement` fields updated, `signed_artifact_updated_at` set, old file deleted, `SIGNED_ARTIFACT_UPLOADED` audit event with `operation=replaced`. |
| Replace failure preserves old | If save fails (e.g., DB error), old artifact and metadata remain. |
| Audit event metadata | Contains only `agreement_id` and `operation`; no filename, no bytes, no signer, no file size. |
| Case-insensitive suffix | `.PDF`, `.Pdf`, `.EDOC` all accepted. |
| Service returns `Agreement` | Return type is the updated `Agreement` instance. |

### 9.2 Admin tests (`tests/agreements/test_signed_artifact_admin.py`)

| Test | What it verifies |
|------|-----------------|
| Agreement admin renders artifact section | Read-only display when an artifact exists; no signed-artifact card when none exists. |
| `has_view_permission` gate on proxy | Non-staff users cannot access the proxy. |
| Staff download proxy streams file | Content-Type, Content-Disposition correct for PDF and `.edoc`. |
| Registration admin upload panel renders | Upload button visible, form fields present. |
| Upload via admin POST | Updates `Agreement` fields, redirects, shows success message. |

### 9.3 Proxy view tests (`tests/agreements/test_signed_artifact_proxy.py`)

| Test | What it verifies |
|------|-----------------|
| Staff can download artifact | Proxy view returns 200 with file content. |
| Guardian can download own artifact | Proxy view returns 200 with file content. |
| Guardian cannot download another's artifact | Proxy view returns 404 (not 403). |
| Non-staff cannot access staff proxy | Proxy view returns 404. |
| PDF inline disposition | `Content-Disposition: inline` for staff PDF preview. |
| PDF attachment disposition | `Content-Disposition: attachment` for guardian PDF download. |
| `.edoc` always attachment | `Content-Disposition: attachment` for all `.edoc` downloads. |
| `?download=1` forces attachment for staff PDF | `Content-Disposition: attachment` even for staff. |

### 9.4 Template tests (`tests/agreements/test_signed_artifact_templates.py`)

| Test | What it verifies |
|------|-----------------|
| Registration admin panel renders status text | `Status nav pieejams` when artifact exists; no card when no artifact. |
| Registration admin lists all agreement artifacts | Every `Agreement` for the approved member (current, superseded, voided, discontinued) with an artifact renders a card; agreements without artifacts are absent. |
| Guardian portal renders per-member artifact list | Artifact cards present for all member agreements with artifacts (any lifecycle state), ordered newest first; absent when no artifacts exist. |
| Guardian portal ordering | Cards are ordered by `signed_artifact_updated_at` descending (newest first). |
| Family hub renders per-member artifact list | Artifact cards present for all member agreements with artifacts (any lifecycle state), ordered newest first; absent when no artifacts exist. |
| Family hub ordering | Cards are ordered by `signed_artifact_updated_at` descending (newest first). |
| No `Status nav verificēts` in P16-A | Rendered HTML never contains `Status nav verificēts`. |
| Latvian copy contract | No English tokens in rendered visible text (via `test_parent_surface_copy_contract.py` pattern). |
| DocuSeal lists remain separate | Parent portal rendered HTML contains both the signed-artifact section and the existing DocuSeal generated-document section as distinct regions. |

### 9.5 Integration tests

| Test | What it verifies |
|------|-----------------|
| Upload → audit event → admin audit log | End-to-end: upload triggers audit event that appears in `AuditEventAdmin`. |
| Replacement → old file deleted → storage clean | After replacement, old file no longer exists in private storage. |

---

## 10. Relationship to P16-B

P16-A and P16-B are **independent slices** of the original P16 scope. P16-A delivers upload and serve. P16-B delivers eParaksts verification on top of P16-A artifacts.

**What P16-A deliberately excludes (to keep P16-B unblocked):**

- No `signed_artifact_version` field on `Agreement`. P16-B adds this.
- No `AgreementSignedArtifactValidation` model. P16-B creates this.
- No django-q2 job enqueue on upload. P16-B adds this.
- No validation result fields (`is_valid`, `validation_error_code`, `signer_names`, `signing_time`, `signature_format`). P16-B adds these.
- No eParaksts adapter or provider integration code. P16-B creates `apps/integrations/eparaksts.py`.
- No stale-result race safety. P16-B adds version-token comparison before validation persistence.

**Shared model:** Both slices reference the `Agreement` model. P16-A adds artifact fields; P16-B adds `signed_artifact_version` and creates the validation model. P16-B's migration adds columns to the existing `Agreement` model and creates the validation model. No P16-B code depends on P16-A code beyond the model definition.

**Deployment order:** P16-A must be deployed first (it adds fields to `Agreement`). P16-B can be deployed at any time after P16-A, independently of eParaksts credentials (P16-B has a stub mode). Production sign-off for P16-B requires live test-environment validation and production credentials/terms.

---

*End of P16-A design specification.*

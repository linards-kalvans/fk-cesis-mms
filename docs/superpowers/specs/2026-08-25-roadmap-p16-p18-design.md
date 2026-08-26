# Roadmap P16–P18 — Design Specification

**Date:** 2026-08-25
**Status:** Approved for planning
**Scope:** Three independent features (P16 signed-agreement upload, P17 configurable member export, P18 unfinished-application lifecycle). Each is self-contained and can be implemented independently.

---

## 0. Roadmap Renumbering

The following renumbering applies to the forward-looking roadmap only.

| Old label | New label | Title |
|-----------|-----------|-------|
| P16 (Custom invoices) | P19 | Custom invoices |
| P17 (Coaches and training groups) | P20 | Coaches and training groups |
| P18 (Calendar + WhatsApp attendance) | P21 | Calendar + WhatsApp attendance |
| P19 (Daily submitted-registration digest) | P22 | Daily submitted-registration digest |
| — | **P16** | **Signed-agreement upload + verification** |
| — | **P17** | **Configurable member export** |
| — | **P18** | **Unfinished-application lifecycle** |

### Rules

- `docs/milestones.md` remains the canonical forward-looking tracker. Historical plans, historical specifications, migrations, historical test annotations, and source-code comments describing original delivery retain their original milestone labels; no runtime behavior depends on a milestone number.
- Status terms:
  - **Complete** — code/checks/required acceptance signed off.
  - **Dev complete** — implementation delivered; named validation (LAN / live provider credentials / production sign-off) remains.
  - **Planned** — requirements approved but implementation has not started.
  - **Blocked** — a named external prerequisite exists.
- Future roadmap refresh must correct stale "remaining" entries and retain current validation/operational blockers without rewriting delivered historical evidence.

---

## 1. P16 — Signed-Agreement Upload + Verification

### 1.1 Problem

After admin approval and electronic signing via DocuSeal, staff may also obtain a signed agreement through an alternative channel (e.g. in-person signing with an eParaksts-qualified signature). Currently there is no way for staff to attach that signed artifact to the agreement record, and no verification that the uploaded document is a valid qualified electronic signature. Staff and parents have no visibility into whether a signed artifact exists or what it contains.

The DocuSeal integration (P5 Slice D) generates a PDF that is streamed externally through the existing `apps.agreements.document_proxy` flow. That externally streamed artifact is distinct from any staff-uploaded signed document. A staff-uploaded signed artifact must remain a separate private Agreement artifact.

### 1.2 Requirements

| # | Requirement |
|---|-------------|
| R1 | Staff-only upload of a signed PDF or `.edoc` file, attached to an Agreement. |
| R2 | The signed artifact uses private-root storage and is accessible through authorization-checked Django proxy views from: registration admin detail, family hub, agreement admin detail, and the verified guardian portal (`parent_portal.html`). |
| R3 | The signed artifact is **separate** from the DocuSeal-generated PDF (the externally streamed artifact behind `apps.agreements.document_proxy`). The DocuSeal artifact remains available as its own document. |
| R4 | One current signed artifact per Agreement. Staff re-upload permanently deletes the previous private artifact and replaces it. |
| R5 | An `AuditEvent` records staff actor, timestamp, agreement target/target ID, and operation `uploaded` or `replaced`. No signer data, no file bytes, no validation results are retained in audit metadata. |
| R6 | Upload **immediately publishes** the artifact. eParaksts validation runs best-effort in the background. |
| R7 | A valid validation result exposes: signer names, signing time, signature format, and validation status — to both admin and guardian portal surfaces. |
| R8 | Validation failure or unavailability **does not block** publication. Guardian portal shows neutral "Status nav pieejams" (status unavailable). |
| R9 | Validation adapter is stub/eparaksts behind the `apps/integrations` boundary. It obtains a service-provider OAuth Introspect token, creates/reuses a temporary SignAPI session, uploads the file, then calls the SignAPI Validation endpoint. It persists only minimized result fields and uses retry classification. |
| R10 | Raw provider payload, certificate serials, and raw signing material are **not retained**. Only: `signer_names` (list[str]), `signed_at` (datetime), `signature_format` (str), `is_valid` (bool), `validation_error_code` (str, blank). |
| R11 | The private FileField stores original filename, content type, and file size. Accepted file suffixes are case-insensitive `.pdf` and `.edoc`. Server-side validation checks: (a) suffix match, (b) MIME type where reliable (`application/pdf` for `.pdf`), (c) a configured maximum file size limit, and (d) rejection of mismatched or unsupported types. `.edoc` is not a MIME content type; no MIME value is assigned to it. |
| R12 | Re-upload clears stale validation results. An artifact version/token is stored with Agreement; the background validation task receives that version and only persists a result if it still matches the current artifact. Stale task results are discarded. |
| R13 | **Explicitly out of scope:** interactive in-portal eParaksts signing, raw provider URL exposure, use of the registration `Document`/OCR model for this artifact. |

### 1.3 Design Decisions

#### 1.3.1 Separate FileField on Agreement (not the `Document` model)

**Decision:** New `Agreement.signed_artifact` FileField using the existing `PrivateDocumentStorage` (private-root storage, not encryption) plus a companion `AgreementSignedArtifactValidation` model for validation results.

**Why:** The existing `Document` model is tightly coupled to the registration workflow (FK to `RegistrationApplication`, OCR pipeline, `field_sources`, `DocumentExtraction`). Reusing it for post-agreement signed artifacts would conflate two distinct lifecycles. A dedicated FileField on `Agreement` is simpler: one file, one lifecycle, no OCR, no application linkage. The validation result is a separate model so it can exist independently of the file (validation runs after upload completes; stale results are discarded via version token).

#### 1.3.2 Immediate publish vs. draft

**Decision:** Upload immediately publishes the artifact. No draft state.

**Why:** Staff are the only uploaders. If staff uploads, they intend it to be visible. A draft state adds complexity (who reviews drafts? auto-publish after N hours?) without clear benefit in a club-sized workflow.

#### 1.3.3 Validation as best-effort background job with version-token race safety

**Decision:** After upload, enqueue a django-q2 job that calls the eParaksts SignAPI Validation endpoint. The job classifies errors (transient → retry; terminal → persist `validation_error_code`). The upload response is always 200 regardless of validation outcome. An artifact version/token is stored with Agreement; the background task receives that version and only persists a result if it still matches the current artifact. Stale task results are discarded.

**Why:** eParaksts SignAPI may be temporarily unavailable, rate-limited, or return processing delays. Blocking the upload on validation would create a fragile UX. Best-effort background validation preserves the "upload first, verify later" pattern. The version-token mechanism ensures that if staff re-uploads while a previous validation task is still running, the stale task result is discarded and does not overwrite the correct result.

#### 1.3.4 Data minimisation in validation results

**Decision:** Persist only: `signer_names` (JSON array of strings), `signed_at` (datetime), `signature_format` (char), `is_valid` (bool), `validation_error_code` (char, blank). Do **not** persist: certificate serial numbers, raw JSON response, OCSP responder URLs, timestamp authority data, or the uploaded file bytes (beyond the FileField itself).

**Why:** eParaksts validation responses may contain certificate chain data and cryptographic material that is sensitive and unnecessary for display. GDPR minimisation: only display what staff and parents need to see.

#### 1.3.5 Four access surfaces, two authorization models

**Decision:** P16 exposes signed-artifact status and download in four surfaces:

- **Registration admin** (staff): review-page status/download plus the sole upload control.
- **Family hub** (staff): `apps/members/admin.py::GuardianAdmin` / `apps/members/family_hub.py` / `templates/admin/members/guardian/family_hub.html` renders a "Līguma paraksts" card and staff-gated download.
- **Agreement admin** (staff): read-only change-page status and `has_view_permission`-gated inline/download proxy; no upload control.
- **Guardian portal** (parent): `parent_portal.html`, served by `apps/registrations/views.py::parent_portal`, renders the card and a guardian-ownership-gated download.

All surfaces show validation status (valid/invalid/unavailable), signer names when available, signing time when available, signature format, and the private download link. The three staff surfaces share staff authorization; the guardian portal uses ownership authorization.

**Why:** Staff need the artifact where they process a family, application, or agreement. Guardians need the same understandable status in their portal, but must never access it through staff routes. Two authorization models—staff permission and guardian ownership—protect four distinct surfaces.

#### 1.3.6 Admin upload endpoint on RegistrationApplication review page

**Decision:** Staff upload is a POST endpoint on the RegistrationApplication admin review page (the existing `apps/registrations/admin.py` review panels). A file upload button triggers the POST; the endpoint validates staff permission, saves the file to the Agreement's `signed_artifact` field, and enqueues validation. The Agreement admin change page remains read-only (`has_change_permission=False`); if a separate upload surface is needed there, it would be a custom AgreementAdmin URL that preserves read-only model fields, but the primary upload surface is the registration review page.

**Why:** `AgreementAdmin` is intentionally read-only (`has_change_permission=False`, `has_add_permission=False`, `has_delete_permission=False`). The existing staff surfaces for agreement transitions are `apps/registrations/admin.py` (review panels), `apps/registrations/admin_panels.py` (review context builder), `apps/members/admin.py`/`family_hub.py` (family hub, `templates/admin/members/guardian/family_hub.html`), and `apps/agreements/admin.py` (read-only listing). The upload endpoint belongs on the registration review page where staff already interact with the agreement.

#### 1.3.7 eParaksts Validation API — session-based OAuth flow

**Decision:** The eParaksts adapter obtains a service-provider OAuth Introspect token using credentials (client ID + secret or equivalent), creates or reuses a temporary SignAPI session, uploads the file to that session, then calls `GET /api-validation/v1.0/{sessionId}/{documentId}/validate`. Configuration uses OAuth client/service-provider credentials plus token endpoint and base URL — not a simple API key. Exact variable names are deferred to implementation; the adapter design is parameterised to accept whatever the SignAPI requires.

**Why:** The eParaksts Validation API is session-based. It requires an OAuth Introspect token for the service provider, a temporary session for the file upload, and a GET call to the validation endpoint with session and document IDs. This is fundamentally different from a simple API-key-authenticated POST.

Provider links:
- https://developers.eparaksts.lv/v2.0/docs/before-you-start-1
- https://developers.eparaksts.lv/docs/test-environment
- https://developers.eparaksts.lv/v2.0/docs/validation-api

**Test credentials** are an implementation prerequisite. Production sign-off requires production credentials and appropriate security/data-processing terms.

### 1.4 Data Model

```python
# apps/agreements/models.py — additions to existing Agreement model

class Agreement(TimeStampedModel):
    # ... existing fields ...

    # P16: signed artifact (staff-upload)
    signed_artifact = models.FileField(
        upload_to="private/agreements/signed/%Y/%m/%d/",
        storage=private_document_storage,
        blank=True,
        default="",
    )
    signed_artifact_original_filename = models.CharField(max_length=255, blank=True, default="")
    signed_artifact_content_type = models.CharField(max_length=255, blank=True, default="")
    signed_artifact_file_size = models.PositiveIntegerField(default=0)
    signed_artifact_uploaded_at = models.DateTimeField(null=True, blank=True)
    signed_artifact_updated_at = models.DateTimeField(null=True, blank=True)
    signed_artifact_version = models.CharField(max_length=64, blank=True, default="")
    """Opaque version/token incremented on each upload. Used for
    race-safe validation result persistence: the background task
    only persists if the stored version still matches."""


# apps/agreements/models.py — new model

class AgreementSignedArtifactValidation(models.Model):
    """Minimised eParaksts validation result for a signed artifact.

    Separate from the Agreement model so validation results can exist
    independently of the file (validation runs after upload; stale
    results are discarded via the artifact version token).
    """

    agreement = models.OneToOneField(
        Agreement,
        on_delete=models.CASCADE,
        related_name="signed_artifact_validation",
    )
    signer_names = models.JSONField(default=list, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    signature_format = models.CharField(max_length=64, blank=True, default="")
    is_valid = models.BooleanField(null=True, blank=True)
    validation_error_code = models.CharField(max_length=64, blank=True, default="")
    artifact_version = models.CharField(max_length=64, blank=True, default="")
    """Snapshot of the artifact version at validation time. Used to
    detect stale results: if the Agreement's signed_artifact_version
    has changed since validation, this result is stale and discarded."""
    validated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Līguma paraksta verifikācijas rezultāts"
        verbose_name_plural = "Līguma paraksta verifikācijas rezultāti"

    def __str__(self) -> str:
        return f"Validation(agreement={self.agreement_id}, valid={self.is_valid})"
```

Storage backend: reuse the existing `PrivateDocumentStorage` from `apps.documents.storage` (private-root storage, not encryption). The upload path prefix is `private/agreements/signed/` to separate from registration documents.

### 1.5 Integration Boundary — eParaksts Adapter

```
apps/integrations/eparaksts.py  (NEW)
├── class EparakstsError(AgreementPlatformError)  (subclassed from existing taxonomy or new base)
├── class ConfigError, AuthError, TransientError  (same pattern as agreement_platform.py)
├── class ValidationResult(frozen dataclass)
│   → signer_names: list[str]
│   → signed_at: datetime | None
│   → signature_format: str
│   → is_valid: bool
│   → validation_error_code: str
├── validate_artifact(file_path: str, artifact_version: str) -> ValidationResult
│   → Obtain OAuth Introspect token using service-provider credentials
│   → Create/reuse temporary SignAPI session
│   → Upload file to session
│   → Call GET /api-validation/v1.0/{sessionId}/{documentId}/validate
│   → Parse response → ValidationResult
│   → Map HTTP/timeout errors to taxonomy
│   → stub mode: returns deterministic ValidationResult(is_valid=True, signer_names=["Zināms parakstītājs"], signed_at=now, signature_format="QES")
└── _request(method, url, headers, **kwargs)
    → existing pattern: _require_config() (token endpoint + base URL + credentials)
    → maps errors to taxonomy
```

**Config:** The adapter requires the following configuration categories (exact variable names are deferred to implementation):
- **Mode** — `stub` (default) or `eparaksts` for real.
- **OAuth client/service-provider credentials** — client ID and secret (or equivalent).
- **Token endpoint** — OAuth Introspect token URL.
- **SignAPI base URL** — the eParaksts Validation API base URL.

### 1.6 Services

```python
# apps/agreements/services.py — additions

def upload_signed_artifact(agreement: Agreement, file, *, actor) -> Agreement:
    """Upload (or replace) a signed artifact for an agreement.

    - Validate candidate file before replacement.
    - Save the new file first and persist the Agreement’s file metadata/version.
    - Only after new file save and database persistence succeed, permanently delete the old private storage object.
    - If new file save or database persistence fails, preserve the existing artifact and its metadata unchanged.
    - Original filename, content type, and file size are stored.
    - Validate case-insensitive `.pdf` / `.edoc` suffixes; check PDF MIME/content signature where reliable; `.edoc` is not a MIME type; enforce configured maximum size; reject mismatch or any other type.
    - A new artifact_version token is generated and stored.
    - Timestamps are set (uploaded_at for first upload, updated_at for replace).
    - Stale validation results are cleared (delete AgreementSignedArtifactValidation).
    - An AuditEvent is recorded (operation "uploaded" or "replaced").
    - A background job is enqueued to validate the artifact (best-effort).
    - Returns the updated Agreement.
    """

def process_signed_artifact_validation(agreement_id: int, artifact_version: str) -> None:
    """Background job: call eParaksts validation, persist minimised result.

    - Calls eparaksts.validate_artifact(file_path, artifact_version).
    - Compares the task's artifact_version against current Agreement.signed_artifact_version
      **before writing any result** (success or error).
    - If versions match: upsert AgreementSignedArtifactValidation (success) or
      persist validation_error_code (terminal error).
    - If versions differ: discard result entirely (stale task), return without writing.
    - Transient errors → raise RetryableAgreementError (django-q2 retries).
    - Terminal errors → persist validation_error_code only if version still matches.
    - Fail-safe: wrapped in try/except, logged, never raises into caller.
    """
```

### 1.7 Access Surfaces

**Registration admin (review panels):** The agreement module (rendered by `apps/registrations/admin_panels.py::build_review_context` and included in `apps/registrations/admin.py` change page) gains a "Parakstītais dokuments" section when `agreement.signed_artifact` is non-empty. It shows:
- A download link (Django proxy view, authorization-checked).
- Validation status badge (green = valid, red = invalid, grey = unavailable).
- Signer names (if available).
- Signing time (if available).
- Signature format (if available).
- A file upload button (POST endpoint on the review page).

**Family hub:** `apps/members/family_hub.py` / `templates/admin/members/guardian/family_hub.html` shows a "Līguma paraksts" card with validation status, signer names, signing time, signature format, and a download link (staff-authorization-checked proxy endpoint in `apps/members/admin.py` or `family_hub.py`).

**Agreement admin change page:** The Agreement admin remains read-only (`has_change_permission=False`). Its change-page template displays the signed-artifact validation status, signer names, signing time, signature format, and inline/download link. A custom `AgreementAdmin.get_urls()` proxy route serves the private artifact after `has_view_permission` and Agreement-PK checks. It does not provide an upload widget; the registration review page remains the sole upload surface.

**Guardian portal:** The guardian portal (`parent_portal.html`) shows a "Līguma paraksts" card with validation status, signer names, signing time, signature format, and a download link (guardian-ownership-checked proxy endpoint in `apps/registrations/views.py`).

### 1.8 Authorization

All signed-artifact access routes through Django proxy views that check:
- **Admin surfaces (registration admin, family hub, agreement admin):** Django staff/authenticated. Registration upload requires change permission. Family hub uses `apps/members/admin.py`/`family_hub.py` proxy endpoints. Agreement admin's custom artifact proxy requires `has_view_permission` and looks up the requested Agreement by PK.
- **Guardian portal:** Guardian ownership (the signed artifact belongs to a member whose guardian is the current user). Ownership check: `agreement.member.guardian.parent_account == request.session[PARENT_ACCOUNT_SESSION_KEY]`.

No public URLs. No raw storage URLs exposed.

### 1.9 Audit Events

New `AuditEvent.Action` value: `SIGNED_ARTIFACT_UPLOADED` (singular, consistent with existing naming convention). Operation is stored in metadata as `"uploaded"` or `"replaced"`. Metadata: `{"agreement_id": N, "operation": "uploaded"|"replaced"}`. No file bytes, no signer data, no validation results in audit metadata.

### 1.10 Migration Strategy

Agreement migrations currently end at `0006`. Use next consecutive migration numbers (e.g. `0007`, `0008`). One migration adds the `signed_artifact` FileField, metadata fields, and version token to `Agreement`. A second migration creates the `AgreementSignedArtifactValidation` model.

### 1.11 Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | Staff can upload a PDF or `.edoc` file to an Agreement from the registration admin review page. |
| AC2 | Uploading a file to an Agreement that already has a signed artifact permanently deletes the previous file and replaces it. |
| AC3 | The signed artifact is stored in private-root storage and accessible only through authorization-checked Django proxy views. |
| AC4 | The signed artifact is separate from the DocuSeal-generated PDF (the externally streamed artifact behind `apps.agreements.document_proxy`). |
| AC5 | Upload immediately publishes the artifact. Validation runs in the background. |
| AC6 | A valid validation result exposes signer names, signing time, signature format, and validation status on registration admin, family hub, agreement admin, and guardian portal surfaces. |
| AC7 | Validation failure or unavailability does not block publication. Guardian portal shows "Status nav pieejams". |
| AC8 | An `AuditEvent` is recorded on upload/replace with agreement target/target ID, operation ("uploaded" or "replaced"), and actor — no signer data, file bytes, or validation results in metadata. |
| AC9 | Only minimised validation fields are persisted (signer_names, signed_at, signature_format, is_valid, validation_error_code). Raw provider payload, certificate serials, and raw signing material are not retained. |
| AC10 | The eParaksts adapter supports `stub` and `eparaksts` modes behind the `apps/integrations` boundary, using session-based OAuth token flow. |
| AC11 | Guardian portal shows the signed artifact card with validation status and download link (ownership-gated). |
| AC12 (family hub) | Family hub staff-admin surface shows the signed artifact card with validation status and download link (staff-authorization-gated). |
| AC13 (agreement admin) | Agreement admin read-only change page shows signed-artifact status and inline/download proxy link through `has_view_permission`; upload remains via registration review page. |
| AC14 | Original filename, content type, and file size are stored with the FileField. Accepted types restricted to PDF and `.edoc` with server-side validation. |
| AC15 | Re-upload clears stale validation. Artifact version token ensures race-safe validation result persistence. |
| AC16 | Interactive in-portal eParaksts signing is NOT implemented (out of scope). |
| AC17 | The registration `Document`/OCR model is NOT used for signed artifacts (out of scope). |

### 1.12 Test Strategy

- **Service layer:** `upload_signed_artifact` deletes old file, saves new file, stores metadata (filename, content type, file size), generates version token, clears stale validation, sets timestamps, enqueues validation job, records audit event. Use a private-storage spy/fake to assert the old file is deleted **only after** the new file save succeeds. Use database assertions (query the Agreement row, check version token, metadata fields, and AuditEvent row) for metadata/version/audit — do not use `CaptureQueriesContext` to prove file storage deletion or a database INSERT.
- **Validation adapter:** `validate_artifact` in stub mode returns deterministic `ValidationResult`. In `eparaksts` mode, test with mocked `_request` that returns a controlled response. Test error classification (transient → retryable, terminal → persisted code). Test session-based OAuth token flow (mocked token endpoint).
- **Race safety:** Two concurrent validation tasks with different artifact versions — only the matching version persists; the stale one is discarded.
- **Family hub:** Staff can download signed artifact via proxy view. Non-staff → 404. Validation card renders with correct status badge.
- **Admin surface:** GET on review panel renders the signed-artifact section when file exists. POST with file uploads and publishes. Authorization enforced (non-staff → 403/404).
- **Agreement admin:** Read-only change page renders artifact status plus inline/download proxy link. Staff with view permission can stream it; non-staff receives denial/404. No upload widget is rendered.
- **Guardian portal:** Guardian can download signed artifact via proxy view. Non-owner → 404. Validation card renders with correct status badge.
- **Audit:** `SIGNED_ARTIFACT_UPLOADED` event recorded with correct metadata (agreement_id, operation). No PII in metadata.
- **File validation:** Case-insensitive `.pdf` and `.edoc` suffixes accepted. MIME type checked where reliable (`application/pdf` for `.pdf`). Configured maximum file size enforced. `.edoc` is not a MIME content type — no MIME value assigned. Mismatched or unsupported types rejected at service layer.

---

## 2. P17 — Configurable Member Export

### 2.1 Problem

P7 Slice B delivered a static CSV export with two fixed column sets (safe/sensitive) on the Member and RegistrationApplication admin changelists. Staff need **configurable** exports: reusable templates with custom column selections, optional agreement-status and training-group filters, and the ability to choose between CSV and XLSX at run time. This is needed for reporting, accounting, and external sharing where fixed column sets are insufficient.

### 2.2 Requirements

| # | Requirement |
|---|-------------|
| R1 | Any staff user can **create, edit, delete, and run** shared saved export templates, including templates with sensitive values. |
| R2 | **Risk/control:** staff-only access; every template mutation and run is audited; exported data values and file bytes are **never** recorded in audit logs. |
| R3 | A template has: a name, an ordered column allowlist, zero or more agreement-status filters, and zero or more training-group filters. Selected agreement states use **OR** within their set (any matching state qualifies). Selected training groups use **OR** within their set (any matching group qualifies). The agreement-status predicate and the training-group predicate are combined with **AND** when both are configured. A single current agreement is never described as "signed AND sent" — agreement states are an OR set. |
| R4 | Columns map stable keys to Latvian labels and safe readers. **No arbitrary ORM path, formulas, or free-text query builder.** Labels and readers are resolved solely from a server-side registry; only ordered stable column keys are persisted. |
| R5 | Export one row per `Member`. May choose: member, guardian, current agreement, and training group columns. |
| R6 | Filters are AND when both configured. Agreement status references **current agreement only**; historical agreements are ignored. Empty filters mean no restriction. |
| R7 | Staff choose **CSV or XLSX** at run time; XLSX defaults when available. CSV keeps UTF-8 BOM + semicolon conventions. Both protect against spreadsheet formula injection. |
| R8 | Downloads are direct responses and are **not retained** in storage. |
| R9 | **Explicitly out of scope:** guardian-row templates, scheduled email exports, arbitrary/custom formula columns, arbitrary queries. |
| R10 | P7 static CSV exports remain available and unchanged until an explicit retirement decision. New templates are additive. |

### 2.3 Design Decisions

#### 2.3.1 Saved templates vs. per-run column picker

**Decision:** Saved templates with a per-run format selector (CSV/XLSX). Templates are shared across staff.

**Why:** Staff frequently run the same reports (e.g. "active members with training groups and current agreement"). Saving templates avoids per-run configuration overhead. A per-run column picker would be more flexible but adds friction for recurring reports. Templates are the right balance.

#### 2.3.2 Column allowlist (stable keys only, resolved from server-side registry)

**Decision:** Only ordered stable column keys are persisted as a JSON array (e.g. `["member_full_name", "guardian_email", "training_group_name"]`). Labels and readers are resolved solely from a server-side registry at export time. No labels or dotted reader callable paths are stored in the database.

**Why:** Storing labels and reader paths in the database couples the template to implementation details that may change (label text, reader function location). A registry keeps labels and readers in one place, testable, and easy to update. The persisted keys are stable identifiers that don't change with refactoring.

#### 2.3.3 Zero-or-many filters (JSON array for agreement status, M2M for training group)

**Decision:** Agreement status filters are stored as a JSON array of state codes (e.g. `["signed", "sent"]`). Empty array = no filter. Training group filters are stored as an M2M relation to `TrainingGroup`. Empty relation = no filter. When both are configured, the agreement-status predicate AND the training-group predicate are combined. Within each set, states/groups use OR logic (any matching state qualifies; any matching group qualifies). A single current agreement is never described as "signed AND sent" — agreement states form an OR set.

**Why:** Staff may need to filter by multiple agreement states (e.g. "signed OR sent") or multiple training groups. A single foreign key or CharField would only allow one value. JSON array for agreement states is simple and queryable; M2M for training groups leverages existing Django ORM capabilities.

#### 2.3.4 XLSX defaults, CSV fallback

**Decision:** XLSX is the default format when the `openpyxl` library is installed. CSV is the fallback. Both formats share the same formula-injection guard and column logic.

**Why:** XLSX provides better formatting (column widths, headers) and is the preferred format for most reporting tools. CSV is the fallback for environments where `openpyxl` is not available (lighter dependency). The formula-injection guard is format-agnostic.

#### 2.3.5 Current-agreement-only filters

**Decision:** Agreement status filters reference the **current** agreement only (`is_current=True`). Historical agreements (superseded, discontinued, void) are ignored by the filter.

**Why:** For roster and reporting purposes, staff care about the current state. Historical agreements are relevant for billing and lifecycle auditing (covered by other reports), not for member rosters.

#### 2.3.6 Audit scope

**Decision:** Audit every template mutation (create/edit/delete) and every export run. Record: actor, timestamp, template ID, selected column keys, state/group filter identifiers, row count, format (CSV/XLSX), and derived `sensitive` flag. **Never** record exported data values, file bytes, or column values.

**Why:** Staff need to know who ran what export and when (accountability). But the exported data itself is sensitive and should not be logged.

### 2.4 Data Model

```python
# apps/members/models.py — new model

class MemberExportTemplate(models.Model):
    """A saved export template for member data.

    Only ordered stable column keys are persisted (JSON array).
    Labels and readers are resolved from the server-side registry
    at export time.
    """

    name = models.CharField(max_length=128)
    column_keys = models.JSONField(default=list)
    """Ordered list of stable column keys. Labels and readers are
    resolved from the server-side COLUMN_REGISTRY at export time."""
    agreement_status_filters = models.JSONField(default=list)
    """JSON array of agreement state codes (e.g. ['signed', 'sent']).
    Empty array = no filter."""
    training_groups = models.ManyToManyField(
        "members.TrainingGroup",
        blank=True,
        related_name="export_templates",
    )
    """M2M to TrainingGroup. Empty relation = no filter."""
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="member_export_templates_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dalītais eksporta veidne"
        verbose_name_plural = "Dalītās eksporta veidnes"

    def __str__(self) -> str:
        return self.name
```

### 2.5 Column Registry

```python
# apps/members/exports.py — additions

COLUMN_REGISTRY = {
    # Member columns
    "member_full_name": {
        "label": "Biedra vārds, uzvārds",
        "reader": "apps.members.exports._member_full_name",
    },
    "member_personal_id": {
        "label": "Biedra personas kods",
        "reader": "apps.members.exports._member_personal_id",
    },
    "member_birth_date": {
        "label": "Dzimšanas datums",
        "reader": "apps.members.exports._member_birth_date",
    },
    # Guardian columns
    "guardian_name": {
        "label": "Vecāka vārds, uzvārds",
        "reader": "apps.members.exports._guardian_name",
    },
    "guardian_email": {
        "label": "Vecāka e-pasts",
        "reader": "apps.members.exports._guardian_email",
    },
    "guardian_phone": {
        "label": "Vecāka tālrunis",
        "reader": "apps.members.exports._guardian_phone",
    },
    "guardian_address": {
        "label": "Vecāka adrese",
        "reader": "apps.members.exports._guardian_address",
    },
    # Agreement columns (current only)
    "agreement_state": {
        "label": "Līguma statuss",
        "reader": "apps.members.exports._agreement_state",
    },
    "agreement_signed_at": {
        "label": "Līguma parakstīšanas datums",
        "reader": "apps.members.exports._agreement_signed_at",
    },
    # Training group columns
    "training_group_name": {
        "label": "Treniņu grupa",
        "reader": "apps.members.exports._training_group_name",
    },
}
```

Labels and readers are resolved from `COLUMN_REGISTRY` at export time. Only stable column keys are persisted in the template. Each reader is a pure function: `def _member_full_name(member: Member) -> str: return member.full_name`. No ORM queries inside readers.

### 2.6 Export Engine

```python
# apps/members/exports.py — additions

def resolve_column_reader(key: str) -> Callable[[Member], Any]:
    """Resolve a column key to its reader callable from the registry.

    Raises LookupError if the key is not in the registry.
    """

def resolve_column_label(key: str) -> str:
    """Resolve a column key to its Latvian label from the registry."""

def export_members(
    queryset: QuerySet[Member],
    column_keys: list[str],
    *,
    fmt: Literal["csv", "xlsx"] = "csv",
) -> HttpResponse:
    """Export members to CSV or XLSX.

    - column_keys: ordered list of stable keys from a template.
    - fmt: "csv" or "xlsx".
    - Returns an HttpResponse with the file content.
    - CSV: UTF-8 BOM, semicolon delimiter, formula-injection guard.
    - XLSX: openpyxl workbook, formula-injection guard, column widths.
    - Downloads are direct responses; not retained in storage.
    """
```

### 2.7 Admin Surface

**`MemberExportTemplateAdmin`:** CRUD for templates. List view shows name, column count, created_by, created_at. Change view shows editable name, a column picker (dropdown of registry keys, ordered), agreement status filter (multi-select dropdown of `Agreement.State` choices, empty = no filter), training group filter (multi-select dropdown of active `TrainingGroup`, empty = no filter).

**Run button:** On the template change page, a "Eksportēt" button that triggers the export with the selected format (CSV/XLSX radio buttons). On the changelist, a "Eksportēt" action that runs the selected template(s).

**Format selection:** A modal or inline radio buttons (CSV/XLSX) on the run button click. XLSX defaults when `openpyxl` is installed.

### 2.8 Authorization

Staff-only (Django staff/authenticated). No public URLs. Sensitive columns (personal_id, guardian email/phone/address) are available in templates but the template itself is audited with a `sensitive` flag derived from whether any selected column key maps to a sensitive reader.

### 2.9 Audit Events

New `AuditEvent.Action` values: `MEMBER_EXPORT_RUN`, `MEMBER_EXPORT_TEMPLATE_MUTATED`.

`MEMBER_EXPORT_RUN` metadata: `{"template_id": N, "column_keys": [...], "agreement_status_filters": [...], "training_group_ids": [...], "row_count": N, "format": "csv"|"xlsx", "sensitive": bool}`.

`MEMBER_EXPORT_TEMPLATE_MUTATED` metadata: `{"template_id": N, "operation": "created"|"updated"|"deleted"}`.

Never include exported data values or file bytes.

### 2.10 Migration Strategy

Member migrations currently end at `0011`. Use next consecutive migration number (e.g. `0012`). One migration creates the `MemberExportTemplate` model.

### 2.11 Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | Any staff user can create, edit, delete, and run shared saved export templates. |
| AC2 | Templates include a name, ordered column allowlist, zero or more agreement-status filters, and zero or more training-group filters. |
| AC3 | Only stable column keys are persisted; labels and readers are resolved from the server-side registry at export time. No arbitrary ORM paths, formulas, or free-text query builder. |
| AC4 | Export produces one row per Member with the selected columns. |
| AC5 | Selected agreement states use OR within their set; selected training groups use OR within their set. The agreement-status predicate AND the training-group predicate when both exist. Agreement status filters reference current agreement only. Empty filters = no restriction. A single current agreement is never described as "signed AND sent". |
| AC6 | Staff choose CSV or XLSX at run time; XLSX defaults when available. |
| AC7 | CSV keeps UTF-8 BOM + semicolon conventions. Both formats protect against spreadsheet formula injection. |
| AC8 | Downloads are direct responses and are not retained in storage. |
| AC9 | Every template mutation and export run is audited with template ID, column keys, filter identifiers, row count, format, and sensitive flag — never exported data values or file bytes. |
| AC10 | Sensitive columns are available in templates but audited with a `sensitive` flag. |
| AC11 | Guardian-row templates, scheduled email exports, arbitrary formula columns, and arbitrary queries are NOT implemented (out of scope). |
| AC12 | P7 static CSV exports remain available and unchanged. New templates are additive. |

### 2.12 Test Strategy

- **Column registry:** All registry keys resolve to valid callables and labels. Each reader returns the expected value for a known `Member` instance.
- **Export engine:** CSV output starts with BOM, uses `;` delimiter, applies formula-injection guard. XLSX output creates a valid workbook with headers and data rows. Labels resolved from registry, not from persisted data.
- **Filter logic:** Selected agreement states use OR within their set; selected training groups use OR within their set. The agreement-status predicate AND the training-group predicate when both configured. Agreement status filters only current agreements. Empty filters = no restriction. JSON array for agreement states; M2M for training groups. No single agreement described as "signed AND sent".
- **Admin CRUD:** Create/edit/delete templates via admin. Run button triggers export. Format selection (CSV/XLSX) works.
- **Audit:** `MEMBER_EXPORT_RUN` and `MEMBER_EXPORT_TEMPLATE_MUTATED` events recorded with correct metadata (template ID, column keys, filter identifiers, row count, format, sensitive flag). No exported data in metadata.
- **Authorization:** Non-staff → 403/404. Sensitive columns available but audited with `sensitive=True`.

---

## 3. P18 — Unfinished-Application Lifecycle

### 3.1 Problem

Draft and fix_requested registration applications that are never completed or corrected sit in the system indefinitely. Staff have no visibility into how long an unfinished application has been inactive, and parents have no reminder to return and complete their registration. There is no automated archival of stale applications, and no way to resume an archived draft.

### 3.2 Requirements

| # | Requirement |
|---|-------------|
| R1 | Automatic workflow affects **draft** and **fix_requested** only. |
| R2 | Send generic no-PII reminder emails at **7** and **21** inactive days, measured from a persisted follow-up anchor. |
| R3 | Automatically **archive** at **60** inactive days. |
| R4 | Scheduler runs **daily** at **09:00 Europe/Riga** and is admin-editable (django-q2 Schedule). |
| R5 | Parent save resets follow-up anchor and reminder markers. A staff `request_fix` resets anchor at request time. |
| R6 | Reminder recipient: verified parent-account email when present, else `claimed_email`. If **both** `parent_account.email` and `claimed_email` are blank, **do not send** the reminder and **do not stamp** the reminder timestamp; leave the application eligible for later retry when an email becomes available. This does not affect archive timing. Reminder contains **no** child/form/document/status detail. Links to `/register/`; standard one-time email-code verification remains required before portal access. |
| R7 | Add `archived` state and retain: anchor, reminder timestamps, archive time, prior state, and archive actor (null for automated archive). |
| R8 | Service layer owns state guards. |
| R9 | Archived draft/fix_requested applications show portal **Resume** button. Resume restores prior editable state and resets timer. |
| R10 | Staff may manually archive draft, submitted, fix_requested, and rejected; **approved cannot be archived**. Manually archived submitted/rejected show read-only and no Resume. |
| R11 | Audit reminder, archive, and resume **without** recording message body, recipient, child name, or form data. |
| R12 | **Out of scope:** deletion/purge, staff reminders, SMS/WhatsApp, automatic reminders for submitted/rejected, new auth links, automatic reopening. |

### 3.3 Design Decisions

#### 3.3.1 Follow-up anchor vs. last-activity timestamp

**Decision:** A dedicated `RegistrationApplication.follow_up_anchor` DateTimeField (nullable). Set on creation (for new drafts), reset on parent save, reset on staff `request_fix`. Reminder timestamps (`last_reminder_7_at`, `last_reminder_21_at`) track which reminders have been sent.

**Why:** `last_activity` is ambiguous (a parent saving a draft is activity, but so is a staff viewing the application in admin). A dedicated anchor that only moves on meaningful actions (save, request_fix) gives a clean "days since last meaningful action" metric.

#### 3.3.2 Generic reminder email (no PII)

**Decision:** The reminder email contains only: "Jums ir neaizpildīts pieteikums. Turpināt reģistrāciju →" with a link to `/register/`. No child name, no form details, no status. The parent must complete one-time-code verification at `/register/` before accessing the portal.

**Why:** The reminder is a nudge, not a notification of specifics. Including PII in an email that may be forwarded, read by others, or retained in an inbox increases exposure risk. The OTP gate at `/register/` ensures only the verified parent can access the portal and their applications.

#### 3.3.3 Archived state vs. soft-delete

**Decision:** A new `Status.ARCHIVED = "archived"` value on `RegistrationApplication.Status`. Not a soft-delete (the row remains, is queryable, and can be resumed). A separate `archived_at` timestamp, `archived_by` FK (null for automated archive), and `previous_status` snapshot.

**Why:** Soft-delete implies the record is gone. Archived implies it is dormant but restorable. The resume operation restores the application to its prior state (draft or fix_requested), so the row must remain intact.

#### 3.3.4 Resume semantics

**Decision:** Resume sets `status` back to `previous_status`, clears `archived_at` and `archived_by`, and resets `follow_up_anchor` to now. The application becomes editable again. The timer restarts from zero.

**Why:** Resume is the inverse of archive for drafts/fix_requested. It should feel like "opening a saved draft" — the application returns to its prior state with a fresh inactivity clock.

#### 3.3.5 Manual archive by staff

**Decision:** Staff can archive draft, submitted, fix_requested, and rejected applications. Approved applications cannot be archived (a member already exists; the member's lifecycle handles discontinuation). Manually archived submitted/rejected applications show read-only in the portal (no Resume button).

**Why:** Staff may need to archive old or irrelevant applications. Approved applications are handled by the member lifecycle (discontinuation), not by application archival.

### 3.4 Data Model

```python
# apps/registrations/models.py — additions to RegistrationApplication.Status

class Status(models.TextChoices):
    DRAFT = "draft", "Melnraksts"
    SUBMITTED = "submitted", "Iesniegts"
    FIX_REQUESTED = "fix_requested", "Jālabo"
    APPROVED = "approved", "Apstiprināts"
    REJECTED = "rejected", "Noraidīts"
    ARCHIVED = "archived", "Arhivēts"  # NEW


# apps/registrations/models.py — new fields on RegistrationApplication

follow_up_anchor = models.DateTimeField(null=True, blank=True)
last_reminder_7_at = models.DateTimeField(null=True, blank=True)
last_reminder_21_at = models.DateTimeField(null=True, blank=True)
archived_at = models.DateTimeField(null=True, blank=True)
archived_by = models.ForeignKey(
    settings.AUTH_USER_MODEL,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="archived_applications",
)
previous_status = models.CharField(max_length=32, blank=True, default="")
```

### 3.5 Services

```python
# apps/registrations/services.py — additions

def reset_follow_up_anchor(application: RegistrationApplication) -> None:
    """Reset the follow-up anchor to now.

    Called on parent save and staff request_fix.
    """

def send_follow_up_reminder(application: RegistrationApplication, threshold: Literal[7, 21]) -> None:
    """Send a generic no-PII reminder email.

    Recipient: parent_account.email (when present), else claimed_email.
    Content: generic nudge + /register/ link.
    Sets last_reminder_7_at or last_reminder_21_at depending on threshold.
    Records AUDIT_EVENT for reminder delivery.
    """

def archive_application(application: RegistrationApplication, *, actor: User | None = None) -> None:
    """Archive an application.

    - Sets status to ARCHIVED.
    - Records previous_status, archived_at, archived_by.
    - AuditEvent: APPLICATION_ARCHIVED.
    - Guards: approved applications cannot be archived.
    """

def resume_application(application: RegistrationApplication) -> None:
    """Resume an archived draft/fix_requested application.

    - Sets status back to previous_status.
    - Clears archived_at, archived_by.
    - Resets follow_up_anchor to now.
    - AuditEvent: APPLICATION_RESUMED.
    - Guards: only archived draft/fix_requested can be resumed.
    """
```

### 3.6 Background Job

```python
# apps/registrations/tasks.py — new job

def process_unfinished_applications() -> dict:
    """Daily sweep: reminders + auto-archive.

    Runs daily at 09:00 Europe/Riga (configured in django-q2 Schedule).

    - Selects draft/fix_requested applications where
      follow_up_anchor is not null and inactivity >= 7 days
      (and last_reminder_7_at is before the threshold) → send reminder.
    - Same for 21 days → send second reminder.
    - If inactivity >= 60 days: auto-archive (archived_by=null), **do not**
      send a 7-day or 21-day reminder in the same sweep.
    - If both parent-account email and claimed_email are blank: skip
      reminder send and timestamp; leave eligible for later retry.
      This does not affect archive timing.
    - Returns counts: {reminders_sent, archived}.
    - Audit: reminders, archive are audited (without PII).
    """
```

Schedule: django-q2 `Schedule` named `registrations-unfinished-lifecycle`, DAILY, 09:00 Europe/Riga (editable in admin).

### 3.7 Parent Portal

**Archived draft/fix_requested applications:** Show a "Turpināt" (Resume) button that calls `resume_application`. After resume, the application returns to its prior state and the portal shows it as active again.

**Archived submitted/rejected applications:** Show as read-only with no Resume button.

**Active draft/fix_requested applications:** Normal display (no archive indicator).

### 3.8 Admin Surface

**Changelist:** Add `archived_at` and `previous_status` columns. Add `Status` list-filter including `ARCHIVED`. Add an "Arhivēt" action for selected applications (guards: approved applications are excluded from the action).

**Change page:** Show archive status, archive time, archive actor, and a "Atcelt arhivizāciju" (Unarchive) button for draft/fix_requested (not for submitted/rejected).

### 3.9 Audit Events

New `AuditEvent.Action` values (singular, consistent with existing naming convention):
- `APPLICATION_REMINDER_SENT` — for each reminder delivery (7-day or 21-day). Metadata: `{"application_id": N, "threshold": 7|21}`.
- `APPLICATION_ARCHIVED` — for manual and automated archive. Metadata: `{"application_id": N, "previous_status": str}`.
- `APPLICATION_RESUMED` — for resume. Metadata: `{"application_id": N, "restored_status": str}`.

No message body, recipient, child name, or form data in audit metadata.

### 3.10 Migration Strategy

Registration migrations currently end at `0012`. Two migrations:

1. **Schema migration** (e.g. `0013`): Adds `follow_up_anchor`, `last_reminder_7_at`, `last_reminder_21_at`, `archived_at`, `archived_by`, `previous_status`, and the `ARCHIVED` status choice to `RegistrationApplication`.
2. **Idempotent data migration** (e.g. `0014`): Seeds the django-q2 `Schedule` row named `registrations-unfinished-lifecycle` (DAILY, 09:00 Europe/Riga). The migration is idempotent — it uses `get_or_create` so re-running on a fresh DB or after a failed deployment is safe. A dedicated test (`tests/registrations/test_schedule_seed.py`) asserts the schedule row exists with correct name, schedule type, and next_run time after migration.

### 3.11 Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | Draft and fix_requested applications receive reminder emails at 7 and 21 inactive days. |
| AC2 | Reminder emails contain no PII (no child name, form details, or status). They link to `/register/`. |
| AC3 | Applications are automatically archived after 60 inactive days. At or above 60 days, the application is archived and no 7-day or 21-day reminder is sent in the same sweep. |
| AC4 | The scheduler runs daily at 09:00 Europe/Riga and is admin-editable. |
| AC5 | Parent save resets the follow-up anchor and reminder markers. |
| AC6 | Staff `request_fix` resets the follow-up anchor. |
| AC7 | Reminder recipient is `parent_account.email` when present, else `claimed_email`. If both are blank, do not send and do not stamp the reminder timestamp; leave eligible for later retry. This does not affect archive timing. |
| AC8 | Archived draft/fix_requested applications show a Resume button in the portal. Resume restores prior state and resets the timer. |
| AC9 | Staff can manually archive draft, submitted, fix_requested, and rejected. Approved cannot be archived. |
| AC10 | Manually archived submitted/rejected show read-only in the portal with no Resume. |
| AC11 | Audit records reminders (`APPLICATION_REMINDER_SENT`), archive (`APPLICATION_ARCHIVED`), and resume (`APPLICATION_RESUMED`) — without message body, recipient, child name, or form data. |
| AC12 | Deletion/purge, staff reminders, SMS/WhatsApp, automatic reminders for submitted/rejected, new auth links, and automatic reopening are NOT implemented (out of scope). |

### 3.12 Test Strategy

- **Service layer:** `reset_follow_up_anchor` sets anchor to now. `send_follow_up_reminder` sends email to correct recipient, sets threshold timestamp, records audit event. `archive_application` sets status to ARCHIVED, records previous_status, archived_at, archived_by. Guards: approved → ValueError. `resume_application` restores previous_status, clears archived fields, resets anchor. Guards: only archived draft/fix_requested.
- **Background job:** `process_unfinished_applications` selects correct applications by inactivity threshold, sends reminders (once per threshold), auto-archives at 60 days. Idempotent: already-reminded applications at the 7-day threshold are not re-reminded. At/in excess of 60 days: archive once, do not send 7/21-day reminder in the same sweep. If both parent-account email and claimed_email are blank: skip reminder send and timestamp, leave eligible for later retry; archive timing unaffected.
- **Admin:** Changelist shows archived applications. "Arhivēt" action excludes approved. "Atcelt arhivizāciju" works for draft/fix_requested only.
- **Portal:** Archived draft/fix_requested shows Resume button. Archived submitted/rejected shows read-only. Resume restores the application.
- **Audit:** `APPLICATION_REMINDER_SENT`, `APPLICATION_ARCHIVED`, `APPLICATION_RESUMED` events recorded with correct metadata. No PII.
- **Schedule seed:** After migration, `registrations-unfinished-lifecycle` schedule row exists with DAILY type, 09:00 Europe/Riga next_run. Idempotent re-run test.

---

## 4. File/Document Plan for Future Work

### 4.1 P16 — Signed-Agreement Upload + Verification

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/agreements/models.py` | Modify | Add `signed_artifact` FileField, metadata fields, version token to `Agreement`. Add `AgreementSignedArtifactValidation` model. |
| `apps/agreements/services.py` | Modify | Add `upload_signed_artifact`, `process_signed_artifact_validation`. |
| `apps/agreements/admin.py` | Modify | Add read-only change-page artifact context plus a `has_view_permission`-gated signed-artifact proxy route. |
| `templates/admin/agreements/agreement/change_form.html` | Modify | Render signed-artifact validation status and inline/download proxy link; no upload widget. |
| `apps/registrations/admin.py` | Modify | Add POST upload endpoint/button on the review page. Add signed-artifact section to review context. |
| `apps/registrations/admin_panels.py` | Modify | Add signed-artifact section to `build_review_context`. |
| `apps/integrations/eparaksts.py` | Create | eParaksts adapter (stub/eparaksts), `ValidationResult` dataclass, `validate_artifact`, exception taxonomy, session-based OAuth token flow. |
| `apps/integrations/tasks.py` | Modify | Add `process_signed_artifact_validation` django-q2 job + enqueue helper. |
| `apps/members/family_hub.py` | Modify | Add family-hub signed-artifact card + proxy endpoint (staff-authorization-checked, private storage). |
| `apps/members/admin.py` | Modify | Wire family-hub signed-artifact proxy endpoint; update GuardianAdmin rendering. |
| `templates/admin/members/guardian/family_hub.html` | Modify | Render signed-artifact card on family-hub guardian detail. |
| `apps/registrations/views.py` | Modify | Add guardian-portal signed-artifact proxy endpoint (ownership-checked, private storage). |
| `templates/registrations/parent_portal.html` | Modify | Render signed-artifact card on application card. |
| `apps/core/models.py` (AuditEvent.Action) | Modify | Add `SIGNED_ARTIFACT_UPLOADED`. |
| `apps/agreements/migrations/` | Create | Next consecutive migrations for Agreement field additions and Validation model. |
| `tests/agreements/test_signed_artifact_upload.py` | Create | Service tests: upload, replace, audit, validation enqueue, version token, race safety. |
| `tests/agreements/test_signed_artifact_validation.py` | Create | Validation adapter tests: stub, error classification, persist minimised result, race safety. |
| `tests/agreements/test_signed_artifact_admin.py` | Create | Agreement admin read-only display and `has_view_permission`-gated proxy tests. |
| `tests/registrations/test_admin_signed_artifact.py` | Create | Admin review panel rendering and upload tests. |
| `tests/members/test_family_hub_signed_artifact.py` | Create | Family hub signed-artifact card rendering and proxy endpoint authorization tests (staff-only). |
| `tests/registrations/test_portal_signed_artifact.py` | Create | Guardian portal rendering and proxy endpoint authorization tests. |

### 4.2 P17 — Configurable Member Export

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/members/models.py` | Modify | Add `MemberExportTemplate` model. |
| `apps/members/exports.py` | Modify | Add `COLUMN_REGISTRY`, `resolve_column_reader`, `resolve_column_label`, `export_members` (CSV/XLSX), formula-injection guard. |
| `apps/members/admin.py` | Modify | Add `MemberExportTemplateAdmin` (CRUD), "Eksportēt" action on changelist. |
| `apps/core/models.py` (AuditEvent.Action) | Modify | Add `MEMBER_EXPORT_RUN`, `MEMBER_EXPORT_TEMPLATE_MUTATED`. |
| `apps/members/migrations/` | Create | Next consecutive migration for MemberExportTemplate model. |
| `tests/members/test_export_template.py` | Create | CRUD tests for templates. |
| `tests/members/test_export_engine.py` | Create | CSV/XLSX output tests: BOM, delimiter, formula-injection, column resolution from registry. |
| `tests/members/test_export_filters.py` | Create | Filter logic tests: AND, current-agreement-only, empty filters, JSON array for states, M2M for groups. |
| `tests/members/test_export_audit.py` | Create | Audit event tests: mutation + run, template ID, column keys, filter identifiers, no PII in metadata. |

### 4.3 P18 — Unfinished-Application Lifecycle

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/registrations/models.py` | Modify | Add `ARCHIVED` status. Add `follow_up_anchor`, `last_reminder_7_at`, `last_reminder_21_at`, `archived_at`, `archived_by`, `previous_status`. |
| `apps/registrations/services.py` | Modify | Add `reset_follow_up_anchor`, `send_follow_up_reminder`, `archive_application`, `resume_application`. |
| `apps/registrations/tasks.py` | Modify | Add `process_unfinished_applications` django-q2 job + enqueue helper. |
| `apps/registrations/admin.py` | Modify | Add `archived_at`/`previous_status` columns, `Status` filter, "Arhivēt" action, "Atcelt arhivizāciju" button. |
| `apps/registrations/views.py` | Modify | Add resume endpoint. Update portal rendering for archived state. |
| `apps/core/models.py` (AuditEvent.Action) | Modify | Add `APPLICATION_REMINDER_SENT`, `APPLICATION_ARCHIVED`, `APPLICATION_RESUMED`. |
| `apps/registrations/migrations/` | Create | Next consecutive schema migration for fields + ARCHIVED status. |
| `apps/registrations/migrations/` | Create | Next consecutive idempotent data migration that seeds `registrations-unfinished-lifecycle` DAILY at 09:00 Europe/Riga. |
| `tests/registrations/test_schedule_seed.py` | Create | Test schedule seed fields and idempotent re-run. |
| `tests/registrations/test_unfinished_lifecycle.py` | Create | Service tests: reset anchor, reminder, archive, resume, guards. |
| `tests/registrations/test_follow_up_job.py` | Create | Background job tests: reminder thresholds, auto-archive, idempotency. |
| `tests/registrations/test_archive_admin.py` | Create | Admin action tests: archive, unarchive, guards (approved excluded). |
| `tests/registrations/test_portal_archived.py` | Create | Portal rendering tests: archived draft/fix_requested (Resume), archived submitted/rejected (read-only). |
| `tests/registrations/test_follow_up_audit.py` | Create | Audit event tests: reminder, archive, resume — no PII in metadata. |

### 4.4 Shared Dependencies

- All three P16–P18 features extend `AuditEvent.Action` — coordinate the additions to avoid conflicts.
Each independently released milestone adds its required AuditEvent.Action choices in the next consecutive `apps/core/migrations/` migration. A combined migration is acceptable only when P16–P18 are deliberately released together as one deployment unit.
- `apps/core/migrations/` is a shared dependency across all three milestones — coordinate migration numbering and release order.
- All three use the existing private-root storage (`apps.documents.storage.PrivateDocumentStorage`).
- All three use the existing django-q2 background job infrastructure.
- All three follow the existing adapter pattern (stub/prod dispatch) for external integrations.

### 4.5 Scope Note

**This design specification does not change production behavior.** It describes future work that has not been implemented. No migrations, no source code changes, no test changes are included in this document. Implementation requires a separate plan document and execution.

---

## 5. Self-Review

### 5.1 Placeholder scan

No "TBD", "TODO", "implement later", or "similar to" patterns found. All requirements have corresponding design decisions, data models, services, and acceptance criteria.

### 5.2 Contradiction scan

- **P16:** Signed artifact is separate from DocuSeal PDF (externally streamed via `document_proxy`) — consistent with R3. Validation is best-effort background with version-token race safety — consistent with R6, R12. Registration admin, family hub, and agreement admin are staff surfaces; guardian portal is parent-owned; all four are distinct access paths. Agreement admin remains read-only and exposes only a `has_view_permission`-gated proxy — consistent with §1.3.6. eParaksts uses session-based OAuth flow — consistent with §1.3.7.
- **P17:** Only stable column keys persisted; labels/readers from registry — consistent with R4. JSON array for agreement states, M2M for training groups — consistent with R3. P7 exports remain unchanged — consistent with R10.
- **P18:** Archived status distinct from soft-delete — consistent with R8. Resume only for archived draft/fix_requested — consistent with R9. Approved cannot be archived — consistent with R10. Scheduler is daily at 09:00 Europe/Riga — consistent with R4. Reminder content is no-PII — consistent with R6.

### 5.3 Scope creep scan

- **P16:** No interactive eParaksts signing (out of scope, explicitly stated in R13). No registration Document model reuse (out of scope, explicitly stated in R13).
- **P17:** No guardian-row templates (out of scope, explicitly stated in R9). No scheduled email exports (out of scope, explicitly stated in R9).
- **P18:** No deletion/purge (out of scope, explicitly stated in R12). No staff reminders (out of scope, explicitly stated in R12). No SMS/WhatsApp (out of scope, explicitly stated in R12). No automatic reminders for submitted/rejected (out of scope, explicitly stated in R12).

### 5.4 Consistency scan

- AuditEvent.Action naming is consistently singular across all three features (`SIGNED_ARTIFACT_UPLOADED`, `MEMBER_EXPORT_RUN`, `APPLICATION_REMINDER_SENT`, `APPLICATION_ARCHIVED`, `APPLICATION_RESUMED`).
- Migration references use "next consecutive" language, not fixed numbers. Each independently released milestone has its own `apps/core/migrations/` audit choice migration.
- No `apps/agreements/admin_panels.py` referenced (does not exist).
- Registration admin, family hub, agreement admin (staff-admin), and guardian portal (parent) are correctly distinguished as separate access surfaces.
- eParaksts configuration lists only categories (mode, OAuth client/service-provider credentials, token endpoint, SignAPI base URL); no concrete `EPARAKSTS_*` variable names.
- All official eParaksts links are present.
- P7 static CSV exports are explicitly preserved (additive, not replacing).
- P17 filter semantics: OR within agreement-state set, OR within training-group set, AND between sets. No "signed AND sent" for a single agreement.
- P16 file validation: case-insensitive `.pdf`/`.edoc` suffixes, MIME check where reliable, configured size limit, `.edoc` not assigned a MIME value.
- P16 replacement test uses private-storage spy/fake for file deletion, database assertions for metadata/version/audit.
- P16 version comparison applied to both success and error persistence paths.
- P18 blank-email: both parent-account email and claimed_email blank → skip send and stamp, leave eligible for retry, archive timing unaffected.
- P18 60-day: archive once, no 7/21-day reminder in same sweep.
- P18 migration: schema migration + idempotent data migration for schedule seed with test.
- Implementation readiness confirmed: safe replacement ordering, correct PDF/.edoc rule, P18 two migrations + schedule test, no hardcoded core migration examples.

### 5.5 External prerequisites

The eParaksts Validation API payload and error-code mapping are implementation research items. Test credentials are required before implementation; production sign-off requires production credentials and appropriate security/data-processing terms. The adapter design is parameterised to accept whatever the SignAPI returns, mapping to the minimised `ValidationResult` fields. This is an external prerequisite, not a design ambiguity.

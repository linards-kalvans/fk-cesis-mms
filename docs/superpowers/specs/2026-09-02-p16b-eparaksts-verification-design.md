# P16-B — eParaksts Signed-Agreement Verification — Design Specification

**Date:** 2026-09-02
**Status:** Planned (Blocked — eParaksts SignAPI test credentials required)
**Slice:** P16-B (of P16, split from original "Signed-agreement upload + verification")
**Parent milestone:** M3 — Approval-to-membership and agreement completion
**Prerequisite:** P16-A (Signed-Agreement Artifact Upload and Serve) must be deployed first.
**Supersedes:** `docs/superpowers/specs/2026-08-25-roadmap-p16-p18-design.md` §1 (P16 scope replaced by P16-A + P16-B)

---

## 0. Table of Contents

1. [Problem](#1-problem)
2. [Scope](#2-scope)
3. [Design Decisions with Rationale](#3-design-decisions-with-rationale)
4. [Components and Data Flow](#4-components-and-data-flow)
5. [Authorization, Security, and Privacy](#5-authorizationsecurity-and-privacy)
6. [Error and Retry Behavior](#6-error-and-retry-behavior)
7. [Migration and Rollout Strategy](#7-migration-and-rollout-strategy)
8. [Acceptance Criteria](#8-acceptance-criteria)
9. [Test Strategy](#9-test-strategy)
10. [Relationship to P16-A](#10-relationship-to-p16-a)

---

## 1. Problem

P16-A delivers artifact upload and serve but does **not** verify that a signed PDF or `.edoc` file actually contains a valid electronic signature. Staff and guardians need to see whether the signature is valid.

eParaksts SignAPI provides server-side signature validation: it returns signer names, signing time, signature format, and a pass/fail indication. This slice adds that verification capability on top of P16-A artifacts.

---

## 2. Scope

### 2.1 In scope

| # | Capability |
|---|-----------|
| S1 | Adds `Agreement.signed_artifact_version` (UUID on every upload/replacement) and a OneToOne `AgreementSignedArtifactValidation` model keyed to `Agreement`, with a snapshot `artifact_version`. It extends the P16-A `Agreement` upload service and enqueues `(agreement_id, artifact_version)` after database commit. Existing P16-A `Agreement` artifacts get versions via P16-B data migration. Bulk staff action runs on selected `Agreement`s with `signed_artifact`; it queues `(agreement_id, current version)`. No artifact-model `version_token` or artifact id references. |
| S2 | A result is valid only if at least one signature exists and every signature has indication `TOTAL-PASSED`. Failed, indeterminate, or no signatures = completed invalid validation (not provider unavailability). |
| S3 | A django-q job is enqueued with `(agreement_id, artifact_version)` after transaction commit. It opens the private artifact server-side and invokes a stub/`eparaksts` integration boundary. Real eParaksts flow: service-provider OAuth Introspect access token → temporary SignAPI session → upload artifact → `GET /api-validation/v1.0/{sessionId}/{documentId}/validate`. Provider URLs never exposed to the browser. |
| S4 | Re-check artifact version before persistence. A stale result is discarded completely. New/replaced P16-B uploads automatically queue verification. |
| S5 | Transient network/timeout/rate-limit/server errors retry. Auth/config/unsupported provider response persists `unavailable` error state. Guardian sees safe status text, never raw error. Staff can see safe error code. |
| S6 | Existing P16-A `Agreement` artifacts get `signed_artifact_version` through migration. No network call occurs in any migration. An explicit staff/admin bulk action queues verification for existing artifacts. Permission-gated; does not mutate agreement state or billing. |
| S7 | Valid/invalid/unavailable result appears in both staff and guardian artifact surfaces for every `Agreement` belonging to a member (current, superseded, voided, discontinued), ordered newest first. For a valid result, show signer names, earliest trusted signing time, and signature format on both staff and guardian surfaces. For invalid, guardian can safely see Latvian invalid status but no technical error. For unavailable, guardian sees only neutral `Status nav pieejams`; no provider name or raw error. Staff sees safe error code. Correct: guardian does NOT always see neutral status — guardian sees `is_valid` (valid/invalid) with safe details. |
| S8 | Production sign-off requires test-environment live validation and production terms/credentials. Exact environment variable names settled in implementation planning; credentials never committed. |
| S9 | P16-B out of scope: interactive in-portal signing, raw provider URL exposure, validation stored in audit metadata, changing agreement state/billing automatically. |

### 2.2 Out of scope

- Interactive eParaksts signing within the portal.
- Raw provider URL exposure to any surface.
- Validation results stored in audit event metadata.
- Automatic agreement state or billing changes on verification result.
- Certificate data, serial numbers, or signing material persistence.
- Duplicate file storage (verification reads the P16-A artifact directly).

---

## 3. Design Decisions with Rationale

### D1. Version on `Agreement`, not on a separate model

**Decision:** `Agreement.signed_artifact_version` is a UUID generated on every upload/replacement. The validation record stores the version that was current when verification ran. Stale results (version mismatch) are discarded.

**Rationale:** A version token on the `Agreement` model provides a simple, tamper-evident way to detect race conditions: if the artifact was replaced between job enqueue and job execution, the result belongs to a different artifact version and must be discarded. Storing the token on the validation record (which is keyed to `Agreement`) means the record is self-describing — it always reflects the artifact version it was computed against.

### D2. OneToOne validation record keyed to `Agreement`, not embedded fields

**Decision:** `AgreementSignedArtifactValidation` is a separate OneToOne model with `agreement` as its FK, not fields on `Agreement`.

**Rationale:** Validation is an asynchronous, best-effort result. It may not exist (verification hasn't run yet, or the artifact was just uploaded). A separate model keeps the `Agreement` model lean and makes the absence of validation explicit (`validation is None`). It also avoids nullable fields on the `Agreement` model, which would complicate queries and indexes.

### D3. Minimal result fields

**Decision:** Persist only `signer_names`, `signing_time`, `signature_format`, `is_valid`, `validation_error_code`. Never persist raw provider responses, certificate data, serials, or URLs.

**Rationale:** The verification result is a derived, minimized projection. The raw provider response may contain certificate serials, issuer DNs, or provider URLs that are not relevant to staff or guardians and could leak infrastructure details. The minimal fields answer the only question that matters: "Is this signature valid, who signed it, and when?"

**Privacy note:** Signer names and signing time are personal data (PII). They are kept minimized, protected by staff or guardian-ownership authorization, excluded from audit metadata, and retained only as prescribed by the validation model lifecycle. They are not non-PII metadata.

### D4. Stale-result discard, not overwrite

**Decision:** Before persisting a validation result, re-read the `Agreement`'s `signed_artifact_version`. If it differs from the version the job was enqueued with, discard the result completely (no DB write, no audit event).

**Rationale:** If an artifact is replaced between enqueue and execution, the verification result belongs to the old artifact version. Persisting it would show stale validation data for the new artifact. Discarding is the safest behavior — the next upload/replacement will enqueue a fresh verification job.

### D5. Invalid ≠ unavailable

**Decision:** A result where at least one signature exists but not all have `TOTAL-PASSED` indication is `is_valid=False` (completed invalid). Provider errors (network timeout, auth failure, rate limit, unsupported format) are `is_valid=None` with `validation_error_code` set, surfaced to guardians as safe text.

**Rationale:** Invalid and unavailable are fundamentally different. Invalid means the signature was checked and failed — a definitive answer. Unavailable means the check could not be completed — an inconclusive answer. Guardians see safe status: valid results show signer names, earliest trusted signing time, and signature format; invalid shows Latvian invalid status without technical error; unavailable shows neutral `Status nav pieejams`. Staff can distinguish via the admin surface and see safe error codes.

### D6. Bulk queue action, not automatic for existing artifacts

**Decision:** Existing P16-A `Agreement` artifacts get a `signed_artifact_version` via migration (UUID4, no network call). Verification is **not** automatically queued for existing artifacts. Staff must explicitly trigger verification via an admin bulk action.

**Rationale:** Automatic verification of all existing artifacts could flood the eParaksts API (especially if there are many agreements). The bulk action gives staff control over when to run verification. It is permission-gated (`has_change_permission` on `Agreement`) and does not mutate agreement state or billing.

### D7. Guardian sees safe details for valid results

**Decision:** Guardian surfaces (family hub, parent portal) show derived status. For valid results: signer names, earliest trusted signing time, and signature format are visible on both staff and guardian surfaces. For invalid: guardian sees safe Latvian invalid status, no technical error. For unavailable: guardian sees only neutral `Status nav pieejams`; no provider name or raw error. Staff sees safe error code on unavailable.

**Rationale:** Guardian-facing copy must be user-safe. A raw error like `"EPARAKSTS_AUTH_FAILED"` or `"SIGNAPI_RATE_LIMIT"` is meaningless and alarming to a parent. Valid results are benign — signer names and signing time are already visible on the signed PDF itself. Invalid results are safe for guardians to see (it means the signature didn't pass validation) but technical error details should not be exposed. The derived status text for unavailable is neutral.

---

## 4. Components and Data Flow

### 4.1 Data model extensions

```python
# apps/agreements/models.py

# Extension to existing Agreement model:
class Agreement(models.Model):
    # ... existing fields (including P16-A artifact fields) ...
    signed_artifact_version = models.UUIDField(
        editable=False,
        default=uuid.uuid4,
        help_text="Monotonically increasing version for stale-result detection.",
    )

class AgreementSignedArtifactValidation(models.Model):
    agreement = models.OneToOneField(
        "agreements.Agreement",
        on_delete=models.CASCADE,
        related_name="validation",
    )
    artifact_version = models.UUIDField(
        help_text="Version token of the agreement artifact this validation was computed against.",
    )
    signer_names = models.JSONField(
        default=list,
        help_text="List of signer display names.",
    )
    signing_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Earliest trusted signing timestamp.",
    )
    signature_format = models.CharField(
        max_length=50,
        default="",
        help_text="Signature format, or 'mixed' if multiple formats detected.",
    )
    is_valid = models.BooleanField(
        null=True,
        blank=True,
        help_text="True if all signatures TOTAL-PASSED; False if any failed; None if unavailable.",
    )
    validation_error_code = models.CharField(
        max_length=50,
        default="",
        blank=True,
        help_text="Stable error code for staff visibility (e.g., 'unavailable', 'unsupported_format').",
    )
    validated_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this validation result was persisted.",
    )

    class Meta:
        ordering = ["-validated_at"]
```

**Field rationale:**

- **`signed_artifact_version`** on `Agreement` — generated on every upload/replacement (UUID4). Used by the verification job to detect stale results.
- **`artifact_version`** on `AgreementSignedArtifactValidation` — snapshot of the agreement's version at enqueue time. Used for stale-result comparison at persistence time.
- **`signer_names`** — JSON array of strings. No certificate data, no serials. **PII — signer names are personal data.**
- **`signing_time`** — earliest trusted signing timestamp across all signatures. `null` if no signatures. **PII — signing time is personal data.**
- **`signature_format`** — e.g., `"PAdES"`, `"XAdES"`, `"mixed"` if multiple formats. Empty string if no validation result.
- **`is_valid`** — `True` (all signatures `TOTAL-PASSED`), `False` (any signature failed or no signatures), `None` (unavailable — verification could not complete).
- **`validation_error_code`** — stable code for staff visibility. Examples: `"unavailable"`, `"unsupported_format"`, `"auth_failed"`. Never exposed to guardians.
- **`validated_at`** — auto-set on create.

### 4.2 Adapter boundary

```python
# apps/integrations/eparaksts.py (new file)

# Exception taxonomy (mirrors existing adapter pattern from apps/integrations/ocr.py and apps/integrations/docuseal.py)
class EparakstsError(Exception): ...
class ConfigError(EparakstsError): ...
class AuthError(EparakstsError): ...
class TransientError(EparakstsError): ...
class UnsupportedFormatError(EparakstsError): ...

# Frozen result dataclass
@dataclass(frozen=True)
class ValidationResult:
    signer_names: list[str]
    signing_time: datetime | None
    signature_format: str  # or "mixed"
    is_valid: bool | None  # True = valid; False = invalid; None = unavailable
    validation_error_code: str  # empty for valid/invalid; code for unavailable

def validate_artifact(file_path: str) -> ValidationResult:
    """Validate a signed artifact via eParaksts SignAPI.

    Dispatches on settings.EPARAKSTS_MODE:
    - 'stub': returns deterministic stub result (is_valid=True, fixed signer names).
    - 'eparaksts': real provider flow.
    - unknown: raises ConfigError.
    """
```

**Real eParaksts flow:**

1. **OAuth Introspect access token** — service-provider credentials → token endpoint → access token.
2. **Temporary SignAPI session** — create session via token → get `sessionId`.
3. **Upload artifact** — POST artifact to session → get `documentId`.
4. **Validate** — `GET /api-validation/v1.0/{sessionId}/{documentId}/validate` → parse response.
5. **Normalize** — map eParaksts response to `ValidationResult`:
   - Extract signer names from `signaturesExt[].signedBy`.
   - Find earliest `signaturesExt[].info.bestSignatureTime` across all signatures.
   - Determine `signature_format` from `signaturesExt[].signatureFormat`: if all signatures have the same format, use it; otherwise `"mixed"`.
   - `is_valid = True` if every signature has indication `signaturesExt[].indication = "TOTAL-PASSED"`; `False` otherwise.
   - If any step fails with a transient error, raise `TransientError`.
   - If auth/config/unsupported, raise the appropriate typed error.

**eParaksts response mapping (confirmed against official validation docs):**

| eParaksts response path | `ValidationResult` field |
|------------------------|-------------------------|
| `signaturesExt[].signedBy` | `signer_names` entry |
| `signaturesExt[].info.bestSignatureTime` | Earliest across all signatures → `signing_time` |
| `signaturesExt[].signatureFormat` | All same → format; mixed → `"mixed"` |
| All signatures `signaturesExt[].indication = "TOTAL-PASSED"` | `is_valid = True` |
| Any signature `signaturesExt[].indication != "TOTAL-PASSED"` | `is_valid = False` |
| No signatures | `is_valid = False` |
| Validation error / timeout / auth failure | `is_valid = None`, `validation_error_code` set |

**Note:** Date parsing and field mapping should be live-validation-confirmed before production sign-off, as the exact eParaksts response format may vary.

### 4.3 Background job

```python
# apps/integrations/tasks.py — new job

def process_signed_artifact_validation(agreement_id: int, artifact_version: str) -> None:
    """Verify a signed artifact via eParaksts (or stub).

    1. Open the private artifact server-side (read bytes from storage).
    2. Invoke the adapter boundary (stub/eparaksts).
    3. Re-check agreement's signed_artifact_version. If stale, discard result.
    4. Persist validationResult if not stale.
    5. Transient errors raise RetryableEparakstsError (cluster retries).
    6. Terminal errors persist 'unavailable' state and return.
    """
```

**Job behavior:**

- **Transient errors** (`TransientError`): raised → django-q2 retries (per `Q_CLUSTER.max_attempts`).
- **Terminal errors** (`ConfigError`, `AuthError`, `UnsupportedFormatError`): persisted as `is_valid=None`, `validation_error_code` set, returned (no retry).
- **Stale result**: version token mismatch → discard completely (no DB write, no audit event).
- **Success**: `is_valid=True` or `is_valid=False` persisted, no error code.

### 4.4 Enqueue on upload/replace

P16-B extends the P16-A `upload_signed_artifact` service to enqueue verification after the transaction commits:

```python
# apps/agreements/services.py — extended

def upload_signed_artifact(...):
    # ... P16-A logic ...
    agreement = Agreement.objects.get(pk=agreement.pk)  # refresh with new version
    # P16-B: enqueue verification
    from apps.integrations.tasks import enqueue_validate_signed_artifact
    enqueue_validate_signed_artifact(agreement.id, agreement.signed_artifact_version)
    return agreement
```

The enqueue helper is imported lazily inside the function to avoid circular imports (P16-A services → P16-B tasks).

### 4.5 Admin bulk queue action

```python
# apps/agreements/admin.py — new action on AgreementAdmin

def bulk_queue_validation(self, request, queryset):
    """Queue eParaksts verification for selected agreements' artifacts.

    Guards:
    - Only agreements with a signed_artifact.
    - Requires has_change_permission on Agreement.
    - Does not mutate agreement state or billing.
    """
```

**UI:** Selected agreements → "Pārbaudīt parakstus (eParaksts)" action → confirmation page → enqueue verification for each agreement → info message with count.

### 4.6 Status surfaces

**Staff surfaces (registration admin, agreement admin, family hub):**

- P16-A status text: `Status nav pieejams` (artifact exists, no validation yet).
- P16-B adds: `Paraksts derīgs ✓` (valid), `Paraksts nav derīgs` (invalid), `Verifikācija nepieejama` (unavailable).
- Staff can see `validation_error_code` in the admin detail (tooltip or expandable row).
- For valid results: signer names, earliest trusted signing time, and signature format are shown.
- Staff family hub lists all member `Agreement`s with non-empty artifacts (any lifecycle state), ordered newest first, each showing the validation status.

**Guardian portal surface:**

- Guardian portal renders a **per-member signed-artifacts list** (ordered newest first) for every `Agreement` belonging to the verified parent's members, regardless of lifecycle state (current, superseded, voided, discontinued). Each agreement with a non-empty artifact renders a card showing filename (redacted), upload date, proxy download link, and validation status.
- Valid result: show signer names, earliest trusted signing time, and signature format.
- Invalid result: show safe Latvian invalid status, no technical error details.
- Unavailable result: show neutral `Status nav pieejams`; no provider name or raw error.
- Guardian never sees raw error codes or provider names.
- DocuSeal-generated document lists (existing) remain separate and unchanged.

### 4.7 Migration for existing artifacts

The P16-B schema migration adds `signed_artifact_version` to `Agreement`. Existing `Agreement` artifacts get a `signed_artifact_version` via the migration (UUID4, no network call). No verification is queued automatically.

---

## 5. Authorization, Security, and Privacy

### 5.1 Authorization

P16-B inherits the P16-A authorization matrix (section 5.1 of P16-A spec). P16-B adds no new access paths — it only enriches the existing surfaces with validation status. The listing behavior (per-member, all-agreement states, newest-first) is gated by the same ownership checks: guardian portal queries `Agreement`s for the parent's members via `ParentAccount → Guardian → Member → Agreement`; family hub queries via `Guardian → Member → Agreement`.

### 5.2 Provider credential security

- eParaksts credentials (OAuth client/service-provider credentials, token endpoint, SignAPI base URL) are environment variables.
- Never committed to the repository.
- Exact variable names settled in implementation planning.
- Credentials used only server-side (background job + adapter). Never exposed to templates or browser.

### 5.3 Privacy

- **Signer names and signing time are personal data (PII).** They are kept minimized, protected by staff or guardian-ownership authorization, excluded from audit metadata, and retained only as prescribed by the validation model lifecycle. They are not non-PII metadata.
- No raw provider responses, certificate data, serials, or URLs are stored.
- Audit events do not include validation results (consistent with P16-A audit policy).
- Guardian surfaces never expose raw errors or provider names. Guardian sees safe details for valid results (signer names, signing time, format) but no technical error details for invalid results.

---

## 6. Error and Retry Behavior

### 6.1 Transient errors (retry)

| Error type | Example | Behavior |
|------------|---------|----------|
| Network timeout | Connection timed out | `TransientError` raised → django-q2 retries |
| Rate limit | HTTP 429 | `TransientError` raised → django-q2 retries |
| Server error | HTTP 5xx | `TransientError` raised → django-q2 retries |

### 6.2 Terminal errors (persist unavailable)

| Error type | Example | Behavior |
|------------|---------|----------|
| Auth failure | Invalid credentials | `AuthError` → persist `is_valid=None`, `validation_error_code="auth_failed"` |
| Config error | Missing endpoint | `ConfigError` → persist `is_valid=None`, `validation_error_code="config_error"` |
| Unsupported format | Non-PDF/.edoc file | `UnsupportedFormatError` → persist `is_valid=None`, `validation_error_code="unsupported_format"` |

### 6.3 Stale result handling

Before persisting any result (valid, invalid, or unavailable), the job re-reads the `Agreement`'s `signed_artifact_version`. If it differs from the enqueued version, the result is discarded completely — no DB write, no audit event. The next upload/replacement will enqueue a fresh verification job.

### 6.4 Guardian-safe status text

Guardians never see raw error codes or provider names. The derived status text varies by result:
- **Valid:** signer names, earliest trusted signing time, signature format.
- **Invalid:** safe Latvian invalid status (no technical error details).
- **Unavailable:** neutral `Status nav pieejams`; no provider name or raw error.

Staff can distinguish via the admin surface and see safe error codes.

---

## 7. Migration and Rollout Strategy

### 7.1 Migrations

One migration: `apps/agreements/migrations/0008_p16b_signed_artifact_validation.py` (P16-A migration is `0007_p16a_signed_artifact.py`).

This migration:
1. Adds `signed_artifact_version` (UUIDField, default=uuid.uuid4) to `Agreement`.
2. Creates `AgreementSignedArtifactValidation` model (OneToOne with `Agreement`).
3. Data migration: existing `Agreement` rows get a UUID4 `signed_artifact_version` (no network calls).

The schema and data migration can be combined into a single migration file if suitable.

### 7.2 Rollout order

1. Deploy P16-A (adds artifact fields to `Agreement`).
2. Deploy P16-B (adds `signed_artifact_version`, creates validation model, adds adapter + job).
3. Verify: stub mode verification runs and produces a valid result.
4. Switch to `eparaksts` mode in test environment → live validation.
5. Production sign-off: test-environment validation confirmed + production credentials/terms in place.
6. Activate production credentials.

### 7.3 Prerequisites for production sign-off

- eParaksts test-environment SignAPI credentials available and verified.
- Production eParaksts credentials available.
- Appropriate security/data-processing terms with eParaksts in place.
- Live validation against test environment confirms correct `is_valid` mapping.

---

## 8. Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC1 | `Agreement` has a `signed_artifact_version` (UUID4, generated on every upload/replacement). `AgreementSignedArtifactValidation` is a OneToOne model keyed to `Agreement` with `artifact_version`, `signer_names`, `signing_time`, `signature_format`, `is_valid`, `validation_error_code`, `validated_at`. No artifact-model `version_token` or artifact id references. |
| AC2 | A result is valid only if at least one signature exists and every signature has indication `TOTAL-PASSED`. Failed, indeterminate, or no signatures = completed invalid (`is_valid=False`). |
| AC3 | A django-q job is enqueued with `(agreement_id, artifact_version)` after upload/replace. It opens the private artifact server-side and invokes the adapter boundary. Real eParaksts flow: OAuth Introspect token → SignAPI session → upload → validate. Provider URLs never exposed to browser. |
| AC4 | Artifact version is re-checked before persisting any result. A stale result is discarded completely (no DB write, no audit event). |
| AC5 | Transient errors (network/timeout/rate-limit/server) retry via django-q2. Auth/config/unsupported errors persist `unavailable` state. Guardian sees safe status text, never raw error. |
| AC6 | Existing P16-A `Agreement` artifacts get `signed_artifact_version` via migration (UUID4, no network call). A staff/admin bulk action queues verification for existing artifacts. Permission-gated; does not mutate agreement state or billing. |
| AC7 | Valid/invalid/unavailable result appears in both staff and guardian artifact surfaces for every `Agreement` belonging to a member (current, superseded, voided, discontinued), ordered newest first. Guardian surfaces show: valid = signer names + signing time + format; invalid = safe Latvian status (no technical error); unavailable = neutral `Status nav pieejams`. Staff sees safe error code. |
| AC8 | Production sign-off requires test-environment live validation and production credentials/terms. Exact environment variable names settled in implementation planning; credentials never committed. |
| AC9 | P16-B out of scope confirmed: no interactive in-portal signing, no raw provider URL exposure, no validation in audit metadata, no automatic agreement state/billing changes. |

---

## 9. Test Strategy

### 9.1 Adapter tests (`tests/integrations/test_eparaksts_adapter.py`)

| Test | What it verifies |
|------|-----------------|
| Stub mode returns deterministic valid result | `is_valid=True`, fixed signer names, fixed signing time. |
| Stub mode returns deterministic invalid result | `is_valid=False`, no signer names. |
| OAuth token flow (stub) | Returns a non-empty access token string. |
| SignAPI session flow (stub) | Returns a valid `sessionId` and `documentId`. |
| Response normalization: all TOTAL-PASSED | `is_valid=True`. |
| Response normalization: any non-TOTAL-PASSED | `is_valid=False`. |
| Response normalization: no signatures | `is_valid=False`. |
| Response normalization: mixed formats | `signature_format="mixed"`. |
| Response mapping: `signaturesExt[].signedBy` | `signer_names` populated from correct path. |
| Response mapping: `signaturesExt[].info.bestSignatureTime` | `signing_time` populated from correct path. |
| Response mapping: `signaturesExt[].signatureFormat` | `signature_format` populated from correct path. |
| Response mapping: `signaturesExt[].indication` | `is_valid` derived from correct path. |
| Transient error (timeout) | Raises `TransientError`. |
| Transient error (rate limit) | Raises `TransientError`. |
| Terminal error (auth failure) | Raises `AuthError`. |
| Terminal error (unsupported format) | Raises `UnsupportedFormatError`. |

### 9.2 Job tests (`tests/agreements/test_signed_artifact_validation_job.py`)

| Test | What it verifies |
|------|-----------------|
| Job enqueues on upload | `upload_signed_artifact` enqueues verification with correct `agreement_id` and `artifact_version`. |
| Job persists valid result | `is_valid=True`, signer names, signing time, format persisted. |
| Job persists invalid result | `is_valid=False`, empty signer names. |
| Job persists unavailable result | `is_valid=None`, `validation_error_code` set. |
| Job discards stale result | Version token mismatch → no DB write. |
| Job retries transient errors | Raises the retryable task error so django-q2 applies its configured retry policy. |
| Job does not retry terminal errors | Terminal error persisted, no retry. |

### 9.3 Admin bulk action tests (`tests/agreements/test_bulk_queue_validation.py`)

| Test | What it verifies |
|------|-----------------|
| Bulk action enqueues for selected agreements | Correct number of jobs enqueued. |
| Bulk action skips agreements without artifacts | No jobs enqueued for agreements without `signed_artifact`. |
| Bulk action requires permission | Non-staff users cannot trigger bulk action. |
| Bulk action does not mutate agreement state | Agreement state unchanged after bulk action. |

### 9.4 Migration tests (`tests/agreements/test_signed_artifact_migration.py`)

| Test | What it verifies |
|------|-----------------|
| Migration adds `signed_artifact_version` to existing agreements | All existing `Agreement` rows have a non-null UUID4 `signed_artifact_version`. |
| Migration creates `AgreementSignedArtifactValidation` model | Model exists after migration. |
| Migration has no network calls | Migration runs without external API calls (verified by code review + no mock patches needed). |
| Reverse migration restores schema | Reverse migration drops `signed_artifact_version` and the validation model. |

### 9.5 Service extension tests (`tests/agreements/test_signed_artifact_upload_with_validation.py`)

| Test | What it verifies |
|------|-----------------|
| Upload enqueues verification | `upload_signed_artifact` enqueues a job with the correct `agreement_id` and `signed_artifact_version`. |
| Replace enqueues verification | Replacing an artifact enqueues a new verification job with the new version. |
| Upload failure does not enqueue | If upload raises `ValueError`, no job is enqueued. |

### 9.6 Surface tests

| Test | What it verifies |
|------|-----------------|
| Staff surface shows validation status | Admin detail renders `Paraksts derīgs ✓` / `Paraksts nav derīgs` / `Verifikācija nepieejama` based on validation result. |
| Staff family hub lists all agreement artifacts | Every `Agreement` for the guardian's members (current, superseded, voided, discontinued) with an artifact renders a card showing validation status; agreements without artifacts are absent. |
| Guardian surface shows valid details | Parent portal renders signer names, signing time, format for valid results. |
| Guardian surface shows per-member artifact list | Parent portal renders artifact cards for all member agreements with artifacts (any lifecycle state), ordered newest first; absent when no artifacts exist. |
| Guardian surface shows safe invalid status | Parent portal renders safe Latvian invalid status for invalid results, no technical error. |
| Guardian surface shows neutral unavailable | Parent portal renders `Status nav pieejams` for unavailable results, no provider name or raw error. |
| Guardian never sees raw errors | No error codes, provider names, or technical details in guardian-facing HTML (except safe details for valid results). |
| Guardian portal ordering | Cards are ordered by `signed_artifact_updated_at` descending (newest first). |
| DocuSeal lists remain separate | Parent portal rendered HTML contains both the signed-artifact section and the existing DocuSeal generated-document section as distinct regions. |

---

## 10. Relationship to P16-A

P16-B is a **vertical extension** of P16-A. It adds verification on top of the artifact upload/serve infrastructure.

**What P16-B adds:**

- `signed_artifact_version` field on `Agreement` (migration).
- `AgreementSignedArtifactValidation` model (OneToOne keyed to `Agreement`).
- eParaksts adapter boundary (`apps/integrations/eparaksts.py`).
- Background job (`process_signed_artifact_validation` in `apps/integrations/tasks.py`).
- Enqueue logic in `upload_signed_artifact` (P16-A service extension), passing `(agreement_id, artifact_version)`.
- Admin bulk queue action.
- Validation status rendering on staff and guardian surfaces.
- Guardian-safe status text with safe details for valid results.

**What P16-B does NOT modify:**

- P16-A upload validation rules (suffix, size, MIME).
- P16-A proxy view authorization logic.
- P16-A audit event emission (upload/replace audit events are unchanged — single `SIGNED_ARTIFACT_UPLOADED` with `operation` metadata).
- P16-A artifact serve behavior (PDF preview, `.edoc` forced-download).
- P16-A artifact fields on `Agreement`.

**Shared dependency:** Both slices reference the `Agreement` model. P16-A adds artifact fields; P16-B adds `signed_artifact_version` and creates the validation model. P16-B's migration adds columns to the existing `Agreement` model. No P16-B code depends on P16-A code beyond the model definition (the enqueue helper is a lazy import).

**Deployment dependency:** P16-A must be deployed first (it adds fields to `Agreement`). P16-B can be deployed at any time after P16-A. P16-B has a stub mode, so it can be deployed and tested without eParaksts credentials. Production activation requires credentials.

---

*End of P16-B design specification.*

# P5 Slice D — DocuSeal Self-Hosted Adapter + Signed-State Sync

**Status:** Design (brainstormed, awaiting review)
**Acceptance items:** P5 items 6, 8, 9, 10
**Base branch:** `dev`
**Predecessor:** Slice C (`apps/agreements/` model + generation + visibility), which reserved the `external_*` fields and established the bidirectional signing-path invariant.

## Context

Slice C delivered the `Agreement` domain: a per-member state machine (`generated → sent → signed`, plus `void`), plain-text Latvian emails on each transition, a `signing_path` field (`electronic` | `paper`), and a bidirectional sync invariant (`agreement.signing_path == application.preferred_agreement_signing`). It deliberately left the DocuSeal-reservation fields (`external_provider`, `external_id`, `external_state`, `external_url`) populated by nothing — they exist on the model but no code writes them.

Slice D fills those reservations: it wires the **electronic** signing path to a self-hosted DocuSeal instance so a guardian signs the membership agreement online, and Django's `Agreement.state` advances to `signed` when DocuSeal reports completion. The **paper** path is untouched — it remains the existing Django-only, staff-managed manual flow.

The DocuSeal instance is already provisioned. The agreement template inside DocuSeal (its named fields) is the one open infra dependency; the adapter maps to placeholder field keys isolated in a single function so renaming to match the real template is a one-line change.

## Why now

Slice C made agreements real but inert for the electronic path: staff can mark an agreement `sent`, but nothing actually requests a signature, and `signed` can only be set manually. Slice D closes the loop — the preferred (electronic) path becomes a working e-signature flow, and the parent is freed from a physical-signature step.

## Locked decisions (from brainstorm)

1. **Sync mechanism** — Webhook (`submission.completed`) + an admin manual "Pārbaudīt DocuSeal statusu" re-sync button.
2. **State during the create-submission job** — Optimistic: `state` becomes `sent` immediately when staff act; the DocuSeal submission is created in a background django-q2 job.
3. **Void cleanup** — Voiding an electronic agreement with an active submission enqueues a DocuSeal archive call alongside the Django void.
4. **Failure surface** — DocuSeal job failures write `external_state="failed"` + `external_error_code`; the Līgums module renders a Latvian error + "Mēģināt vēlreiz" retry button.
5. **Email suppression (electronic only)** — Suppress the `sent` and `signed` Django emails (DocuSeal notifies the signer); the `void` email always sends. Paper path emails on all transitions, unchanged.
6. **DocuSeal link** — The Līgums module renders an "Atvērt DocuSeal ↗" link when `external_url` is set.
7. **Stub provider** — Deterministic fake returning predictable `external_id` + `external_url`; never auto-fires the webhook. Tests POST the webhook directly to drive `signed`.
8. **Webhook events** — Only `submission.completed` drives a Django state change; all other events are acknowledged (200) and ignored.

## Existing pieces we reuse

- **OCR adapter shape** (`apps/integrations/ocr.py`) — boundary module + concrete provider + `*_PROVIDER_MODE` stub/real switch + classified exceptions. Mirrored exactly for the agreement platform.
- **django-q2 task pattern** (`apps/integrations/tasks.py`) — enqueue helpers; `Q_CLUSTER` already configured with `max_attempts=2`, `retry=90`, `timeout=60`. Reused for the three new jobs.
- **HMAC verification** — the M6 deploy-listener already validates `hmac.new(secret, raw_body, sha256)` + `hmac.compare_digest`. Same scheme for the DocuSeal webhook.
- **`apps/agreements/services.py` transitions** — `mark_agreement_sent`, `mark_agreement_signed`, `void_agreement`, `set_signing_path`. Extended (not rewritten) to add electronic-path side-effects.
- **`Agreement.external_*` reserved fields** — populated for the first time here.
- **Bidirectional signing-path invariant** — reused by the electronic→paper fallback, which routes through `set_signing_path` to keep `application.preferred_agreement_signing` in sync.

## Changes

### 1. Model — `apps/agreements/models.py`

Add one field (the only schema change in this slice):

```python
external_error_code = models.CharField(max_length=64, blank=True, default="")
```

One migration: `apps/agreements/migrations/XXXX_agreement_external_error_code.py`.

Normalized `external_state` values written by the adapter: `"pending"`, `"completed"`, `"archived"`, `"failed"`.

### 2. Boundary — `apps/integrations/agreement_platform.py` (new)

```python
class AgreementPlatformError(Exception): ...
class AgreementPlatformConfigError(AgreementPlatformError): ...     # missing/bad settings → permanent
class AgreementPlatformAuthError(AgreementPlatformError): ...       # 401/403 → permanent
class AgreementPlatformNotFoundError(AgreementPlatformError): ...   # 404 on sync/archive → permanent
class AgreementPlatformTransientError(AgreementPlatformError): ...  # 5xx/timeout/conn → retryable

@dataclass(frozen=True)
class SubmissionResult:
    external_id: str
    external_url: str
    external_state: str  # "pending" | "completed" | "archived"

def create_submission(agreement) -> SubmissionResult: ...
def sync_submission(external_id: str) -> SubmissionResult: ...
def archive_submission(external_id: str) -> None: ...
def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool: ...
```

Provider mode switch on `settings.AGREEMENT_PROVIDER_MODE` (`"stub"` default, `"docuseal"` in prod). Stub returns:
- `external_id = f"stub-{agreement.id}"`
- `external_url = f"https://stub.invalid/{agreement.id}"`
- `external_state = "pending"`

and never fires a webhook.

### 3. Provider — `apps/integrations/docuseal.py` (new)

Real DocuSeal HTTP calls:
- **create_submission** — POST DocuSeal "create submission" with template id + submitter + prefilled field values. Returns normalized `SubmissionResult`.
- **sync_submission** — GET submission status, normalize.
- **archive_submission** — POST/DELETE archive endpoint.
- **verify_webhook_signature** — `hmac.compare_digest(expected_hex, header)` over the raw body.

Field payload builders, isolated for testability and template-rebinding:

```python
def _build_submitter(agreement) -> dict:
    guardian = agreement.member.guardian
    return {"email": guardian.email, "name": guardian.full_name, "role": "Vecāks"}

def _build_field_payload(agreement) -> dict:
    member = agreement.member
    guardian = member.guardian
    return {
        "child_name": member.full_name,
        "child_personal_id": member.personal_id,
        "child_birth_date": member.birth_date.isoformat() if member.birth_date else "",
        "guardian_name": guardian.full_name,
        "guardian_personal_id": guardian.personal_id,
        "guardian_address": guardian.address,
        "agreement_date": agreement.generated_at.date().isoformat(),
    }
```

**Field-payload notes:**
- **Submitter (structural, required by the API):** `Guardian.email` (signer), `Guardian.full_name`, constant role `"Vecāks"`.
- **Prefilled values (template-bound keys):** the data set is fixed (above); the key strings are bindable to the DocuSeal template — change them in `_build_field_payload` only. `training_group` is **not** sent.
- Blank/null model fields pass through as empty strings; no hard failure for missing personal_id, birth_date, or address.

### 4. Tasks — `apps/integrations/tasks.py` (extend)

```python
def create_agreement_submission(agreement_id: int) -> None: ...
def sync_agreement_submission(agreement_id: int) -> None: ...
def archive_agreement_submission(external_id: str) -> None: ...
```

- **create** — calls `create_submission`, stores `external_provider="docuseal"`, `external_id`, `external_url`, `external_state`. On `TransientError`: re-raise so django-q2 retries (`max_attempts=2`). On `Auth/Config/NotFound`: write `external_state="failed"` + `external_error_code`, do not retry.
- **sync** — calls `sync_submission`; if `completed`, drives `mark_agreement_signed` (idempotent). Same exception classification.
- **archive** — calls `archive_submission`; failure logs + leaves a retryable error surface; the Django void itself already succeeded independently.

### 5. Service wiring — `apps/agreements/services.py` (extend)

Electronic-path side-effects layered onto existing transitions. Paper path unchanged.

| Transition | Electronic-path addition |
|---|---|
| `mark_agreement_sent` | If `Guardian.email` empty → `set_signing_path(agreement, PAPER, actor)` and fall through to paper behavior (no DocuSeal). Else: set `sent` (optimistic), **suppress `sent` email**, enqueue `create_agreement_submission(agreement.id)`. |
| `mark_agreement_signed` | Reached for electronic via the webhook; **suppress `signed` email**. Paper still emails. |
| `void_agreement` | Set `void`, **send `void` email** (both paths), and if electronic with `external_id` set, enqueue `archive_agreement_submission(external_id)`. |

Email suppression lives in one helper:

```python
def _should_send_email(agreement, template_name) -> bool:
    if (agreement.signing_path == Agreement.SigningPath.ELECTRONIC
            and template_name in {"sent", "signed"}):
        return False
    return True
```

`_render_and_send_agreement_email` early-returns when `_should_send_email` is `False`.

**Electronic→paper fallback caveat (documented, not solved here):** the paper `sent` email also targets `Guardian.email`, so a guardian with no email is not notified on either path. Pre-existing paper-path condition; out of Slice D scope.

### 6. Webhook — `apps/agreements/webhooks.py` (new) + URL mount

```
POST /integrations/docuseal/webhook/
```

- `@csrf_exempt`, POST-only (405 otherwise). Auth is the HMAC, not a session.
- Verify `X-Docuseal-Signature` over the raw body via `verify_webhook_signature`. Fail → `403`, no DB touch.
- Parse JSON. `event_type != "submission.completed"` → `200` no-op.
- Look up `Agreement.objects.filter(external_id=...).first()`. No match → `200` + log (stale/foreign submission).
- Match → `mark_agreement_signed(agreement, actor=None)` (idempotent; already-`signed` returns early). Transition errors log but still return `200` so DocuSeal doesn't retry on our bug.

Mount in `fk_cesis_mms/urls.py` (or `apps/agreements/urls.py` included there).

### 7. Līgums module UI — `apps/agreements` view/template (extend)

- `external_state == "failed"` → Latvian error (via an `agreement_messages` lookup on `external_error_code`) + "Mēģināt vēlreiz" submit → re-enqueues `create_agreement_submission`.
- `external_id` set → "Pārbaudīt DocuSeal statusu" submit → enqueues `sync_agreement_submission`.
- `external_url` set → "Atvērt DocuSeal ↗" link.

### 8. Settings — `fk_cesis_mms/settings.py`

```
AGREEMENT_PROVIDER_MODE   # default "stub"; "docuseal" in prod
DOCUSEAL_API_URL
DOCUSEAL_API_KEY
DOCUSEAL_TEMPLATE_ID
DOCUSEAL_WEBHOOK_SECRET
```

All empty-string defaults so dev/test run in stub mode without them. Added to the `docs/deployment.md` "required secrets" pre-flight.

### Files touched

- `apps/agreements/models.py` (+1 field) + new migration
- `apps/integrations/agreement_platform.py` (new — boundary)
- `apps/integrations/docuseal.py` (new — provider)
- `apps/integrations/tasks.py` (extend — 3 jobs)
- `apps/agreements/services.py` (extend — electronic side-effects + suppression helper)
- `apps/agreements/webhooks.py` (new) + `urls.py` mount
- `apps/agreements/` Līgums view + template (extend)
- `fk_cesis_mms/settings.py` (+5 settings)
- `docs/deployment.md` (required-secrets pre-flight)
- Tests (below)

## Tests

- `tests/integrations/test_agreement_platform_adapter.py` — stub determinism; mode switch; HTTP failure → exception class mapping (401→Auth, 404→NotFound, 5xx/timeout→Transient, missing config→Config).
- `tests/integrations/test_docuseal_provider.py` — mocked HTTP: create-submission request shape (URL, headers, template id, submitter, field payload), response normalization, `verify_webhook_signature` accept/reject.
- `tests/agreements/test_docuseal_webhook.py` — valid sig + `submission.completed` → `signed`; bad sig → 403; wrong event → 200 no-op; unknown `external_id` → 200 no-op; already-signed → 200 idempotent; GET → 405.
- `tests/agreements/test_electronic_flow_integration.py` — electronic `mark_agreement_sent` sets `sent` + enqueues create (stub) + stores `external_id/url`; webhook → `signed`. Paper: no external calls, no enqueue. Empty-email electronic → falls back to paper (signing_path flips, application synced, no DocuSeal).
- `tests/agreements/test_electronic_email_suppression.py` — electronic `sent`/`signed` send 0 emails; electronic `void` sends 1; paper sends on all three (`mail.outbox`).
- `tests/agreements/test_void_archives_submission.py` — electronic void with `external_id` enqueues archive; paper void / electronic-without-external-id does not.

## Out of scope (explicit)

- DocuSeal template field configuration (infra task; mapped to placeholder keys).
- Scheduled/cron polling — manual button + webhook only.
- Storing the signed PDF back into Django (`Document`).
- Multi-signer / counter-signature flows — single guardian signer.
- Regenerating an agreement after `void` (terminal; Slice C decision stands).
- Retry/backoff tuning beyond existing `Q_CLUSTER` `max_attempts=2`.
- Sending `training_group` to DocuSeal.

## Verification

1. `uv run pytest -q` → full suite green (≥ current baseline).
2. `uv run ruff check .` and `uv run mypy .` clean.
3. Stub-mode manual LAN check (`AGREEMENT_PROVIDER_MODE=stub`):
   - Approve an application with electronic preference → mark sent → `state=sent`, `external_id`/`external_url` populated, no `sent` email in console backend.
   - POST a signed-event payload to the webhook with a valid HMAC → `state=signed`, no `signed` email.
   - Void the signed electronic agreement → `void` email sent, archive job enqueued.
   - Electronic agreement whose guardian has no email → marking sent falls back to paper (signing_path=paper, application synced).
   - Paper agreement → emails on sent/signed; no DocuSeal calls.
4. Real-mode smoke (once DocuSeal template configured): create-submission against the live instance; bad API key surfaces in Līgums module with Latvian copy + "Mēģināt vēlreiz"; "Pārbaudīt DocuSeal statusu" runs a sync.
5. Update `AGENTS.md` ("Current Status" + "P5 Slice D delivered") and `docs/milestones.md`.

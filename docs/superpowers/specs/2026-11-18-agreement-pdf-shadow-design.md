# Agreement PDF shadow forwarding

## Scope change and authorization

User requests shadow forwarding so the new PDF approach can be tested without
cutover. This **replaces full migration as the next implementation deliverable**.
The local-agreement-pdfs migration spec/plan remains future work; do not execute
its backend switching, handover/signing guards or historical-archive steps here.

Implement in the current checkout. No worktree, commit, push, deployment, mode
activation, live signing/mail, DB migration on the existing root database, or
DocuSeal retirement. A default-off capability can be built/tested without accepting
the native-library findings for deployment. Final-image security and manual signing
gates in the feasibility checkpoint remain open.

## Chosen flow

```
Existing primary generation job → DocuSeal → existing agreement update
                                               │
                         enabled? capture same submitted field values
                                               │ best-effort enqueue
                                        separate shadow job
                                               │
                                   private comparison-only PDF
```

DocuSeal remains authoritative for documents, notifications and state. Shadow output
is never sent to parents, used for signing/billing, or substituted for primary PDF.
Enable only with `AGREEMENT_PDF_SHADOW_ENABLED=true`, default false, on web/worker.
Build wiring now; do not turn this on against a live environment in this task.

## Snapshot accuracy and forwarding boundary

Hook **successful new generation attempts**, after the existing
`create_agreement_submission` job has persisted the DocuSeal result. No automatic
backfill or scan of old agreements. Primary failure means no comparable result and
no shadow forwarding. Primary success must remain success even if shadow recording,
queueing/rendering/storage fails.

Capture the exact field map already used by `docuseal.create_submission`, plus the
signing path used for that attempt. Do not re-read current model data in the shadow
worker: parent/profile edits may happen after primary submission. Avoid serializing
models, external URLs, API credentials or tokens into a task payload.

Extend `agreement_platform.SubmissionResult` compatibly with optional
`generation_snapshot` (default None, excluded from repr/comparison). The real provider
reuses its already-built field dictionary; do not alter the DocuSeal HTTP payload or
add a second primary call. Attach snapshot only when shadow enabled. Stub mode may
construct the same dictionary for focused tests, but snapshot failure must not break
the pre-existing stub result. Existing mocked result objects without the new field
remain valid (`getattr` at hook boundary).

Field allowlist is current primary payload: agreement_number, child_name,
child_personal_id, child_birth_date, child_address, guardian_name,
guardian_personal_id, guardian_address, guardian_email, guardian_phone.
Snapshot also records signing_path. No browser input can select arbitrary templates.

## Shadow persistence and lifecycle

Add `AgreementPDFShadow` related to Agreement, not a new operative agreement or a
replacement for `signed_artifact`. Store primary submission ID, shadow template
version, captured signing path, pending/ready/failed status, private PDF, file size,
SHA-256, timestamps, generic error code, renderer/font/template provenance and frozen
allowlisted input while pending/failed. Clear input JSON after successful publication
to avoid retaining an unnecessary duplicate of sensitive fields.

Unique per `(agreement, primary_external_id, template_version)`. Repeated forwarding
or job retry cannot overwrite a ready PDF. Concurrent publication chooses one winner
under a row lock and removes unused temporary storage objects. A new primary
submission can have a new comparison row; no implicit regeneration of old output.

The model's string/display/log/audit metadata uses IDs/status only, never snapshot,
names, personal IDs, addresses or email contents. Apply the same private-storage and
DB/backup protections as existing agreement/person data. No snapshot editor/export.
Deletion follows Agreement ownership/CASCADE and cleans up its private artifact
after commit; no unrelated retention policy is introduced.

Failed jobs can be retried by staff without re-sending or mutating DocuSeal. Retain
their original frozen input. Template/CSS/asset versions must remain immutable and
available for retries; changed/missing provenance fails explicitly, never falls back
to a current template. Turning flag off stops new forwarding and queued rendering;
already-ready shadow PDFs remain readable, and pending work is explicitly marked
disabled/failed rather than falsely ready.

## Renderer and visual contract

Use WeasyPrint **70.0**, reviewed versioned Django HTML/CSS, known local font/logo
assets and fail-closed 70.0 URLFetcher allowlisting. No PDF extraction at runtime,
user HTML/CSS/URLs, network resource fetching, JS, OCR inputs or uploaded images.
Use existing 60s worker timeout; cap PDF output at 20 MiB/20 pages. Record exact
renderer/native/font provenance; no new claims of PDF/A, signature validity or DRM.

Approved style: DejaVu Sans legal body, DejaVu Sans Mono Bold every inserted value.
Preserve 50 EUR and other agreed clauses. Paper omits electronic-signature footer,
timestamp header and electronic/timestamp sentences of final 7.5; retains ordinary
date field/signature lines. Electronic provisions unchanged. This expected paper
wording difference from today's DocuSeal template must be explained in comparison UI.

Every page clearly says comparison-only / not for signing, in Latvian. **Do not label
real forwarded data synthetic.** Remove prototype diagnostic alphabet. The source
blank PDF and its digest are in the feasibility checkpoint; transcribe reviewed
clauses into HTML once, not from a temporary file when the app runs.

## Staff comparison surface

Provide read-only Django admin list/detail for shadow records, with agreement link,
status/provenance and side-by-side or paired links to **DocuSeal original** and
**comparison PDF**, plus POST-only failed retry. Primary comparison fetch uses the
shadow row's saved submission ID, not Agreement.external_id which may later change.
No raw provider/storage URLs in HTML. Existing parent/admin primary links stay as-is.

Local/primary preview/download endpoints accept only shadow record IDs and resolve
ownership server-side. Active staff only, validate disposition, stream privately,
set private/no-store headers and audit preview/download with redacted metadata.
Use existing audit action choices rather than introduce unrelated event taxonomy.
Disabled/pending/failed rows never pretend a PDF exists; ready data remains accessible
after feature flag off. No parent route, bulk backfill, primary resend or auto-approval.

## Verification and acceptance

Mode **tested**, focused regressions plus repository-required full gates. Verify:
flag-off unchanged primary behavior/no shadow data; exact submitted field capture;
same source submission shown after later primary changes; primary failure no shadow;
shadow queue/render/DB/storage failure never changes primary outcome/notifications;
both signing paths; no signing/billing/state mutations; snapshot changes after
enqueue do not affect output; disabled worker; immutable ready output/idempotency;
concurrent publication on PostgreSQL; retry same snapshot; no PII in logging;
staff-only private/audited endpoints and CSRF-safe retry; autoescaping/resource guards;
actual rendered text/font/page checks and visual inspection. Tests must stub external
providers/mail and use isolated DB/storage.

No deployment claim. Deliver docs for enabling in an explicitly chosen dev environment
and inspecting comparisons, disabling, retrying, cleanup and current security limits.
Retain legacy migration plan as future work, not a shadow implementation checklist.

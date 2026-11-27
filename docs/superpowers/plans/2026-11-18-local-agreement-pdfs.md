# Local Agreement PDFs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate immutable private PDFs for new agreements without DocuSeal,
preserving manual signing and legacy document access.

**Architecture:** Versioned Django HTML/CSS renders through WeasyPrint 70.0 in a
background job. A one-to-one unsigned-document record owns frozen job input and
immutable output; existing agreement/signing/billing services remain authoritative.
Per-agreement backend selection separates new local rows from untouched legacy rows.

**Tech Stack:** Django, Python >=3.14, PostgreSQL, django-q2, WeasyPrint 70.0, private
storage, existing PyMuPDF inspection/rasterization.

**Spec:** `docs/superpowers/specs/2026-11-18-local-agreement-pdfs-design.md`

**Status:** Plan recorded, not executed. User sample layout approved. Security gates,
manual signing and independent review remain open. Consult feasibility evidence
before implementation; never treat prototype image scans as release approval.

**Next-deliverable change:** user subsequently requested shadow forwarding. Execute
`2026-11-18-agreement-pdf-shadow.md` first; this full cutover plan is future work,
not the current implementation brief.

## Global Constraints

- Verification mode: **tested**; focused regression tests per unit and full project
  gates before completion. TDD ordering may be used, but no mandatory red phase.
- No old agreement regeneration or historical-row reclassification; default mode
  stays legacy until explicit activation. No production DB/remote mutation.
- No commit, push, deployment, worktree, archive or DocuSeal shutdown unless asked.
- Exact approved typography, 50 EUR and paper/electronic wording in the spec apply.
- Preserve signing/billing guards; generation/upload never means signed.
- Use `uv add 'weasyprint==70.0'` when dependencies are implemented; do not copy the
  spike's isolated dependency commands into the application deployment workflow.
- Subagents currently have an unresolved Invalid credential failure; restore/verify
  their health before delegation. If unavailable, report lack of independent review
  and implement directly only within authorized scope; never invent review approval.

## Review Focus

- Guardian edits or template deployment between retries must not change frozen input.
- Duplicate jobs/storage save failure must not replace or orphan published artifacts.
- Signing-path changes through the application admin sync must obey the same freeze.
- Old external-ID-only lists/guards must not hide or remotely fetch local PDFs.
- Global rollback must not route already-local agreements back to DocuSeal.

---

### Task 1: Production renderer and reviewed template

**Files:** create `apps/agreements/pdf_rendering.py`,
`templates/agreements/pdf/v1-2026-11.html`, `apps/agreements/pdf_assets/` with CSS,
three reviewed fonts/logo/licenses; modify `pyproject.toml`, `uv.lock`, `Dockerfile`;
tests `tests/agreements/test_pdf_rendering.py`.

**Interfaces:** `render_agreement_pdf(context: dict, *, signing_path: str,
template_version: str) -> bytes`. Accept only documented snapshot keys and two
signing paths; unsupported version/path raises ValueError. No DB or network reads.

- [ ] Transcribe actual approved clauses into the versioned template, comparing
  normalized text to the blank source digest in feasibility evidence. Remove sample
  warnings/alphabet; preserve all non-authorized legal wording/numbering.
- [ ] Test normal/long/Latvian/special HTML characters, all fill-value font uses,
  unchanged fee, paper omissions/electronic inclusions, embedded fonts/page bounds,
  no TEST text, unsupported mode/version and blocked remote/arbitrary local resources.
- [ ] Implement fail-closed exact asset fetcher with WeasyPrint 70 URLFetcher API.
  No `safe` filtering of field values, PDF extraction or remote assets at runtime.
- [ ] Version HTML/CSS/font/logo bytes together; keep issued versions immutable and
  retain them for pending/failed jobs. Test unknown/missing/mismatched assets fail
  explicitly rather than selecting the current template during retry.
- [ ] Add native typography dependencies to both builder/runtime where required;
  keep existing non-root/no-runtime-installer policy. Record font digests/license.
- [ ] Run `uv run pytest -q tests/agreements/test_pdf_rendering.py` and inspect
  actual rendered normal/long paper/electronic pages, not only extracted text.

### Task 2: Immutable document model and async publication

**Files:** `apps/agreements/models.py`, migration
`apps/agreements/migrations/0008_local_generated_documents.py`, create
`apps/agreements/document_generation.py`, `apps/agreements/tasks.py`; modify
`apps/agreements/services.py`, `fk_cesis_mms/settings.py`, `.env.example`;
tests `tests/agreements/test_document_generation.py`.

**Interfaces:** `request_document_generation(agreement, actor) -> GeneratedAgreementDocument`,
`retry_document_generation(agreement, actor) -> GeneratedAgreementDocument`,
`generate_agreement_document(document_id: int) -> None` (job),
`enqueue_document_generation(document_id: int) -> None` (on-commit caller).
Model/fields/states follow the spec; one-to-one reverse name `generated_document`.

- [ ] Add default-legacy backend marker and additive one-to-one model. Migration
  must perform no document/remote I/O and create no PDFs for historical rows.
- [ ] Read `AGREEMENT_DOCUMENT_MODE` only on new agreement creation, including
  material amendment/regeneration constructors. Preserve existing number allocation.
- [ ] Lock agreement/document rows at freeze/publication boundaries; capture only
  specified inputs, render outside long DB locks, publish one winning artifact,
  clear snapshot on ready and clean unsuccessful storage writes after commit.
- [ ] Generic redacted errors leave frozen input retryable; ready is immutable.
  Reject signing-path mutations after freezing through both service sync writers.
- [ ] Test legacy migration/defaults, normal generation, retry after profile/template
  change, duplicate jobs/concurrency (PostgreSQL), save/crash failure, no orphaned
  new files, preserved old bytes, path-sync guard and mode rollback.
- [ ] Run `uv run pytest -q tests/agreements/test_document_generation.py` and
  `uv run python manage.py makemigrations --check`; use isolated test DB only.

### Task 3: Staff lifecycle and authorized document surfaces

**Files:** `apps/agreements/services.py`, `document_proxy.py`, `presentation.py`,
`apps/agreements/admin.py`, `apps/registrations/admin.py`, `admin_panels.py`,
`apps/members/admin.py`, `apps/admin_hub/views.py`,
`templates/registrations/admin/_agreement_module.html`,
`templates/admin/_agreement_list.html`, `templates/admin_hub/agreement.html`,
existing agreement email templates; tests
`tests/agreements/test_local_document_workflow.py` and affected existing suites.

**Interfaces:** retain `build_agreement_document_response(agreement, *, disposition)`
and existing route names/ownership checks. Add `generate_pdf` / `retry_pdf` branches
to existing registration review-action dispatch, not a second mutation layer.

- [ ] Expose generation pending/ready/failed and retry within current agreement UI;
  handover requires ready PDF for local rows. Generation does not advance lifecycle.
- [ ] Local handover sends club-owned manual-process notification on either path;
  no signing-session claim, attachment or new parent unsigned endpoint. Local rows
  never enqueue DocuSeal create/sync/archive. Keep legacy behavior and external IDs.
- [ ] Local staff signing requires ready PDF plus all existing plan/month guards;
  preserve explicit staff confirmation and billing signal. Artifact upload alone
  still changes no lifecycle/billing state.
- [ ] Serve private immutable local bytes, never silently re-render/fallback remotely.
  Update all external_id-only list/query/view gates to handle ready local artifacts.
  Preserve safe filenames/disposition validation and audited ID-only access metadata.
- [ ] Test all three staff surfaces, anonymous/nonstaff/foreign ownership, missing
  local storage, inline/download/invalid disposition, local historical visibility,
  legacy retrieval, frozen-path lifecycle, void/new agreement and unchanged billing.
- [ ] Run focused local workflow plus existing document proxy, lifecycle, signed
  artifact, registration/admin and billing-trigger regression suites.

### Task 4: Blank preview and operator documentation

**Files:** `apps/agreements/template_preview.py`,
`apps/registrations/preview_views.py`,
`templates/parent_ui/includes/agreement_preview.html`, `static/js/agreement_preview.js`,
`tests/registrations/test_agreement_template_preview.py`,
`docs/registration-agreement-preview.md`, new `docs/local-agreement-pdfs.md`.

**Interfaces:** extend preview get/enqueue/refresh/cache-key helpers with explicit
validated signing path. Local cache identity includes backend/template version/path;
legacy API/settings still supported during coexistence.

- [ ] Find immediate callers/JS consumer before edits; propagate selected paper /
  electronic path to the manifest request without trusting arbitrary parameters.
- [ ] Generate blank local template in worker, keep raster-only verified-parent
  delivery/private cache bounds; never create agreement/document rows from preview.
- [ ] Test selected-path correctness, cross-path cache separation, no PII/submissions,
  verified/active-account access, failures and legacy preview regression.
- [ ] Document generate/handover/manual signing/upload, frozen data/path, retry,
  versioning, coexistence, setting rollback, security obligations and no historical
  regeneration. DocuSeal retirement stays a separate operator task.

### Task 5: Acceptance, independent review and promotion boundary

- [ ] Run `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`,
  `uv run python manage.py makemigrations --check`, scoped Git whitespace checks.
  Record all skips/errors honestly; use PostgreSQL for locking/concurrency checks.
- [ ] Build exact final app image; scan baseline/candidate with same DB and retain
  all findings. Fixable H/C fail gate. Review newly introduced unfixed findings
  explicitly; current minimal smoke does not satisfy release security criteria.
- [ ] Manual eParaksts sample signing/opening plus staff generation → handover →
  signed-file upload → explicit sign → billing acceptance, and paper equivalent.
  Expose local acceptance via authorized tunnel; no live provider/mail by accident.
- [ ] Independent reviewer verifies spec first, quality second, including all five
  review-focus classes. Report credential blocker if unavailable; no rubber stamp.
- [ ] Update milestone/AGENTS/docs only with evidenced implemented/accepted status.
  No deployment, mode activation, commit/push or historical archive/shutdown without
  explicit authorization. Leave old DocuSeal documents and pending sessions intact.

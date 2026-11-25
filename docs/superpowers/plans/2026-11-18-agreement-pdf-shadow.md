# Agreement PDF Shadow Forwarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically create private comparison PDFs for future successful primary
generation attempts, while DocuSeal stays authoritative and shadowing defaults off.

**Architecture:** Primary provider returns an optional exact generation snapshot;
post-primary job hook records/enqueues a separate shadow artifact. An isolated
renderer and read-only staff comparison surface never affect agreement state/mail.

**Tech Stack:** Django, Python >=3.14, django-q2, PostgreSQL, private storage,
WeasyPrint 70.0, existing PyMuPDF.

**Spec:** `docs/superpowers/specs/2026-11-18-agreement-pdf-shadow-design.md`

**Execution status:** implemented directly in the parent session after delegated
execution stopped during initial reads. Final isolated PostgreSQL gate: 2964 passed,
0 failures/errors/skips; static gates and exact image build/smoke passed. Shadow
defaults off; root database migration, activation, independent code review, live
provider/browser acceptance and deployment remain open. See
`docs/acceptance/2026-11-18-agreement-pdf-shadow.md`. Do not replay the stalled child
implementation: application code now exists. Its historical diagnostic remains at
`/tmp/opencode/weasyprint-agreement/shadow-execution-blocker.md`.

## Global Constraints

- Verification mode **tested**; regression tests for behavior and full repo gates.
- Current checkout only; no worktree, commit/push, deployment, activation, live
  external calls/mail, root DB migration, backfill or DocuSeal shutdown.
- Shadow flag defaults false. No migration backend flag, operative PDF replacement,
  new handover/signing guard or production cutover from the older migration plan.
- Approved fixed-width field styling, paper/electronic text and unchanged 50 EUR.
- Security/manual-signing/release gates remain explicit; shadow is not a workaround
  for unresolved native-library risks in deployed environments.
- Inspect all listed files/immediate callers before edits. Agent writes only intended
  scope; preserve existing uncommitted spike/design work from this parent session.

## Review Focus

- Later guardian/Agreement.external_id edits cannot corrupt an earlier comparison.
- DB/queue/render/storage exceptions in shadow cannot fail the primary operation.
- Duplicate/concurrent jobs never replace a ready artifact or leak temporary files.
- Disabling feature stops capture/render but not reading an already-ready artifact.
- Real forwarded PII remains private, escaped, audited and absent from logs/task args.

### Task 1: Versioned comparison renderer

**Files:** create `apps/agreements/pdf_rendering.py`,
`templates/agreements/pdf/shadow_v1.html`, dedicated CSS/assets/provenance; modify
`pyproject.toml`, `uv.lock`, `Dockerfile`; test
`tests/agreements/test_shadow_pdf_rendering.py`.

**Interface:** `render_shadow_pdf(snapshot: dict, *, template_version: str) -> bytes`;
`shadow_renderer_provenance() -> dict` with safe version/hash values only.

- [ ] Add tests from approved samples for exact field text, fixed-width font,
  variant-specific text, unchanged fee, comparison warning on every page, no false
  synthetic-data label, autoescaping, resource rejection and output/page limits.
- [ ] Use `uv add 'weasyprint==70.0'`; port approved template into source HTML and
  keep legal text directly versioned. No temporary-source-PDF runtime dependency.
- [ ] Add necessary native packages to correct image stages, retaining non-root
  security policy. Explicitly identify/version font assets and fail closed on mismatch.
- [ ] Render actual normal/long paper/electronic samples and inspect PNGs. Run
  focused renderer suite; record source/provenance and visual evidence.

### Task 2: Snapshot forwarding and shadow job

**Files:** `apps/integrations/agreement_platform.py`, `docuseal.py`, `tasks.py`,
`apps/agreements/models.py`, new `shadow.py`, `shadow_tasks.py`, migration after
`agreements/0007`, `fk_cesis_mms/settings.py`, `.env.example`; tests
`tests/agreements/test_pdf_shadow.py`, affected provider/job regression files.

**Interfaces:** optional repr-/comparison-excluded `SubmissionResult.generation_snapshot`;
`enqueue_agreement_pdf_shadow(agreement, result) -> None` (best-effort boundary);
`render_agreement_pdf_shadow(shadow_id: int) -> None`; `retry_pdf_shadow(shadow, actor)`.

- [ ] Add default-off flag and additive AgreementPDFShadow model following spec;
  no migration network/file generation. Capture only allowlisted primitive values.
- [ ] Reuse the real provider's already-built field map without changing POST JSON;
  return optional snapshot only when enabled. Keep stub/mocked results backward safe.
- [ ] Forward only after existing primary result save; isolate all shadow failures,
  including transaction/savepoint/queue issues. Queue carries row ID, not PII.
- [ ] Implement frozen-input worker, explicit disabled handling, safe retry and
  row-locked immutable publication with cleanup and snapshot clearing on success.
- [ ] Test every failure class/flag branch, no primary/billing/mail state changes,
  post-enqueue edits, duplicate/concurrent jobs, version mismatch and no PII logging.
  Use PostgreSQL for meaningful lock/concurrency checks, isolated storage/DB.

### Task 3: Private comparison UI and operator checks

**Files:** new `apps/agreements/shadow_admin.py` (import/register from `admin.py`),
`templates/admin/agreements/agreementpdfshadow/change_form.html`,
`tests/agreements/test_pdf_shadow_admin.py`, `docs/agreement-pdf-shadow.md`;
update `AGENTS.md`/`docs/milestones.md` only with verified DEV status.

- [ ] Read-only staff list/detail with source agreement, comparison status and
  unambiguous paired primary/local preview/download controls; saved source ID only.
- [ ] Add private/no-store staff-only stream endpoints, safe dispositions, redacted
  audit access, POST-only failed retry with CSRF enforcement. Parent URLs unchanged.
- [ ] Test unauthorized/missing/failed/disabled/ready access, HTML does not expose
  provider/storage URLs, saved-ID comparison after primary change, and retry isolation.
- [ ] Document default-off enablement in explicitly chosen dev environment, required
  migrations/dependencies/shared storage, inspection/retry/disable and risk limits.
- [ ] Run full `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`,
  `uv run python manage.py makemigrations --check`, whitespace checks. State all
  skips. Review spec compliance then independent code quality; report auth blocker.
- [ ] Build/scan exact candidate if feasible, compare same DB and report inherited /
  introduced findings. No promotion/activation without required security review.

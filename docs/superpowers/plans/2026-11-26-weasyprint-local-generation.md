# WeasyPrint Local Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Slice A as default-off local agreement generation, and prepare evidence for a separately authorized activation.

**Architecture:** Persist the document backend on each agreement and select it only when creating a new row. An explicit staff request freezes a private input snapshot and queues an isolated renderer; a single immutable private PDF is published without changing signing or billing state. Existing DocuSeal rows and issued sessions remain legacy, while a separate cutoff prevents new sessions after a controlled worker quiescence.

**Tech Stack:** Django 6, Python 3.14+ (current `pyproject.toml`), PostgreSQL, django-q2, WeasyPrint 70.0, PyMuPDF, private shared storage.

**Spec:** `docs/superpowers/specs/2026-11-26-weasyprint-rollout-and-docuseal-preservation-design.md`; document contract: `docs/superpowers/specs/2026-11-18-local-agreement-pdfs-design.md`. The older `docs/superpowers/plans/2026-11-18-local-agreement-pdfs.md` is historical, not executable.

## Global Constraints

- Planning baseline: `dev` at `da0d414`; verify the actual source and migration graph at execution. Preserve unrelated changes. No staging, commit, provider call, deployment, mode change, archive or shutdown is authorized by this plan.
- `agreements/0008_agreement_pdf_shadow` already exists; create the next migration after the actual graph head. `pyproject.toml` already pins `weasyprint==70.0`; do not add it again. Shadow output is watermarked comparison material and is never an operative PDF.
- Mode defaults to `docuseal`; cutoff defaults open to preserve existing behavior. Existing rows, including non-current and no-ID rows, remain `docuseal`. Backend is immutable after creation; settings affect future rows only.
- Staff prepares the PDF explicitly. A ready local PDF is required before handover **and** explicit signing confirmation; upload alone, rendering and preview never sign or create billing. Keep all existing billing-plan/month guards and the existing signing signal.
- Retain private access, plain-text notifications and existing authorization. No unsigned parent download, attachment, new signing integration, signature-validity claim, provider fallback or silent historical regeneration.
- Template `v1-2026-11` is distinct from `shadow-v1-2026-11`: preserve approved clauses, 50 EUR base fee, typography and path-specific wording; do not silently amend legal text. Keep immutable HTML/CSS/font/logo versions and their digests for retries.
- Tests-first: write and run failing focused tests before each implementation, then rerun green. Use isolated databases and stubbed providers/mail; no real provider or external signing without separate authorization.
- Slice B archive and Slice C disable are not designed or implemented here. The approved detached-archive decision remains in the rollout spec; no retention duration is established.

## Review Focus

- A profile, template or asset changes between freeze and retry: the original snapshot and exact version win (Task 2).
- Duplicate jobs, failed commits or missing bytes: only one immutable file survives; no remote fallback (Tasks 2 and 4).
- Staff or application admin changes the path after freeze: neither side persists a conflicting path (Task 3).
- Queued legacy create or old worker overlaps cutoff: guards block queued work, but operator quiescence is essential for in-flight HTTP (Tasks 3 and 6).
- Both blank-preview paths remain isolated across version/cache keys and parent authorization, including stale pages (Task 5).

---

### Task 1: Durable routing and production renderer

**Owner:** agreement domain. **Files:** modify `apps/agreements/models.py`, `apps/agreements/services.py`, `fk_cesis_mms/settings.py`, `.env.example`, `apps/agreements/pdf_rendering.py`; create a new migration after `0008`, `templates/agreements/pdf/v1_2026_11.html`, `apps/agreements/pdf_assets/v1_2026_11.css`; extend `tests/agreements/test_pdf_shadow.py`; create `tests/agreements/test_local_pdf_rendering.py` and `tests/agreements/test_document_backend.py`.

**Interfaces:** Add `Agreement.document_backend` choices `docuseal`/`local`, migration default `docuseal`, and `AGREEMENT_DOCUMENT_MODE` default `docuseal`. Add `render_agreement_pdf(snapshot: dict, *, template_version: str) -> bytes` and `agreement_renderer_provenance(template_version: str) -> dict`; retain `render_shadow_pdf` and shadow provenance unchanged.

- [ ] Write tests that migrate representative current, historical, failed and no-ID agreements without changing external fields; check default, invalid configuration fail-closed, approval via `create_agreement_for_member`, idempotent existing-row return, `regenerate_agreement`, and `start_material_amendment`. Check both mode settings select only new rows and rollback never reclassifies existing rows. Also test `renew_member_billing` does not create a new Agreement: current renewal is billing-only, despite the rollout spec's general reference to renewal.
- [ ] Run `uv run pytest -q tests/agreements/test_document_backend.py`; expect failures for missing interface, not provider access.
- [ ] Implement selection at both actual constructors in `services.py`, preserving the material amendment's copied billing setup and number allocation. Add the additive migration and setting. Do not add an agreement-creation side effect to billing renewal.
- [ ] Write renderer tests for paper/electronic text differences, 50 EUR, long/Latvian/escaped input, no shadow watermark, page/20 MiB limits, blocked network and arbitrary file resources, immutable version/digest mismatch, and unchanged shadow rendering. Compare actual template against authorized source when available; absence blocks activation, not development.
- [ ] Run `uv run pytest -q tests/agreements/test_local_pdf_rendering.py tests/agreements/test_pdf_shadow.py`; expect new renderer tests to fail first. Implement a separate production template based on the reviewed shadow source, reusing only safe renderer primitives such as `AssetFetcher`; use the exact existing font/logo assets with recorded digests and licensing. Do not edit the shadow version in place.
- [ ] Rerun both focused commands and `uv run python manage.py makemigrations --check`; expect passing tests and no missing migrations.

### Task 2: Snapshot, queue and immutable publication

**Owner:** agreement domain/worker. **Files:** modify `apps/agreements/models.py`, new migration, `apps/agreements/apps.py` as needed; create `apps/agreements/document_generation.py`, `apps/agreements/document_tasks.py`, `tests/agreements/test_document_generation.py`.

**Interfaces:** Add `GeneratedAgreementDocument` one-to-one reverse `generated_document`, with private file, pending/ready/failed, version, frozen path, temporary snapshot, provenance, SHA-256, size, timestamps and generic error. Expose `request_document_generation(agreement: Agreement, actor) -> GeneratedAgreementDocument`, `retry_document_generation(agreement: Agreement, actor) -> GeneratedAgreementDocument`, and worker `generate_agreement_document(document_id: int) -> None`.

- [ ] Write tests for explicit request only; agreement number, child name/PID/DOB/address and guardian name/PID/address/email/phone plus signing path/version frozen under lock; no OCR, upload, training group or billing data. Assert snapshot never appears in admin, logs, audit metadata or exports, persists on failure, and clears on ready. Confirm enqueue occurs only after commit and never after rollback; queue failure remains visibly retryable.
- [ ] Add PostgreSQL concurrency tests for two requests and duplicate workers: one row, one winning file/hash, no overwrite; retry after profile change renders frozen input; mismatched/missing version/assets fail closed; failed DB commit, deleted row and storage failure clean temporary files without deleting published bytes. Deletion of stored files follows DB commit; no lifecycle, mail or billing changes.
- [ ] Run `uv run pytest -q tests/agreements/test_document_generation.py`; expect missing-interface failures. Implement row-locked freeze and publication, render outside locks, validate PDF/limits and provenance, use unique private temporary names, delete losing files safely, and enqueue with `transaction.on_commit`. Record redacted errors only. Follow `shadow_tasks.py` as a safety reference, not as operative output.
- [ ] Rerun focused tests against isolated PostgreSQL, including real concurrent transactions, and `uv run python manage.py makemigrations --check`; expect pass and no model drift.

### Task 3: Lifecycle guards, cutoff and manual notifications

**Owner:** agreement domain/integration. **Files:** `apps/agreements/services.py`, `apps/integrations/tasks.py`, `apps/integrations/agreement_platform.py`, `apps/registrations/admin.py`, `apps/members/admin.py`, `templates/emails/agreements/sent.txt`, `templates/emails/agreements/signed.txt`, settings and `.env.example`; create `tests/agreements/test_local_lifecycle.py`, `tests/integrations/test_agreement_cutoff.py`.

**Interfaces:** Retain `mark_agreement_sent(agreement, actor)`, `mark_agreement_signed(agreement, actor)`, `set_signing_path(agreement, signing_path, actor)`, `sync_application_signing_path_to_agreement(application)`, and `create_agreement_submission(agreement_id: int, send_email: bool = True)`. Add boolean `AGREEMENT_DOCUSEAL_CREATE_ENABLED`, default true, checked for legacy creates; false is the separately authorized cutoff.

- [ ] Test pending/failed/missing-file local PDFs block handover and signing before state, email, audit or billing mutation; ready files permit both paths subject to existing plan/month guards. Upload alone does not sign. Frozen path changes through both setter and admin application sync fail atomically without persisting either side; unchanged path is a no-op. Exercise `RegistrationApplicationAdmin.save_model`, not just the helper.
- [ ] Test local paper and electronic handover/signed notices are club-owned plain text with no provider link, session claim or attachment; verify legacy electronic suppression and paper behavior remain unchanged. Local send/sync/archive/retry never contacts DocuSeal. A missing email must not silently change a frozen electronic path to paper.
- [ ] Test cutoff at send/retry, enqueue, worker execution and provider-create boundary: legacy no-ID rows, including uploaded artifacts and queued jobs, cannot send or confirm signing after cutoff; no state/mail/billing changes and no HTTP call. Legacy rows with an ID retain normal sync/completion, existing upload and reference; never infer no remote submission merely from missing ID. Verify local rows cannot enter provider create even when cutoff is open.
- [ ] Run `uv run pytest -q tests/agreements/test_local_lifecycle.py tests/integrations/test_agreement_cutoff.py`; expect failures. Implement guards before mutations, make errors visible on existing admin/Hub surfaces, and route notices by durable backend. Restrict provider create at each boundary without blocking issued-session sync. Preserve `external_*` fields and existing signed uploads.
- [ ] Rerun focused tests plus `uv run pytest -q tests/agreements/test_agreement_services.py tests/agreements/test_agreement_signed_signal.py tests/integrations/test_agreement_tasks.py tests/registrations/test_admin_agreement_lifecycle.py`; expect pass. Configuration checks cannot cancel an HTTP POST already running in an old process: Task 6 explicitly requires quiescence before the cutoff.

### Task 4: Staff generation and document routes

**Owner:** staff surfaces/security. **Files:** `apps/registrations/admin.py`, `apps/registrations/admin_panels.py`, `apps/members/admin.py`, `apps/agreements/admin.py`, `apps/agreements/document_proxy.py`, `apps/agreements/presentation.py`, `apps/admin_hub/views.py`, `templates/registrations/admin/_agreement_module.html`, `templates/admin/_agreement_list.html`, `templates/admin_hub/agreement.html`; create `tests/agreements/test_local_document_workflow.py`.

**Interfaces:** Existing review-action dispatch gains POST actions `generate_pdf` and `retry_pdf` invoking Task 2. Keep `build_agreement_document_response(agreement: Agreement, *, disposition: Literal["inline", "attachment"]) -> StreamingHttpResponse` and existing route names/ownership checks.

- [ ] Test staff action/status/retry and ready download in registration admin, Agreement admin, family hub and Admin Hub as applicable. Check CSRF, anonymous/nonstaff denial, foreign guardian/application 404, historical local rows, inline/attachment and invalid disposition, private/no-store headers and redacted access audit. Parent routes must not acquire unsigned access.
- [ ] Test missing or corrupt local bytes fail visibly without provider calls or regeneration; legacy rows still use their existing proxy. Check every `external_id`-only list and route guard, including `RegistrationApplicationAdmin.docuseal_document_view`, `GuardianAdmin.family_hub_docuseal_document_view`, and `AgreementAdmin.docuseal_document_view`.
- [ ] Run `uv run pytest -q tests/agreements/test_local_document_workflow.py`; expect missing action/routing failures. Implement existing admin mutation delegation and ready local-byte routing; preserve descriptive filenames and provider split-origin/redirect restrictions. Ensure views, not caller-supplied IDs, enforce association and permission.
- [ ] Rerun focused tests and `uv run pytest -q tests/agreements/test_agreement_admin_document.py tests/admin_hub/test_hub_agreement.py tests/registrations/test_admin_review_agreement_ui.py`; expect pass.

### Task 5: Local blank preview

**Owner:** registration/preview. **Files:** `apps/agreements/template_preview.py`, `apps/registrations/preview_views.py`, `templates/parent_ui/includes/agreement_preview.html`, `static/js/agreement_preview.js`, `tests/registrations/test_agreement_template_preview.py`, `docs/registration-agreement-preview.md`.

**Interfaces:** Extend `get_preview`, `preview_failed`, `enqueue_template_preview` and `refresh_template_preview` to carry validated backend/version/signing path; propagate the same identity through manifest and image requests. Preserve `agreement_template_preview(request)` and `agreement_template_page(request, version, page)` route names and active verified-parent checks.

- [ ] Write tests for both selected paths, switching while a request is in flight, version/path/backend-separated cache and stale image URL rejection, invalid path, inactive/anonymous parent denial, page limits and 202/503 behavior. Assert blank raster-only output, no PII, agreement row, submission, provider call in local mode or PDF response; retain legacy preview tests.
- [ ] Run `uv run pytest -q tests/registrations/test_agreement_template_preview.py`; expect new assertions to fail. Implement blank snapshot rendering through Task 1 in qcluster and PyMuPDF rasterization in the existing private shared cache. Pass validated path with page URLs and queue arguments so web and worker resolve the same key; prevent stale asynchronous JS responses replacing the newly selected path. Keep legacy mode operational.
- [ ] Rerun focused tests and the repository's relevant JavaScript harness; inspect both paths in a local browser with stubbed services. Update preview documentation to describe cache identity, shared volume, authorization and failure behavior.

### Task 6: Verification, readiness and separately authorized cutover

**Owner:** release operator and independent reviewer. **Files:** create `docs/local-agreement-pdfs.md` and a dated acceptance record; update `docs/milestones.md` and `AGENTS.md` only with evidenced implementation status during execution.

**Interfaces:** No additional runtime API. Default-off implementation completion is distinct from activation readiness and from authorization to deploy or change modes.

- [ ] Document staff prepare/retry/download, manual paper/eParaksts handover, signed PDF/edoc upload and explicit confirmation, frozen path/version, privacy, failure recovery and historical routing. Record that plain email does not deliver the unsigned file. Document cutoff, no-ID adjudication and rollback below.
- [ ] Run `uv run pytest -q` on isolated PostgreSQL, `uv run ruff check .`, `uv run mypy .`, `uv run python manage.py makemigrations --check`, and scoped `git diff --check`; record exact counts, skips and failures. Run concurrent PostgreSQL tests explicitly; do not present SQLite locks as equivalent. Obtain independent spec and security review, or report the blocker.
- [ ] For activation readiness, build the **exact candidate final image** from identified source and lockfile; record source/image/platform digests. Scan baseline and candidate with the same current scanner/database, retaining full reports and native findings; fixable HIGH/CRITICAL findings block promotion. Review newly introduced unfixed HIGH/CRITICAL findings and obtain explicit risk acceptance where required. Exercise final-image PostgreSQL suite, web/worker, private storage, non-root native renderer and encryption smoke; account for every skip. Earlier 2989-test and image-scan evidence is historical, not this gate.
- [ ] In an authorized isolated dev acceptance environment using that exact image, verify source comparison and document-owner approval for both templates; visual normal/long output; both manual handover paths, eParaksts sample opening/signing where separately authorized, upload then explicit confirmation, unchanged billing, void/replacement, legacy access, blank preview, auth and browser behavior. Use synthetic data and stubbed provider/mail unless separate live-use approval exists. Record results and gaps; a local synthetic test does not establish deployed/provider acceptance.
- [ ] Before requesting cutoff, inventory and have the data owner adjudicate every legacy draft, failed and ambiguous no-ID row, including possible remote submissions and paper exceptions; preserve uploads and external references. Record boundary, exceptions and evidence without sensitive content. Between default-off testing and any approved cutoff, the legacy default continues creating normal sessions; refresh inventory immediately before cutoff and account for all sessions/jobs created in that interval.
- [ ] Only after separate target/deployment and activation approval: stop new staff sends, quiesce **all old web and qcluster processes**, drain or reconcile queued, running, retrying and uncertain create jobs and any in-flight HTTP POST, then deploy identical cutoff-enabled configuration to web and workers. Verify no old processes remain and no new provider sessions arise before resuming traffic; allow only already-issued sessions to sync. A configuration flip alone cannot fence a running request. Any unresolved no-ID case remains blocked before send/sign, not silently replaced.
- [ ] Rollback before disable requires separate authorization: quiesce/reconcile jobs again, deliberately lift cutoff and restore legacy default only for future rows. Existing local rows and PDFs remain local and readable; do not delete artifacts or reopen sessions. Any later provider re-enable after Slice C requires separate authorization, security/configuration checks and reconciliation, not merely a mode flip. B archive/import, integration disable and provider shutdown each remain separate decisions.

## Open decisions and contradictions

- The rollout spec names renewal among agreement creation routes, but `renew_member_billing` currently renews billing only; Task 1 tests that reality rather than inventing a new lifecycle.
- Current `mark_agreement_sent` automatically changes electronic to paper when email is absent; this conflicts with a frozen path. Task 3 refuses that change for frozen local rows and preserves legacy behavior.
- Authorized blank source and document-owner approval, exact target/cutoff, data-owner no-ID dispositions, live provider/browser exercise and final-image security acceptance are not established by this plan. They block the relevant readiness or activation gate, not template development.
- The detached legacy archive is approved as a direction only. Its interfaces, retention and implementation belong to a later Slice B plan; no Slice C disabled-mode behavior is claimed here.

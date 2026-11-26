# Agreement PDF shadow — resumed verification, 2026-11-25

> **Current status:** The fixture repair and subsequent security follow-up passed the
> real-clock PostgreSQL full gate (2989 passed, no failures, errors or skips), and
> independent code review approved the changes with deferred minor findings. See
> [the later repair and review record](2026-11-25-shadow-test-repair-and-review.md).
> The failed run and other observations below are preserved as historical evidence.

## Result at resume: implementation present; full gate not green

Resumed the existing checkout on `dev` at HEAD
`9bf076b4743055cfb8c74e53a5fe4d97fb66019d`. Shadow implementation was already
present. No product code was changed during this resume. Existing staged and
unstaged spike, design and implementation changes were preserved.

The 2026-11-18 acceptance note remains historical evidence, not the result of
this rerun. Its `/tmp/opencode/weasyprint-agreement/` artifacts, including the
blank source PDF and approved revision-2 samples, are no longer available on this
host. The retained candidate Docker image still has the documented identity.
No fresh security scan or source-PDF transcription comparison was performed.

## Fresh checks

All database checks used a newly created disposable PostgreSQL 18 container,
`fk-shadow-resume-pg`, with tmpfs data and a random loopback-only port. Temporary
settings directed uploads/private files to `/tmp/opencode/fk-shadow-resume/`,
used stub providers, in-memory mail, and kept the runtime shadow flag off.
Tests explicitly enable shadowing only within their test settings.

| Check | Observed result |
| --- | --- |
| Shadow-specific suite | 28 passed, 0 failures/errors/skips |
| Shadow + primary adapter/provider/jobs + runtime security contracts | 78 passed, 0 failures/errors/skips, 10.563 s |
| Full suite, real 2026-11-25 clock, correct synchronous-worker harness | **2883 passed, 26 failed, 55 errors, 0 skipped**, 302.277 s |
| `uv run ruff check .` | Passed |
| `uv run mypy .` | Passed, 523 source files; existing annotation notes |
| Isolated `uv run python manage.py makemigrations --check --dry-run` | No changes detected |
| `git diff --check -- . ':!spikes'` | Passed |
| Whole-checkout whitespace check | Two existing trailing spaces in parent-owned `spikes/weasyprint-agreement/fonts/LICENSE-DejaVu.txt`; preserved |
| Retained exact-image offline smoke | UID 10001, flag off, paper/electronic rendering passed with network disabled, read-only root and no capabilities |

Fresh artifacts are under `/tmp/opencode/fk-shadow-resume/`:

- `changed-boundaries.xml`, `changed-boundaries.log`: final focused boundary gate.
- `focused.xml`, `focused.log`: original 28-case focused run. Its database teardown
  warned about two remaining test connections; only the disposable test database
  was force-dropped before the next run.
- `full-sync.xml`, `full-sync.log`: **authoritative real-clock full rerun**.
- `ruff.log`, `mypy.log`, `migrations.log`, `whitespace.log`.
- `verification_settings.py`: exact isolated settings used.
- `image-smoke.log`: retained candidate smoke output.
- `render_samples.py`, `samples.json`, `samples.log`, and four `*-normal.pdf` /
  `*-long.pdf` paper/electronic samples plus representative first/final PNGs.

### Failure diagnosis and harness limitations

Existing agreement/billing fixtures use a `2026/2027` default plan. On November 25,
the cutoff advances the first billing month into December; skipping December then
advances into January 2027. The existing year guard correctly declines automatic
selection for that 2026-start plan. Fixtures assuming a preselected plan then fail
with `billing plan required`; 55 full-suite setup errors have this message.
Neither the billing default-selection service nor these legacy fixtures was
changed by shadow work.

A narrow temporary diagnostic supplied November 18 only to the default billing
month calculation: all **18 lifecycle service tests passed**. Evidence:
`billing_clock.py`, `billing-clock-diagnosis.xml` and `.log`. This confirms the
date-sensitive fixture cause for that group; it is not a normal full-suite pass
or permission to bypass current-date signing guards. Remaining failures require
triage before the required full gate can be called green.

Two exploratory runs are retained but are **not acceptance gates**:

- `full.xml` / `.log`: 52 failures and 55 errors. Explicitly setting
  `DJANGO_SETTINGS_MODULE` loads settings before project conftest defaults; this
  initial harness missed `Q_CLUSTER_SYNC=1`. The corrected rerun above removes
  those asynchronous OCR-related failures. Providers were stubbed in both runs.
- `full-pinned.xml` / `.log`, `pinned_clock.py`: globally pinning Django time to
  November 18 removed billing setup errors but introduced frozen-time ordering and
  default-callable inconsistencies: 2955 passed, 9 failed. This workaround was
  rejected as a verification gate; no project clock or tests were changed.

Host warnings include missing local `staticfiles/` and HarfBuzz-Subset deprecation.
The earlier final-image security counts remain historical, unresolved risk
evidence; the previous scanner database/reports are absent here.

## Visual smoke

Actual app renderer (WeasyPrint 70.0) produced four synthetic-data fixtures, each
three A4 pages, sizes 213193 / 213637 / 213572 / 214025 bytes. Inspected normal-paper
first page and long-electronic last page: comparison warning visible, fixed-width
inserted values, ordinary paper date field and expected electronic footer. Every
page's extracted text contains `NAV DERĪGS PARAKSTĪŠANAI`; no synthetic label is
embedded in the reusable legal template. This is author visual smoke, not
independent approval or a renewed comparison against the missing approved samples.

Retained image: `fk-cesis-mms:shadow-candidate`,
`sha256:2ce91e8258dbc0b92f684067a357eb64aa6d2fe6cd98bd470f25b4a262b17ac1`.
No image was rebuilt, promoted or published during this resume.

## Exact implementation file scope

These existing implementation changes remain in the checkout; they were not
reimplemented during this resume:

```text
.dockerignore
.env.example
AGENTS.md
Dockerfile
apps/agreements/admin.py
apps/agreements/apps.py
apps/agreements/migrations/0008_agreement_pdf_shadow.py
apps/agreements/models.py
apps/agreements/pdf_assets/shadow_v1.css
apps/agreements/pdf_rendering.py
apps/agreements/shadow.py
apps/agreements/shadow_admin.py
apps/agreements/shadow_tasks.py
apps/integrations/agreement_platform.py
apps/integrations/docuseal.py
apps/integrations/tasks.py
docs/acceptance/2026-11-18-agreement-pdf-shadow.md
docs/agreement-pdf-shadow.md
docs/milestones.md
fk_cesis_mms/settings.py
pyproject.toml
templates/admin/agreements/agreementpdfshadow/change_form.html
templates/agreements/pdf/shadow_v1.html
tests/agreements/test_pdf_shadow.py
tests/deployment/test_runtime_security_contract.py
uv.lock
```

This resume adds this acceptance file and updates status pointers in `AGENTS.md`,
`docs/milestones.md`, `docs/agreement-pdf-shadow.md` and the historical acceptance
note. Parent-owned `spikes/`, feasibility notes and local-PDF/shadow design/plan
documents are unchanged by this resume. Temporary harness files live only under
`/tmp/opencode/fk-shadow-resume/`.

## Remaining gates and boundaries

- Required real-clock full gate is **not green**. Resolve the date-fragile fixture
  coverage and triage remaining failures; do not weaken production guards.
- Independent read-only review is pending parent coordination. No retry of known
  invalid-credential agents and no change to authentication was attempted.
- Security risk acceptance, fresh scanning, browser/live-provider comparison,
  approved dev migration/activation and deployment remain open.
- No worktree, commit, push, deploy, live provider/mail call, root DB migration,
  historical backfill, feature activation or shutdown of existing services.
- DocuSeal remains primary; no state/mail/billing/parent-document changes.
- Trello tracking was not used: no project board mapping exists.

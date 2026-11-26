# Agreement PDF shadow forwarding — local verification

**Historical checkpoint.** Resumed real-clock verification on 2026-11-25 is not
fully green (78 focused passed; full: 2883 passed / 26 failed / 55 errors, no skips).
Earlier temporary artifacts are no longer present. See
`docs/acceptance/2026-11-25-agreement-pdf-shadow-resume.md` for fresh evidence and
date-sensitive fixture diagnosis; do not treat this older gate as the latest run.

## Delivered, not activated

Implemented directly after delegated execution/review infrastructure failures.
Default-off flag, exact successful-primary field capture, separate private shadow
record/worker, versioned reviewed HTML/CSS, fixed-width values, expected paper
omissions, explicit comparison warnings, audited private staff comparison and
independent retry. No operative PDF/state/billing/mail/parent route replacement.

`agreements/0008_agreement_pdf_shadow` is additive. Only isolated test databases
were migrated. Root database, `.env`, existing provider records/agreements and
runtime flag remain untouched. No live provider calls, live mail, publication,
deployment, commit, push or DocuSeal shutdown. Operator guide:
`docs/agreement-pdf-shadow.md`.

## Verification evidence

- Final full isolated PostgreSQL run: **2964 tests, 0 failures, 0 errors, 0 skipped**,
  345.724 seconds in personally inspected XML. **28 shadow test cases** include real
  rendering, default-off compatibility, exact submitted-field capture, primary and
  queue/DB/render/storage failure isolation, frozen input, duplicate/concurrent
  publication, failed-publication cleanup, after-commit deletion, provenance mismatch,
  disable/retry behavior, crashed-worker stale pending recovery, saved primary ID,
  staff-only/no-store/audited streams, private detail and CSRF enforcement.
- XML: `/tmp/opencode/weasyprint-agreement/shadow-verified-pg.xml`.
  Earlier failed/pre-fix and passing reports are historical, not the final gate.
- `uv run ruff check .`: passed. `uv run mypy .`: passed, 523 source files, existing
  untyped-body annotation notes. `uv run python manage.py makemigrations --check`:
  no changes detected. Scoped whitespace inspected.
- Warnings: test suite reports 1244 warnings, dominated by existing missing local
  staticfiles-directory warnings, plus host HarfBuzz-Subset deprecation. Required
  native subset package is installed in the final image; host OS was not modified.
- Original blank source digest in the feasibility checkpoint was used for a one-time
  transcription check: **73 introduction/heading/clause fragments, zero missing**,
  ignoring whitespace/blank underscores. No runtime source-PDF extraction dependency.
- Actual app renderer generated four synthetic normal/long paper/electronic samples
  in `/tmp/opencode/weasyprint-agreement/shadow-samples/`; representative first/final
  PNGs inspected. All pages warn not for signing; no real PII was used in samples.

## Exact final image

- Matched baseline built from Git HEAD
  `9bf076b4743055cfb8c74e53a5fe4d97fb66019d` via `git archive HEAD | docker build … -`.
- Baseline `fk-cesis-mms:shadow-baseline`:
  `sha256:b4d5f3b9f3d8c844cbee95d646795c74d278ab41d393f3c9c7b00083eba6365e`,
  447777366 bytes.
- Final candidate `fk-cesis-mms:shadow-candidate`:
  `sha256:2ce91e8258dbc0b92f684067a357eb64aa6d2fe6cd98bd470f25b4a262b17ac1`,
  563052013 bytes. Local build only, not published. Delta ~109.9 MiB uncompressed.
- Both use Python 3.14.10/Trixie base index
  `sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f`.
- Exact candidate smoke: network disabled, read-only root, tmpfs font cache, no
  capabilities, no-new-privileges, 512 MiB limit, image default **UID 10001**.
  Flag verified off; no `.env` or `spikes/` baked in. Both paper/electronic PDFs
  rendered (212625 / 213020 bytes), three pages each, without a DB or provider.

## Security — narrow gate passes, risk review remains open

Pinned Trivy 0.76.1, same retained DB SHA-256:
`2a16239b389bf61a1f7404eb61968d25e5aacfce3791196bdb22aea025259c3d`.

| Exact image | Critical | High | Fixable H/C |
| --- | ---: | ---: | ---: |
| Current-HEAD matched baseline | 0 | 48 | 1 |
| Final patched shadow candidate | 0 | 51 | 0 |

An initial exact candidate failed on inherited zlib1g HIGH CVE-2026-85091. The final
Dockerfile explicitly refreshes this direct compression dependency alongside four
native typography packages, no blanket OS upgrade or extra dev/curl tools. A narrow
deployment-contract test was observed failing before that fix, then the entire suite
passed. Final fixable-H/C scanner gate **passed**, not bypassed or suppressed.

Four **introduced unfixed HIGH** Expat findings remain (CVE-2026-113351,
CVE-2026-115506, CVE-2026-117610, CVE-2026-118370); one fixable zlib finding was
removed. Counts are package/advisory findings, not proof of reachability. No newly
introduced critical/fixable H/C, but this is **not** risk acceptance or unrestricted
deployment clearance. Existing security obligations still apply to shadowing.

Artifacts: `/tmp/opencode/weasyprint-agreement/final-baseline-scan/`,
`final-patched-candidate-scan/`, `shadow-final-security-delta.json`. Initial unpatched
candidate report is retained separately as `final-candidate-scan/`.

## Rulings and remaining acceptance

- Direct tested execution in existing checkout, no worktree/commits; independent
  `code-reviewer` and `recovery` calls still return Invalid credential. Controller
  self-inspection and regressions are not independent review approval. Docs writer
  did inspect/write the operator guide.
- System font bytes/Pango/renderer/template provenance are captured and compared;
  a changed image/asset set blocks a pending retry rather than rendering different
  inputs silently. Operators must retain the matching environment for retry.
- Existing blanket ban on every apt install was narrowed to the exact typography
  dependencies plus zlib refresh; security scans remain mandatory. Native attack
  surface and the four introduced unfixed HIGH findings remain explicit costs.
- Worker crash can leave a pending row; after five minutes staff may re-enqueue the
  same snapshot, never re-send DocuSeal. Concurrent publication still has one winner.

Open: independent code review, browser/live-DocuSeal comparison acceptance, explicit
dev-environment migration/activation and risk review. Manual eParaksts/signing and
full replacement remain future scope; shadow PDFs must not be signed or sent as
operative agreements. No release or production sign-off.

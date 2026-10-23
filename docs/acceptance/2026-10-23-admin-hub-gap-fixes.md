# Admin Hub gap fixes — scoped local acceptance

**Date:** 2026-10-23
**Status:** All four slices were exercised locally. The controller's post-tooltip-fix full regression passed **2769 tests, 0 failures, 0 errors, 0 skipped** on 2026-10-23. This is not deployment acceptance or automatic milestone/release sign-off; history acceptance remains partial.

## Environment and provenance

- The application ran from the current dirty `dev` checkout against disposable PostgreSQL **18.6**, with **en_US.utf8** collation/ctype and the libc locale provider. No production database or data was used. Additive migration `registrations/0013_applicationcorrectionmessage.py` was applied only to the acceptance test database.
- Browser evidence came from real **Chromium 155**, headless, controlled through **playwriter** at `http://127.0.0.1:42471`. Phone viewport/touch checks were emulated, not performed on physical hardware.
- Email used Django's **locmem** backend; OCR, agreement and invoice providers used **stub** mode. No live SMTP or provider delivery was tested.
- An initial setup attempt reached its step cap; contaminated entries were excluded from recovered evidence. Recovery identified a local/tunnel origin mismatch: an inherited tunnel setting affected absolute email links, while final browser checks used the local origin. Authenticated tunnel acceptance was not performed. This does not establish an infrastructure outage.

Two recovered passes reported **14 passing main preview/medical cases**, plus **one contract observation, not a failure**, and **7 passing grouped search/history cases**, with **one parent-browser resubmission subcase not run**. These are scoped case counts, not an automated test total or proof that every planned scenario passed.

## Results by slice

| Slice | Exercised behavior and result |
|---|---|
| 1 — Search | Child/guardian partial names, reversed and split tokens, matching tab counts, pagination, retained/encoded query, clear and no-match states passed in the browser and against PostgreSQL ground truth. PostgreSQL `ILIKE` matched `JĀNIS` with `Jānis` and `BĒRZIŅŠ` with `Bērziņš` under this locale. There is no accent folding: SQL returned **0** for `Berzins`; that spelling was not separately browser-tested. Other database locales are not covered. |
| 2 — Native previews | A real two-page PDF rendered in Chromium's native viewer, visually confirmed by screenshot showing both page thumbnails and fixture text, not merely iframe presence. Private inline PDF headers, tab/link synchronization, image rotate/zoom/fit/keyboard transforms, first-document-missing and all-missing states, HEIC decode-error fallback, and safe unsupported-DOCX fallback passed. Phone viewport/touch emulation switched image/PDF tabs without reported horizontal overflow. |
| 3 — Medical upload | Real form-driven first upload and replacement before approval, and replacement after approval, passed with status, validity, approved-member linkage and medical preview/download links checked. Missing file, DOCX and an oversized PDF retained the existing file, displayed localized errors and returned to the cockpit. Staff without change permission could read status but had no upload/file controls; direct file/action requests were denied. Anonymous redirects and the permitted-admin inverse were checked. |
| 4 — Correction history | Hover/focus fetched no history; click opened the native dialog. Escaped text, 20+5 paging, Escape/close/backdrop dismissal and focus return, no-history copy, no-JavaScript standalone navigation, private/no-store headers, unknown-object denial, non-staff denial and method denial passed. POST without CSRF returned 403; with valid CSRF it returned 405 (`Allow: GET`). A later simulated failed attempt retained the last successful send timestamp. |

**Medical validation observation:** A text-content file named `.pdf` with declared `application/pdf` was accepted. Validation follows the filename-extension/declared-MIME contract, not MIME byte-sniffing. This was an observation, not a contract failure; no validation change was made.

**History evidence boundaries:** Failed-send rows were simulated database fixtures, not SMTP failures. Network abort and expired-session redirect were deliberately intercepted/simulated; the dialog showed an error and did not inject the login page. Authenticated non-staff denial used an explicitly constructed synthetic session, not a successful admin login. A genuine staff browser correction request created a `sent` history row through locmem acceptance. Resubmission was then **service-driven**, followed by browser confirmation that the exact subject/body remained unchanged and the row was resolved. **Parent-browser OTP/login and resubmission were NOT RUN.** Multiple complete parent-browser correction cycles are not claimed. “Sent” means backend acceptance, not delivered or opened mail.

## Acceptance-found defect and verification

One genuine minor defect was found: a focused row's informational tooltip intercepted a click on the next row. The subsequent fix adds `pointer-events: none` in both `static/admin_hub/hub.css` and `style-guide/admin/hub.css`, retaining focus visibility. A normal browser click failed before the fix and succeeded after it at the **same coordinate (1031, 467)**, opening the intended next row's history without a forced click. Post-fix review was **APPROVED**, with no critical or minor tooltip findings remaining.

The focused CSS regression report records **4 passed, 0 failed, 0 skipped**, focused ruff success and a clean diff check. The independent full run of **2767 passed, 0 failures/errors/skips on 2026-10-22** is historical and predates the tooltip fix.

**Final controller verification (2026-10-23, after the tooltip fix):** `uv run rtk pytest -q --junitxml=/tmp/opencode/fk-hub-acceptance-final-suite.xml` passed **2769** tests. The parent controller personally inspected the XML; parsed totals were **tests=2769, errors=0, failures=0, skipped=0, time=354.149s**. Full ruff, mypy, `makemigrations --check` and `diff --check` passed; mypy emitted existing notes only, with no errors. This is supplied controller evidence, not a test rerun by this documentation session. The pre-existing medical access-audit ordering issue remains unchanged and outside these acceptance fixes.

## Evidence index

These are **ephemeral local artifacts** under `/tmp/opencode/fk-hub-acceptance/`, not durable repository attachments. Raw reports may contain synthetic authentication details; they are referenced, not copied into the repository. No credentials or session material are included here.

| Report / trace | Representative screenshots under `screenshots/` |
|---|---|
| `slices23-report.md`; `artifacts/slices23-recovered.jsonl` | `s23-pdf-main-frame.png`, `s23-pdf-main-desktop.png`, `s23-image-transformed.png`, `s23-heic-error-region.png`, `s23-unknown-format.png`, `s23-phone-pdf.png`, `s23-phone-portrait.png` |
| Same preview/medical report | `s23-medical-initial-upload-ui.png`, `s23-medical-before-replaced-ui.png`, `s23-medical-after-approval-replace.png`, `s23-medical-viewer-tab.png`, `s23-medical-invalid-docx.png`, `s23-medical-missing-file.png`, `s23-perm-denied.png` |
| `slices14-report.md`; `artifacts/slices14-evidence.jsonl` | `s14-search-janis.png`, `s14-search-berzins.png`, `s14-search-reversed.png`, `s14-paging-page2.png`, `s14-corr-dialog-44-page1.png`, `s14-corr-dialog-44-page2.png`, `s14-corr-abort-error.png`, `s14-nojs-history.png`, `s14-cycle-history-after-resubmit.png` |
| `tooltip-fix-report.md` | `tooltip-before-intercept.png`, `tooltip-after-fix-focus-visible.png`, `tooltip-after-fix-click-works.png` |

## Remaining acceptance and rollout

- **NOT RUN:** Parent-browser OTP/login and resubmission; physical mobile/touch; non-Chromium/non-headless viewer behavior; production/deployed acceptance; authenticated tunnel acceptance; live SMTP/provider delivery.
- **Pending:** A separate deployment/milestone release decision and the unrun acceptance scope above. The full automated regression is complete; historical automated results remain historical.
- Before deployment enables tracked correction writes/UI, apply migration `0013` to the target database. The local disposable migration is not deployment evidence. Do not infer/backfill old emails; history begins at rollout and follows application CASCADE deletion rather than audit pruning.

## Documentation self-review

Case totals, simulations, browser versus service-driven steps, locale limits, MIME validation, artifact provenance and unrun checks are distinguished above. Plan checkboxes and milestone status reflect only this tested scope. This documentation update changes no code, tests, public interfaces, commits or deployment state.

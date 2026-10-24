# Admin Hub review actions — scoped local acceptance

**Date:** 2026-10-23
**Scope:** Authorized Units 2 and 3 of the [review-actions plan](../superpowers/plans/2026-10-23-admin-hub-review-actions.md) and [paired design](../superpowers/specs/2026-10-23-admin-hub-review-actions-design.md). Unit 1 remains an operator-only read-only lookup, not an executed production operation or a PDF product filter.

**Disposition:** Scoped local browser acceptance is complete, including genuine parent-browser resubmission and the acceptance-found mobile regression fix. Implementation and presentation-fix review are APPROVED after fixes. This is **not complete release sign-off**: authenticated tunnel acceptance is blocked; physical mobile, other browsers and production deployment are not run. Target migrations and rollout remain open.

## Evidence and environment

This report consolidates inspected execution reports, not a documentation-session browser or test rerun:

- `/tmp/opencode/fk-review-browser/artifacts/unit2-browser-report.md`
- `/tmp/opencode/fk-review-browser/artifacts/unit2-browser.jsonl` — 28 checks: **25 PASS, 1 BLOCKED, 2 NOTRUN**. The narrative table groups some checks; it is not a separate count.
- `/tmp/opencode/fk-review-browser/artifacts/unit3-browser-report.md` and `unit3-browser.jsonl` — initial **19 executed: 18 PASS, 1 FAIL**.
- `/tmp/opencode/fk-review-browser/artifacts/unit3-mobile-fix-report.md` — before/after measurements, normal interaction, focused checks and reviewer follow-up, including the owned-runtime restart proof.

These are **ephemeral `/tmp` artifacts**, not durable repository attachments. Associated screenshots and probes remain under `/tmp/opencode/fk-review-browser/`; filenames below identify synthetic acceptance fixtures only. No credentials, OTPs, cookies, CSRF values, private configuration or correspondence bodies are copied into this document.

The disposable PostgreSQL **18.6** database `fk_review_browser` ran on loopback port **55705**, with a separate temporary private-media directory and file-based captured email. Only this disposable database received `registrations/0014_applicationcorrectionmessage_resolution.py` and `core/0013_alter_auditevent_action.py`. The root default database remains intentionally unmigrated. OCR, agreement and invoice providers were stubbed; jobs were synchronous; invoice autosend and analytics were disabled. There was no live SMTP, provider or production operation.

Authenticated work used local app `http://127.0.0.1:42472`, headless **Chromium 155 via Playwriter**, genuine staff form login and genuine parent email-entry/OTP login. Controlled negative/replay requests used that browser session's real authentication and CSRF state; DB probes observed persisted effects. Seeded multi-status/history fixtures and the disposable deleted-resolver fixture are synthetic setup, not evidence that a browser generated those historical sends.

## Unit 2 — corrections and provenance

| Scenario | Observed result and method |
|---|---|
| Genuine request-fix and staff resolution | Normal cockpit request-fix created a sent history row and one captured email. Deliberate resolution returned `FIX_REQUESTED → SUBMITTED`, cleared review fields and rearmed the digest. DB probes confirmed `staff_manual`, resolver/time, unchanged send snapshot, one structurally redacted audit, no resolution email, no approval/member/agreement creation. |
| Send-state history | Browser/DB inspection preserved seeded pending, failed, sent and previously resolved rows. This inspection is not a claim that all seeded send states were generated or resolved through browser interaction; automated domain evidence separately covers all-status resolution. |
| Replay and zero history | Same-session replay left timestamps, digest, audit and email unchanged. Actual zero-history resolution recorded count zero without fabricated correspondence. |
| Security and state | Approved/rejected tamper requests failed with Latvian errors and no mutation; no-change staff saw no action and received 403 on forged POST; missing CSRF returned 403. Safe local `next` returned to the Hub. |
| Genuine parent resubmission | Browser submitted the email-entry form, obtained an OTP through **file-based local capture**, verified it normally, opened the owned workspace, advanced the wizard and submitted. No synthetic session or service-only submission substituted for this path. DB probes confirmed `parent_resubmission`, null staff resolver and the exact unchanged send-time snapshot; no staff-resolution audit was added. |
| Shared history | Dialog and standalone pages distinguished parent/staff source and requester/resolver, rendered zero history, and paged 20 + 1 synthetic rows. Deleting only the temporary resolver retained manual source/time and displayed the unavailable-staff placeholder. |

The original Unit 2 run did **not** exercise optional touch emulation or concurrent writers; authenticated tunnel work was BLOCKED. The later shared-CSS check covered cockpit layout at **390 and 320 px** and normal-tap opening of the resolve disclosure at 390 px, without submitting or changing state. It does not convert the original optional-touch NOTRUN into a full mobile workflow pass. Actual PostgreSQL concurrency tests are separate automated evidence, not browser acceptance.

Representative synthetic-fixture screenshots: `u2-a-request-fix-open.png`, `u2-a-cockpit-resolved.png`, `u2-c-register-entry.png`, `u2-c-otp-requested.png`, `u2-c-parent-review-step.png`, `u2-c-parent-submitted.png`, `u2-d-dialog-staff-manual.png`, `u2-d-standalone-parent-source.png`, `u2-d-dialog-paging-page2.png` (all under `screenshots/`). OTP values and captured email files are not repository evidence.

## Unit 3 — reject, document void and discontinuation

| Scenario | Observed result and method |
|---|---|
| Reject | Separate native reason disclosure; blank reason blocked. Actual submitted rejection produced one captured email, audit and no correction history. Draft/fix-requested/approved probes were denied without mutation; CSRF enforced. |
| Document-only void | Actual generated, sent and signed voids preserved active membership. Signed artifact metadata/hash and authenticated download remained intact; billing/invoices were unchanged. Sent void ran the existing archive stub. Replay produced no duplicate email/job/audit. Terminal controls and no-change denial were checked. |
| Zero-selection discontinuation | Actual confirmation ended signed/active membership with no selected invoices and no fabricated cancellation rows. Billing stayed unchanged; one captured email and lifecycle event were observed. Replay was blocked without duplicate effects. |
| Selection validation | Browser showed disabled paid/partial/unknown rows and explanations. Controlled date/reason/malformed/foreign/paid/partial/unknown-ID probes, including mixed valid/invalid selection, rolled back without invoice/member/agreement/email/job changes and displayed fixed Latvian errors. |
| Explicit mixed selection | Normal checkbox selection of disposable invoice IDs **3/4/5** cancelled exactly those rows: local, archive stub and cancel stub respectively. Selectable-but-unselected ID 6 and partial/paid/unknown IDs 7–9 remained unchanged; amounts did not change. Two synchronous stub jobs completed, one captured email and lifecycle metadata were observed; no credit adjustment was created. |
| Read-only outcomes | Persisted local/archive/cancel results rendered after discontinuation. `done` and Invoice Ninja completion labels here reflect **stub completion only**, not live external success. There is no global future-billing shutdown, refund or automatic-credit promise. |
| Keyboard/no-JS/redirects | Native disclosures, fields and button worked without JavaScript; keyboard reached controls. Safe/unsafe/absent `next` stayed local. These presentation probes did not submit an additional lifecycle mutation. |

### Historical U3-F failure and resolved regression

The initial report remains **18 PASS / 1 FAIL**, not silently rewritten as all-pass. At **390×844 touch emulation**, opening discontinuation widened the page to **720 px** and the fixed action bar intercepted taps. Evidence includes `u3-f-mobile-app21-open-overflow.png`, `u3-f-mobile-app21-tap.png` and `u3-f-mobile-app21-viewport.png`.

The subsequent presentation-only fix added labelled, keyboard-focusable internal-scroll wrappers around both new tables, scoped shrink/overflow rules and mobile bottom clearance. Narrow-screen header, signed-document tile and file-input wrapping removed remaining 320 px min-content overflow; the shared style-guide CSS mirrors the shipped CSS. No business writer, schema or selection semantics changed.

Normal, unforced taps/clicks at **320 and 390 px** then opened/closed both disclosures and reached checkbox/date/reason/empty-submit controls. Page width matched the viewport; wide tables scrolled internally by keyboard and touch. The read-only outcome table remained readable at both widths. Desktop **1280 px**, no-JS and Unit 2 cockpit checks passed. Empty submit triggered native required validation only; the signed/active negative fixture, invoices, captured-email/job counts and Unit 2 fixture stayed unchanged.

Initial after-fix proof used fresh read-only runtime **42473** because **42472** had cached templates. That secondary runtime was stopped. The owned **42472** app was subsequently restarted with the same isolated settings and served the latest fix: health 200, wrapper present, 390 px page width, normal-tap opening, internal scroll and empty-submit validation were recorded without data mutation. No unrelated runtime was restarted.

Representative synthetic-fixture follow-up screenshots: `u3-mobile-fixed-390-open.png`, `u3-mobile-fixed-320-open.png`, `u3-mobile-fixed-outcomes-390.png`, `u3-mobile-fixed-outcomes-320.png`, `u3-mobile-fixed-desktop.png`, `u3-mobile-fixed-u2-cockpit.png`, `u3-mobile-fixed-nojs.png`, `u3-mobile-fixed-restarted-42472.png`.

## Automated evidence and review chronology

- **Historical pre-mobile-fix controller gate:** PostgreSQL **2869 passed, 0 errors/failures/skips**, including actual concurrent staff/staff and staff/parent cases. Parent-inspected XML `/tmp/opencode/fk-review-actions-final-pg.xml`, time **482.075s**, used separate isolated database `fk_review_actions`, stub providers and locmem mail. Full ruff/mypy (notes only)/migration-consistency/diff checks passed at that stage. This is not the post-mobile-fix gate or the browser file-email runtime.
- **Presentation-fix engineer evidence:** Hub **413 passed**. After strengthening CSS tests to enforce the actual bounded mobile-media scope, focused agreement/CSS checks **34 passed**; focused ruff passed. Review APPROVED, including the minor test correction. The initial fix report's whole-tree diff warning was a pre-existing EOF issue, not a clean whole-tree check; do not infer a new final diff result from the focused check.
- **Current post-mobile-fix controller gate (2026-10-23):** The parent completed the full PostgreSQL suite and personally inspected `/tmp/opencode/fk-review-actions-browser-final-pg.xml`: **tests=2871, errors=0, failures=0, skipped=0, time=479.111s**, timestamp `2026-10-23T18:08:54.915291+03:00`. This documentation update also inspected the XML suite header. Full ruff, mypy, `makemigrations --check` and diff check passed according to the parent; mypy emitted only existing annotation notes. This is automated regression evidence after the reviewed mobile fix and strengthened media-block test, not additional browser cases or a browser rerun. The earlier 2869 and focused 413/34 remain historical evidence, not components to sum into this total. The final full diff check supersedes the earlier fix report's whole-tree warning.

## Remaining acceptance and rollout

- [x] Scoped local authenticated Units 2/3 workflows, including real parent OTP/wizard resubmission, history/security probes and explicit selected-invoice effects.
- [x] Acceptance-found mobile presentation regression resolved and reviewed; emulated 320/390, desktop, keyboard/no-JS and shared Unit 2 cockpit checks recorded with their limits.
- [x] Recorded the parent-completed, personally inspected post-mobile-fix PostgreSQL gate: 2871 tests, zero errors/failures/skips, 479.111s on 2026-10-23, with full ancillary checks passed. XML suite header inspected during this documentation update; no tests or browser scenarios rerun here.
- [ ] Authenticated tunnel acceptance: **BLOCKED**. Anonymous health returned 200, but native login POST lost the session cookie through the tunnel. This is a setup-smoke finding, not an established application-security defect or a claimed infrastructure fix. All authenticated acceptance here was local only.
- [ ] Physical mobile and other-browser acceptance: **NOT RUN**. Emulation is not device/browser coverage.
- [ ] Apply both migrations on the target before new resolution readers/writers/UI and verify deployment separately. Disposable migration success is not target rollout evidence.

All fixture mutations were limited to disposable acceptance data. This documentation update changes no application/test files, runtime configuration or databases and runs no tests. No live SMTP/provider effects, production lookup, production migration, deployment, commit, push or worktree operation occurred. Previous gap acceptance/report/spec/plan remain historical and untouched; their service-driven resubmission evidence is not retroactively relabelled as this genuine parent-browser run.

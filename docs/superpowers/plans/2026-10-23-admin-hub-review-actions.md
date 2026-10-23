# Admin Hub Review Actions Implementation Plan

> **For agentic workers:** The user has authorized implementation of Units 2 and 3; do not request approval again. Execute Tasks 2 onward with focused implementation and independent review checkpoints. Unit 1/Task 1 is completed operator documentation, not product implementation or permission to execute against production. Commit, push and deployment are not authorized.

**Goal:** Provide an operator-only PDF-permit lookup snippet, then implement truthful staff correction resolution and discoverable, distinct rejection/document-void/membership-discontinuation actions in the Admin Hub. No PDF product filter is in scope.

**Architecture:** The Hub derives presentation and submits mutations to existing registered Django admin endpoints. Registration services own the new correction transition; existing agreement and billing services remain the only lifecycle writers. Add resolution provenance rather than overloading email-send status or building a workflow engine.

**Tech Stack:** Existing Python/Django ORM, server-rendered templates, pytest/pytest-django, PostgreSQL, `uv`; no new dependency or provider.

**Date/status:** 2026-10-23 / Authorized Units 2 and 3 implemented and independently review APPROVED after fixes, including the strengthened mobile media-block test. Scoped local browser acceptance is complete: Unit 2 **25 PASS / 1 BLOCKED / 2 NOTRUN**, including genuine parent OTP/wizard resubmission; Unit 3 initially **18 PASS / 1 FAIL**, with the mobile regression subsequently fixed, normally tapped at 320/390 px and review-approved. Current parent-completed post-mobile-fix PostgreSQL gate: **2871 passed, 0 errors/failures/skips, 479.111s**, timestamp **2026-10-23**, personally inspected XML `/tmp/opencode/fk-review-actions-browser-final-pg.xml`. Full ruff/mypy/`makemigrations --check`/diff checks passed, only existing mypy annotation notes. Parent controller's **2869** PostgreSQL/concurrency suite and focused **413 Hub / 34 agreement/CSS** checks remain historical evidence. Automated verification is not new browser cases or a browser rerun. Authenticated tunnel, physical mobile/non-Chromium browsers and target migrations/deployment remain open. Unit 1 is documentation only, not executed. Original planning baseline: clean `dev` HEAD `a07bd58`; implementation/tests now contain intentional uncommitted changes. The earlier **2769 passed** belongs to the prior gap work. This docs-only session runs no application tests and makes no release-completion claim.

**Design and acceptance contract:** [Admin Hub review actions design](../specs/2026-10-23-admin-hub-review-actions-design.md). Its state tables, side-effect limits and explicit assumptions are normative. Prior gap-fix specs/plans remain untouched.

## Delivery map

| Unit | Responsibility | Dependencies |
|---|---|---|
| 1 | Operator-only read-only PDF lookup snippet; documentation complete, not executed | Existing runtime Python and MedicalPermit ORM; no product changes |
| 2 | Application-level correction resolution, provenance, audit and history | Additive registrations/core migrations before new readers/writers |
| 3 | Discoverable reject and independent document-void/discontinuation forms | Existing lifecycle/billing writers; no new schema |

The checked implementation, automated-verification and scoped local browser tasks below record delivered contracts and supplied executed evidence; unchecked tunnel/device/final-gate/target-rollout tasks remain open. Commands are retained for reproducibility, not as claims this documentation session executed them. Tests may be written alongside implementation; tests-first is not a prerequisite for executing this plan.

## Implementation evidence and review checkpoints

- **Unit 2 — APPROVED after fixes:** focused SQLite **164 passed, 2 PostgreSQL-only skips**; isolated PostgreSQL domain **56 passed, 0 skipped**; actual-overlap staff/staff and staff/parent concurrency pair **2 tests × 3 runs, no skips**; complete resolver module **14 PostgreSQL passed**. Added resolver/admin/migration tests and extended parent history, redirects and Hub history tests cover atomic rollback, immutable send snapshots, no-op side effects, nullable resolver, exact source, selective backfill/reversal and security boundaries. Review fixes preserve parent callers' original-instance status for analytics and establish real concurrent connections rather than SQLite lock inference.
- **Unit 3 — APPROVED after fixes:** focused **253 passed, 0 skipped** and Hub regression **411 passed**. Reject-error, lifecycle/admin, billing, agreement, Hub and family/native coverage exercise deliberate independent forms, state/security/redirect guards, actual document-only/repeat void, zero-selection discontinuation, selected-invoice outcomes and invalid/mixed-selection rollback. Review fixes preserve the read-only cancelled-invoice table after discontinuation and correct the service email docstring to match the existing after-inner-atomic call.
- Engineer ruff/mypy (**508 files**) and migration-no-change checks remain historical implementation evidence. **Historical pre-mobile-fix parent-controller evidence (2026-10-23):** full suite executed via `/tmp/opencode/run-fk-review-pg.py`, with `DATABASE_URL` fixed to loopback port **55705**, database `fk_review_actions`, `review_settings`, temporary private storage, stub providers and locmem mail. Parent inspected `/tmp/opencode/fk-review-actions-final-pg.xml`: **tests=2869, errors=0, failures=0, skipped=0, time=482.075s**. Actual concurrency cases ran without skips. Parent full ruff, mypy (notes only), migration-consistency and diff checks passed. This is supplied executed/inspected evidence, not a post-mobile-fix gate, docs-session rerun, sum of focused totals or substitution of the prior gap gate.
- **Scoped local browser acceptance:** [Evidence report](../../acceptance/2026-10-23-admin-hub-review-actions.md) consolidates the three inspected ephemeral `/tmp/opencode/fk-review-browser/artifacts/` reports and Unit 2's 28-check trace. Genuine staff and parent-browser workflows passed with file-captured email (not a synthetic session or service-only resubmission). Unit 3's initial mobile failure remains historical; the presentation-only table-scroll/clearance/wrapping fix passed normal 320/390 px, desktop, keyboard/no-JS and limited Unit 2 cockpit checks. Engineer Hub **413 passed**, strengthened agreement/CSS **34 passed**; fix review APPROVED after minor test correction. Latest owned app 42472 was restarted for cached templates and rechecked; secondary read-only 42473 was stopped. These checks made no further business mutations.
- **Current post-mobile-fix parent-controller evidence (2026-10-23):** Parent completed the full PostgreSQL run and personally inspected `/tmp/opencode/fk-review-actions-browser-final-pg.xml`: **tests=2871, errors=0, failures=0, skipped=0, time=479.111s**, timestamp `2026-10-23T18:08:54.915291+03:00`. The XML suite header was also inspected during this documentation update. Full ruff/mypy/`makemigrations --check`/diff checks passed according to the parent, with only existing mypy annotation notes. This supersedes the pre-mobile-fix gate as current automated evidence, not the historical browser result or targeted fix verification.
- **Open:** Authenticated tunnel acceptance is BLOCKED (anonymous health 200, native login POST loses session cookie); physical mobile, non-Chromium browsers and target migrations/deployment are NOT RUN. This setup finding is not a proven app-security defect or fixed infrastructure. Root default DB is intentionally unmigrated. No production lookup, migration, live mail/provider action, worktree, commit, push or deploy occurred; prior gap acceptance remains untouched and is not proof.

## Task 1 — Operator-only read-only PDF lookup (documentation complete)

- [x] Supply the manual snippet below; inspect model fields, cockpit route and runtime Python PATH. No application/test file or management command is needed. No production execution has occurred.

An operator may run this manually from the **production Compose directory**, replacing `web` with the actual application service name. The runtime image has `/app/.venv/bin/python` on PATH but no `uv` binary, so use container `python` directly:

```bash
docker compose exec -T web python manage.py shell <<'PY'
from django.db.models import Q
from apps.documents.models import MedicalPermit

q = (
    MedicalPermit.objects.exclude(file="")
    .filter(content_type__iexact="application/pdf")
    .filter(
        Q(original_filename__iendswith=".pdf")
        | Q(original_filename="", file__iendswith=".pdf")
    )
    .select_related("application")
    .order_by("application_id")
)
print("Matching PDF permit metadata:", q.count())
for permit in q.iterator():
    application = permit.application
    print(
        application.pk,
        application.member_full_name,
        permit.original_filename,
        f"/hub/pieteikumi/{application.pk}/",
        sep="\t",
    )
PY
```

This performs read-only ORM queries. Output contains application ID, child name, original filename and relative cockpit URL, not storage paths, personal IDs or contacts. It never opens file bytes, saves rows or invokes providers. Matching requires nonempty stored file metadata, case-insensitive exact declared MIME and suffix; a stored suffix is used only for an empty original filename. Parameterized MIME does not match. Validity, source, application state and member linkage are not filters. The count is metadata-based, not a magic-byte guarantee or storage-readability check. Treat output as private operational data.

**Product exclusion:** No PDF UI/filter, new queue parameter or change to `apps/admin_hub/queries.py` is planned. Preserve existing search/tab/count/pagination interfaces and the `Jālabo`/`FIX_REQUESTED` state filter, badge/history/cockpit links; mail `pending` is not that state. Unit 1 needs no browser acceptance or tests. Proceed to the already authorized Units 2 and 3 without another approval request; do not execute this snippet against production in this session.

## Task 2 — Resolution schema and historical provenance

**Modify:** `apps/registrations/models.py`, `apps/core/models.py`.

**Create at inspected baseline:**
- `apps/registrations/migrations/0014_applicationcorrectionmessage_resolution.py`
- `apps/core/migrations/0013_alter_auditevent_action.py`
- `tests/registrations/test_correction_resolution_migration.py`

- [x] Rechecked migration leaves; implemented registrations `0014_applicationcorrectionmessage_resolution` after 0013 and core `0013_alter_auditevent_action` after 0012. Existing migrations are unchanged.
- [x] Added `ApplicationCorrectionMessage.ResolutionSource` values empty, `parent_resubmission`, `staff_manual`; `resolution_source` is length 32 with blank/default empty; `resolved_by` is a nullable/blank AUTH_USER_MODEL FK, SET_NULL, related_name `+`. Model docstring distinguishes sender/resolver; original send fields and resolved_at remain.
- [x] Added `AuditEvent.Action.APPLICATION_CORRECTIONS_RESOLVED` / `application_corrections_resolved` with a choices-only core migration.
- [x] Added historical-model backfill after field creation: only nonnull resolved_at gets parent provenance; unresolved remains blank and resolving staff null. Swappable dependency and no-op data reverse preserve existing timestamps/content while schema reversal removes new provenance.
- [x] Added historical forward/reverse migration coverage in `test_correction_resolution_migration.py`, including resolved/unresolved send states, unchanged snapshots and restored leaves.
- [x] Verified migration/domain coverage under isolated PostgreSQL as part of the supplied Unit 2 evidence; no root/default or deployed database was migrated.
- [x] Reviewed dependencies, selective backfill and reversal boundary.

## Task 3 — Manual correction writer and admin action

**Modify:**
- `apps/registrations/services.py` — new `resolve_application_corrections(application, reviewer) -> RegistrationApplication`; parent final-write provenance/serialization.
- `apps/registrations/admin.py` — import service and add `resolve_corrections` branch in `review_action_view`.
- `tests/registrations/test_correction_message_history.py` — automatic parent provenance/rollback regressions.
- `tests/admin_hub/test_review_action_next_redirect.py` — safe-next regression coverage.

**Create:**
- `tests/registrations/test_resolve_application_corrections.py` — state machine, no-side-effect and concurrency tests.
- `tests/registrations/test_admin_resolve_corrections.py` — actual admin permission/method/CSRF/redirect behavior.

- [x] Implemented atomic fresh-row `select_for_update()` decisions and the design's four-row state table, including exact disallowed-state/inconsistent-history errors. The service returns the fresh instance for transition/no-op.
- [x] FIX_REQUESTED uses one `now`, resets submitted/review/digest fields and resolves only unresolved messages as staff_manual/reviewer. All send snapshots remain unchanged. Zero history creates no correspondence; no completeness gate, mail, analytics, signal, member or agreement is added.
- [x] Scheduled one structural fail-safe audit after commit for the real transition, with generic target label and exactly from_status/to_status/resolved_count/source. Repeated/concurrent no-op does not re-audit or reset timestamps/digest.
- [x] Parent submission retains pre-write validation, locks/rechecks final-write state and writes parent_resubmission with null resolving staff. A losing parent cannot overwrite manual provenance. Original-instance transition fields are refreshed and returned for existing analytics callers; regression coverage preserves this contract.
- [x] Added `resolve_corrections` under the existing admin change-permission/POST/CSRF boundary, fixed Latvian known-error mapping and safe-next redirects; unexpected errors remain observable. No Hub mutation URL was added.
- [x] Added all-status/multiple-attempt, zero-history, immutable snapshot, rollback, no-side-effect, rejected-state and no-op assertions, including commit-callback handling.
- [x] Added actual overlapping PostgreSQL staff/staff and staff/parent tests; supplied pair ran three times without skips. SQLite-only results are not lock proof.
- [x] Covered actual endpoint GET nonmutation, anonymous/nonstaff/no-change denial, enforced CSRF, safe/unsafe/scheme-relative/absent-next and unchanged invalid-path effects.
- [x] Ran focused coverage (supplied implementation evidence above; not a docs-session rerun):

  ```bash
  uv run pytest -q tests/registrations/test_resolve_application_corrections.py tests/registrations/test_admin_resolve_corrections.py tests/registrations/test_correction_message_history.py tests/admin_hub/test_review_action_next_redirect.py
  ```

  Expected: selected tests pass, including PostgreSQL lock cases and existing parent failure-persistence/rollback tests; inspect actual results.
- [x] Checkpoint: Unit 2 review APPROVED; atomicity, no-op, structural audit and separate parent provenance verified without changing delivery claims.

## Task 4 — Manual resolution discovery and shared history

**Modify:**
- `apps/admin_hub/views.py` — cockpit capability flag using registered admin permission helper.
- `apps/admin_hub/correction_messages.py` — `correction_history_page` joins resolving actor as well as sending actor.
- `templates/admin_hub/cockpit.html` — FIX_REQUESTED-only confirmation disclosure/form.
- `templates/admin_hub/_correction_messages.html` — source, timestamp and distinct resolving staff label.
- `tests/admin_hub/test_correction_messages.py` — shared dialog/no-JS markup and deleted-user behavior.
- `README.md`, `docs/audit-log.md` — workflow, provenance and audit catalog.

- [x] Derived FIX_REQUESTED/change-permission `can_resolve_corrections`; added standalone CSRF/safe-next native confirmation disclosure describing closure/return to review without approval/email/parent-response implication. Queue remains navigation-only.
- [x] History joins actor/resolved_by and renders separate source/time/resolver/requester in escaped shared fragment. Deleted resolving staff retains manual source/time with “Darbinieks vairs nav pieejams”; blank unresolved provenance remains truthful.
- [x] Extended history/cockpit tests for source, nullable/deleted resolver, immutable/escaped content, bounded queries, private/no-store GET, 20-row chronological pagination, dialog/no-JS markup, permission visibility and zero-history resolution.
- [x] Updated README workflow and audit metadata/retention docs without delivery or historical-send claims.
- [x] Focused history/JS/resolver checks included in supplied Unit 2 verification above.
- [x] Checkpoint: implementation/docs reconciled; scoped local browser evidence is recorded separately below. Authenticated tunnel/device coverage and migration-first target rollout remain open.

**Unit 2 browser acceptance (scoped local complete):** Genuine request-fix/manual resolution, replay, zero history, security/invalid-state/safe-next probes, parent email-entry/OTP/workspace wizard resubmission and shared provenance/paging/deleted-resolver views passed. The actual runtime used file-based captured email rather than planned locmem; providers stayed stubbed. Multi-status history included seeded rows and DB inspection, not browser-generated failed/pending sends. Exact send snapshots were unchanged and the parent resolver was null with source `parent_resubmission`. Original optional touch was NOTRUN; later shared-CSS cockpit 320/390 checks opened resolve at 390 without changing state. Actual concurrency is separate automated evidence. See the acceptance report for method attribution and open tunnel/device boundaries.

## Task 5 — Discoverable, deliberate rejection

**Modify:**
- `templates/admin_hub/cockpit.html` — independent request-fix/reject forms, visible secondary reject disclosure near primary actions.
- `apps/admin_hub/views.py` — submitted/change-permission reject flag.
- `apps/registrations/admin.py` — rejection branch's known-error mapping only.
- `tests/admin_hub/test_hub_cockpit.py` — discovery/no-JS/state/escaping tests.
- `tests/admin_hub/test_review_action_next_redirect.py` — preserve rejection success/error return behavior.

**Create:** `tests/registrations/test_admin_reject_errors.py` — endpoint state/note/error and security regressions.

- [x] Added permission/submitted-only native “Noraidīt” disclosure with impact, required review_message and deliberate confirmation; request-fix has its own form/note. Opening the disclosure does not reject.
- [x] Kept action=reject/service/email; mapped only known state/note errors, preserved unexpected exceptions, safe-next and native no-next behavior. No broader rejection state or correction-history write was added.
- [x] Covered valid/blank/stale rejection, security/CSRF/nonmutating GET, safe/unsafe/no-next, escaping, existing email and no correction-history creation; invalid paths leave effects unchanged.
- [x] Focused rejection coverage included in supplied Unit 3 checks above.
- [x] Checkpoint: discoverability remains separate from server validation; FIX_REQUESTED requires resolution before rejection.

## Task 6 — Separate document void and membership/billing discontinuation

**Modify:**
- `apps/registrations/admin_panels.py` — promote existing candidate helpers, keep existing native-admin consumer working.
- `apps/registrations/admin.py` — narrowly guard/parse/redirect discontinuation branch; leave void's global policy unchanged.
- `apps/admin_hub/views.py` — agreement capabilities, candidate/outcome data and minimal adjacent-control flags.
- `templates/admin_hub/agreement.html` — visible lifecycle panel with two independent forms, selected invoice outcomes and terminal-state controls.
- `apps/admin_hub/timeline.py` — correct outdated module description, preserve timeline interface.
- `tests/admin_hub/test_hub_agreement.py`, `tests/admin_hub/test_review_action_next_redirect.py`.
- `tests/registrations/test_admin_agreement_lifecycle.py` — actual guard/parse/rollback regressions.
- `tests/billing/test_discontinuation_adjustments.py` — preserve selected-invoice semantics.
- `tests/agreements/test_agreement_services.py` — document-only/repeat-void assertions if absent.
- `tests/admin_hub/test_family_hub_actions.py` — shared native/family behavior regression coverage.

- [x] Promoted and documented `discontinuation_candidates(member) -> list[BillingInvoice]` and `proposed_action_for_invoice(invoice: BillingInvoice) -> str`; updated native consumer. Hub uses the narrow helper, not the full review-context builder.
- [x] Derived permission/state flags from the current agreement for void/discontinue/regenerate; preserved private artifacts/history. Selectable candidates load when offered; cancelled outcome rows also load on discontinued agreement/member pages. No new writer/route was added.
- [x] Added independent native document-void/discontinuation disclosures, required Hub void reason and signed-document warning. Removed false credit claim; existing permissive shared void policy/email/archive/no-op is unchanged. These are not sequential steps.
- [x] Discontinuation posts date/reason/repeated selected_invoices/safe next, defaults none and warns zero selection changes no invoices. Candidate rows show amounts/dates/payment/external/cancellation/proposed states with disabled reasons. No global future-billing/refund/credit promise is made.
- [x] Existing dispatcher explicitly guards current plus signed/active before parsing/writing. Shared service/native/family policies remain; this adds no global lifecycle-lock guarantee.
- [x] Added fixed Latvian date/ID/known-domain error mapping with unexpected errors observable. Retained inner-atomic email call and on-commit invoice jobs; no outer dispatcher transaction was added.
- [x] All discontinuation outcomes use safe `_after_review_redirect`, preserving native no-next change-page return and unrelated branch behavior.
- [x] Gated regenerate/mark-sent and suppressed misleading terminal-state signing/plan controls without globally restricting shared void/signing-path policy or changing calculations.
- [x] Preserved timeline/badges and added a read-only persisted cancellation outcome table after discontinuation: cancellation time/action and local/pending/done/failed result. Rows are member-level cancelled candidates, not a new event-selection ledger. Enqueue is not remote completion; timeline docstring now reflects the actions.
- [x] Covered state/permission/form separation/no-JS markup, signed warning, real zero selection, document-only/replay void preservation and terminal/stale controls.
- [x] Covered real local/draft/sent selected cancellation, unselected invoices unchanged, lifecycle/notification/audit, commit callbacks, no automatic credit, invalid/mixed selection rollback and current/signed/active guards.
- [x] Covered safe/unsafe/no-next, no-change/anonymous/enforced CSRF and native/family regressions; stale discontinuation has no second effect. No new global void-reason validation was introduced.
- [x] Ran focused implementation verification (supplied evidence above):

  ```bash
  uv run pytest -q tests/admin_hub/test_hub_agreement.py tests/admin_hub/test_review_action_next_redirect.py tests/registrations/test_admin_agreement_lifecycle.py tests/billing/test_discontinuation_adjustments.py tests/agreements/test_agreement_services.py tests/admin_hub/test_family_hub_actions.py
  ```

- [x] Checkpoint: Unit 3 review APPROVED after fixes; writer boundaries, selection rollback, native behavior and independent lifecycle meanings verified. Existing service concurrency/email-policy limits are not silently broadened.

**Unit 3 browser acceptance (scoped local complete after fix):** Separate disposable cases exercised actual rejection, generated/sent/signed document void with artifact preservation, zero-selection and exactly selected local/draft/sent invoice discontinuation, disabled rows, tamper rollback, security/redirects and keyboard/no-JS controls. Captured file email and synchronous stub jobs established local effects only; persisted completed external labels are not live-provider proof. The initial 390 px overflow/tap FAIL remains in the original report. Presentation-only fix and reviewed media-boundary tests followed; normal 320/390 taps/internal scroll, desktop 1280, no-JS and current 42472 restart proof passed without new state changes. Physical devices, other browsers and authenticated tunnel remain open.

## Task 7 — Documentation, regression gate and isolated acceptance evidence

**Modify during implementation:** `README.md`, `docs/audit-log.md`, `docs/milestones.md`, affected inline API docstrings. Create `docs/acceptance/2026-10-23-admin-hub-review-actions.md` only when there is actual acceptance evidence to record; use the actual execution date if later and update links accordingly. Do not edit completed gap-fix design/plan documents.

- [x] Documented actual resolver/helper signatures, independent actions, no global future-billing promise, structural correction audit and existing reason-bearing discontinuation audit. No PDF product parameter/filter was added.
- [x] Prepared disposable PostgreSQL 18.6 `fk_review_browser` on loopback 55705, temporary private media, file-captured email (instead of locmem), stub providers, synchronous jobs and autosend/analytics disabled. Local authenticated Chromium 155 via Playwriter used app 42472; migrations were applied only there. Root live `.env`/default DB were not changed. No collation result is asserted from the three browser reports.
- [ ] Complete authenticated tunnel acceptance with matching origins: anonymous health 200 was insufficient; native login POST lost the session cookie. Keep this setup-smoke finding separate from application security and local acceptance.
- [x] Isolated PostgreSQL migration/domain coverage is supplied in Unit 2 evidence, including historical forward/reverse tests. This is not root/default or production migration evidence. Retained commands for future isolated browser setup:

  ```bash
  uv run python manage.py migrate
  uv run python manage.py showmigrations registrations core
  uv run python manage.py makemigrations --check
  ```

  Expected: new registrations/core migrations applied in isolated DB and no pending model changes. Rehearse forward/backward/forward there; never reverse production data as a test.
- [x] Focused automated checks completed with attributed totals in the evidence section; PostgreSQL concurrency checks ran without skips.
- [x] Captured parent controller's executed/inspected historical pre-mobile-fix gates on 2026-10-23: 2869 PostgreSQL tests passed with no errors/failures/skips; full ruff/mypy/migration-consistency/diff checks passed (mypy notes only). Exact wrapper, isolated configuration and XML/time are recorded above. Gate commands retained for reference:

  ```bash
  uv run pytest -q
  uv run ruff check .
  uv run mypy .
  uv run python manage.py makemigrations --check
  git diff --check
  ```

  Inspect actual exit codes, failure/error/skip totals and migration output. No target count is invented from the old 2769 baseline. Capture commit callbacks appropriately in tests; do not start real external jobs for regression verification. If graphify remains absent, record graph update as not applicable; do not generate a new graph for documentation.
- [x] Performed scoped local Units 2/3 browser scenarios and recorded actual versus seeded/stubbed effects, no-JS/keyboard behavior and genuine parent-browser OTP/wizard resubmission in the separate acceptance report. Original Unit 3 failure and later reviewed fix remain distinguishable. Unit 1 is documentation only, not a production execution task.
- [ ] Complete physical-mobile and other-browser checks; 320/390 emulated touch is not physical-device coverage and the limited Unit 2 cockpit smoke is not a full mobile workflow rerun.
- [x] Recorded parent-completed and personally inspected post-mobile-fix full PostgreSQL gate: 2871 tests, zero errors/failures/skips, 479.111s, timestamp 2026-10-23; full ruff/mypy/migration/diff checks passed (existing mypy annotation notes only). XML suite header inspected during this docs update. Historical 2869 and focused 413/34 remain separate; no browser rerun is claimed.
- [x] Recorded migration-first schema/backfill/audit order, no new env/dependency/worker, provenance-only schema reversal limits, application-CASCADE correspondence and existing audit pruning. Root default DB remains intentionally unmigrated; no production action occurred.
- [x] Updated only authorized follow-up status docs with delivered Units 2/3 and scoped local evidence. Prior gap acceptance/report/spec/plan remain untouched and are not proof or release sign-off.
- [x] Documentation self-review preserved documented interfaces, migration dependencies, structural metadata, redirects, nullable resolver semantics and persisted outcome limits. Context/Decision/Consequences remain populated in the paired design. PDF lookup remains operator documentation only. Current 2871 full gate, historical 2869 and focused 413/34 are attributed separately; tunnel/device checks and target rollout remain open.
- [ ] Apply resolution/audit migrations on the target before resolver readers/writers/UI and verify target rollout separately. Isolated test migrations are not deployment evidence; root default DB remains intentionally unmigrated and no production operations are authorized or performed.

## Documentation-session verification boundary

This update retains the inspected Unit 2/3 browser reports, Unit 2 trace and mobile-fix reviewer/restart addendum, preserving the prior source-reconciled interface contracts. The current automated gate records the parent's completed/personally inspected 2871-test result; this documentation update also inspected its XML suite header. It updates only the authorized acceptance report and follow-up status documentation. No application/test file, prior gap report/spec/plan, runtime database or environment file is changed. Tests and browsers are not rerun for this documentation-only update; supplied execution and review evidence is explicitly attributed. No graph rebuild is needed for documentation-only changes. Scoped local acceptance and the post-fix full automated gate are complete, not release sign-off: tunnel/device coverage and target migrations/deployment remain open. Root default DB remains intentionally unmigrated; no production operations occurred.

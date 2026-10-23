# Admin Hub review actions design

**Date:** 2026-10-23

**Status:** Authorized Units 2 and 3 are implemented and independently review APPROVED after fixes, including the strengthened mobile media-block test. [Scoped local acceptance](../../acceptance/2026-10-23-admin-hub-review-actions.md) includes genuine file-captured parent OTP/wizard resubmission: Unit 2 **25 PASS / 1 BLOCKED / 2 NOTRUN**; Unit 3 initially **18 PASS / 1 FAIL**, followed by a reviewed presentation-only mobile fix verified with normal 320/390 px interactions. Current parent-completed post-mobile-fix PostgreSQL gate: **2871 passed, 0 errors/failures/skips, 479.111s**, timestamp **2026-10-23**, personally inspected XML `/tmp/opencode/fk-review-actions-browser-final-pg.xml`. Full ruff/mypy/`makemigrations --check`/diff checks passed, only existing mypy annotation notes. The controller's **2869** pre-mobile-fix PostgreSQL/concurrency gate and focused **413 Hub / 34 agreement/CSS** passes remain historical. Automated verification is not new browser cases or a browser rerun. Authenticated tunnel acceptance is BLOCKED; physical mobile, non-Chromium browsers and target migrations/deployment remain open. Local stub/file-email evidence is not live delivery/provider proof or release sign-off. Unit 1 remains operator documentation only; production execution, commit, push and deployment are not authorized.

**Planning baseline:** Originally inspected clean `dev` HEAD `a07bd58`. The contracts below have now been reconciled against implemented source, migrations, admin dispatcher, Hub forms/history and persisted outcome rendering; the working checkout contains intentional uncommitted implementation and tests.

**Plan:** [Implementation plan](../plans/2026-10-23-admin-hub-review-actions.md)

## Context

This is a separate follow-up to the implemented Admin Hub gap slices. It does not reopen their scope, revise their completed design/plan, or close their outstanding acceptance and deployment work. Their recorded full-suite baseline is 2769 passed; that is historical evidence, not a test run for this change.

The Hub remains a read/presentation layer. Staff mutations go through the registered `RegistrationApplicationAdmin` endpoints and domain services. The queue already has name search, tab counts, pagination and correction summaries. `Jālabo` already means `RegistrationApplication.Status.FIX_REQUESTED`. Mail-history `pending` instead means an uncertain mail-backend outcome, not a new application state.

The cockpit already posts `reject` from a risk disclosure, but rejection is hard to discover and shares a note field with request-fix. The agreement page posts `void_agreement` while incorrectly claiming that voiding credits invoices. The existing domain has two different operations: document voiding and membership/billing discontinuation. Both belong in this follow-up, clearly separated.

## Decisions and alternatives

### Context

Staff need to find PDF permits, close corrections they have handled themselves, reject a submitted application deliberately, and choose between voiding a document and ending membership with explicitly selected invoice handling. Presentation alone cannot change the correction lifecycle or retain truthful resolution provenance.

### Decision

Keep three numbered units for stable references: (1) an operator-only read-only PDF-permit lookup snippet, (2) manual corrections lifecycle and history, and (3) destructive-action UX for reject, document void and membership/billing discontinuation. Only Units 2 and 3 require product implementation and are authorized. There is no PDF product filter, queue parameter or change to `apps/admin_hub/queries.py`. Reuse narrow existing writers and presenters; add only the missing application-level correction-resolution service and provenance fields. Keep all mutation routes in the existing admin.

Considered alternatives:

1. **UI-only links and badges:** lowest schema cost, but cannot atomically return `FIX_REQUESTED` to `SUBMITTED`, rearm the digest or distinguish staff resolution from a parent's response. Rejected for correction resolution; appropriate for clearer entry points to existing actions. PDF discovery is an operator lookup, not product UI.
2. **Narrow service plus existing admin writers (selected):** adds a small additive migration and one service while preserving domain ownership, native admin behavior and existing emails/jobs. Requires explicit state and history tests.
3. **General workflow/format/notification engine:** could model arbitrary transitions and formats, but introduces unrelated policy, permissions and retention machinery. Rejected as disproportionate.

### Consequences

Correction provenance requires migration-first rollout. Staff resolution intentionally bypasses parent submission completeness gates without approving anything. Destructive-action labels must describe actual selected effects, not promise global billing shutdown or automatic refunds. Existing lifecycle services stay authoritative; template flags are not authorization or validation boundaries.

## Scope and explicit routine assumptions

- There are no bulk actions, per-message resolution buttons, parent-portal redesign, new Hub mutation routes, document conversion, new providers or amount edits.
- The permit is the current one-to-one `MedicalPermit` linked through `application.medical_permit`, not an identity `Document` or a search through historical uploads.
- A PDF match is declared metadata, not byte inspection or proof that storage bytes are present/readable. Permit validity is independent; an expired PDF matches.
- Staff may resolve all unresolved attempts for one application, including failed/pending sends. Resolution does not change the recorded send outcome or assert that a parent acted.
- The action return target uses the existing validated `next`; no open redirect or secondary Hub writer is introduced.
- Document voiding and discontinuation are independent choices. Voiding first makes the agreement no longer signed, so discontinuation's signed-state precondition is no longer satisfied; they are not a two-step wizard. Copy must direct staff to discontinuation instead when their intent is to end membership.
- No new reason field is added for correction resolution. Document void requires a reason in the Hub UI only; the shared service's existing permissive reason policy is unchanged.

## Unit 1: Operator-only PDF lookup — documentation complete

Task 1 in the implementation plan supplies a short read-only ORM snippet for an operator to run manually from the production Compose directory, replacing `web` with the actual service name. Use `docker compose exec -T web python manage.py shell`, not `uv`: the runtime image places `/app/.venv/bin` on PATH but does not ship the `uv` binary. This documentation session does not execute it against production.

Query `MedicalPermit`, exclude `file=""`, require case-insensitive exact declared MIME `application/pdf`, and require a case-insensitive `.pdf` suffix on `original_filename`. Only when `original_filename == ""` may the stored file suffix supply the match. A nonempty wrong original suffix cannot fall back. Parameterized MIME does not match. Validity, source, application status and member linkage are not filters.

Use `select_related("application")`; print a count, application primary key, `application.member_full_name`, original filename and relative Hub cockpit URL. Never print storage paths, personal IDs or contacts; never open/read file bytes, save rows or invoke providers. The count describes matching metadata, not magic-byte validation or proof of readable storage. No code file or management command is needed.

There is no PDF UI/filter, new queue GET parameter, query-interface change or change to `apps/admin_hub/queries.py`. Preserve the existing `Jālabo`/`FIX_REQUESTED` state filter and awaiting-parent badge/history/cockpit navigation; mail `pending` is not an application state. Units 2 and 3 retain the manual return to review and both independent agreement actions below.

## Unit 2: Manual correction resolution

### Public service contract

`resolve_application_corrections(application, reviewer) -> RegistrationApplication` is implemented in `apps/registrations/services.py`. It is a staff action through the admin, not a parent resubmission shortcut. The dispatcher enforces change permission; the service owns the state transition. The service returns a fresh locked/persisted instance; unlike parent submission, it does not refresh the caller's original instance.

Inside `transaction.atomic()`, reread the application by primary key with `select_for_update()` and use that fresh row for every state decision. Return the fresh persisted instance. Use one `now` for the transition and history resolution.

| Fresh application state | Unresolved attempts | Result |
|---|---|---|
| `FIX_REQUESTED` | Any count, including zero | Transition and resolve all unresolved attempts |
| `SUBMITTED` | Zero | Idempotent no-op; no write, audit, digest reset or timestamp change |
| `SUBMITTED` | One or more | Reject; never silently close inconsistent old history |
| Any other state | Any | Reject without writes |

The real transition sets `status=SUBMITTED`, `submitted_at=now`, `review_message=""`, `reviewed_by=None`, `reviewed_at=None`, `submission_digest_sent_at=None`, and saves `updated_at`. It resolves every `resolved_at IS NULL` message regardless of `pending`, `failed` or `sent`. It does not rerun `_require_complete_application`, document/portrait/kit gates or upload validation: staff are explicitly closing corrections to an already submitted application. It creates no Member or Agreement, approves nothing, sends no email and emits no `application_submitted` analytics event.

Use stable service `ValueError` messages for `cannot resolve corrections in this application state` and `submitted application has unresolved corrections`. Map the first to “Labojumus var atzīmēt kā atrisinātus tikai pieteikumam statusā Jālabo.” and the second to “Iesniegtam pieteikumam ir neatrisināti labojumu pieprasījumi. Pārbaudiet pieteikuma stāvokli.” Do not catch unexpected errors as success. A pretracking `FIX_REQUESTED` row with no message history can transition; record a zero-count event and never fabricate correspondence.

### Provenance and migrations

Extend `ApplicationCorrectionMessage` without changing its send-time fields:

- `resolved_by`: nullable/blank FK to `settings.AUTH_USER_MODEL`, `on_delete=SET_NULL`, `related_name="+"`.
- `resolution_source`: blank-default CharField with `ResolutionSource` choices `""`, `parent_resubmission`, `staff_manual`; use length 32 and explicit Latvian display labels. Existing `resolved_at` remains.
- Staff resolution writes `resolved_at=now`, `resolution_source=staff_manual`, `resolved_by=reviewer` for unresolved rows only.
- Parent `submit_application(application, actor_account)` keeps its validation and automatic all-attempt resolution; its existing atomic update additionally sets `resolution_source=parent_resubmission`, `resolved_by=None`. Serialize its final state write against manual resolution by locking/rereading the application inside that transaction and rechecking the allowed draft/fix-requested state before saving. A parent request that loses to staff resolution must not overwrite provenance or rearm the digest again. Preserve the existing passed-instance mutation/return behavior: both immediate view callers ignore the return and read `application.status` for parent analytics after success. Refresh the original instance's transition fields after the locked write and return it; do not silently leave those callers with stale status. This compatibility requirement applies to the existing parent service, not the new staff service's fresh-instance return. Do not redesign unrelated review writers.
- Preserve original `status`, `body`, `subject`, `review_message`, `sent_at`, `created_at`, and sending `actor`, including for failed/pending rows and already resolved rows.

Implemented migrations are `registrations/0014_applicationcorrectionmessage_resolution.py` (schema additions, then historical-model `RunPython` backfill; dependencies on registrations 0013 and the swappable user model) and `core/0013_alter_auditevent_action.py` (choices only, depending on core 0012). Apply both before code/UI uses the resolver fields. The root default database remains intentionally unmigrated; isolated PostgreSQL migration evidence is not production rollout.

Backfill only rows with nonnull `resolved_at` to `parent_resubmission`, because `submit_application` is the only known prior resolver. Leave unresolved rows blank and every `resolved_by` null. There is no inferred send backfill. The data reverse is a no-op; normal reversal removes the added fields and their provenance. It must not clear pre-existing `resolved_at` or invent actors/timestamps. Use the swappable user dependency for the FK.

Add `AuditEvent.Action.APPLICATION_CORRECTIONS_RESOLVED` / `application_corrections_resolved`. Emit once per real transition, with actor and structural target id/type, a fixed generic `target_repr` (not the application's PII-bearing `__str__`), and metadata only `{from_status, to_status, resolved_count, source}` where source is `staff_manual`. Schedule the fail-safe audit call with `transaction.on_commit` from the locked transition so rollback cannot leave a success audit and a concurrent retry cannot double-audit. Audit failure keeps the existing fail-safe policy; do not claim guaranteed audit delivery. No note, subject, body, name, contact or provider data enters the new event metadata/target label. Existing audit retention and application-CASCADE correspondence deletion remain unchanged.

### Admin and Hub contract

Add `action=resolve_corrections` to the existing registered endpoint `admin:registrations_registrationapplication_review-action`, resolved as `/<object_id>/review-action/` under the model admin. Require the existing admin change permission, POST and CSRF protection; GET must never mutate. Success, no-op and expected state errors honor `_after_review_redirect(request, object_id)`.

In the cockpit, offer “Atzīmēt labojumus kā atrisinātus” only for `FIX_REQUESTED` with the registered application's change capability. A native disclosure explains: all outstanding requests will be closed by staff, the application returns to `Jāizskata`, no parent email is sent, and this is not approval. Post only after an explicit confirmation button. The queue provides discoverability through its existing status/helper/history/cockpit links, not a bulk or row-level mutation.

Extend `correction_history_page(application, raw_page)` to `select_related("actor", "resolved_by")`. Keep the signature, bounded pagination, ordering, escaped content and private/no-store GET contract. The shared `_correction_messages.html` fragment displays resolution source, timestamp and resolving staff when available in both dialog and no-JS page. Label parent resolution as parent resubmission, never staff approval. After deletion of the resolving user, retain `staff_manual` and the timestamp and show “Darbinieks vairs nav pieejams”; do not relabel it as a parent response. Unresolved blank-source rows remain unresolved; sending actor and resolving actor are distinct labels. Do not add a durable actor-name snapshot.

## Unit 3: Destructive lifecycle UX

### Rejection

Keep `reject_application(application, reviewer, message) -> RegistrationApplication` and its current rule: `SUBMITTED` only, nonblank message. `FIX_REQUESTED` must first be manually resolved back to review; no new rejected transition from approved/fix-requested is introduced.

Place a visible secondary “Noraidīt” entry near the primary cockpit review actions. Use a native `<details>` with a clearly named summary/confirmation section and required reason, separate from request-fix's form and text. It must work without JavaScript and present the impact before the actual POST button. Opening the disclosure does not reject; confirmation is UX, not a security boundary. Submit `action=reject`, `review_message` and safe `next` to the existing endpoint. Hide/disable the entry outside submitted state and without change permission; server checks still apply.

Repair only the rejection branch's misleading error mapping. Map `can only reject submitted application` to “Noraidīt var tikai iesniegtu pieteikumu.” and `reject message is required` to “Noraidīšanas ziņojums ir obligāts.” Re-raise unexpected `ValueError` rather than disguising it as a missing note. Preserve existing success/no-next changelist behavior and error/no-next change-page behavior. Keep the rejection email content/recipient and exclusion from correction history unchanged; escape reason text wherever displayed.

### Two independent agreement actions

Replace the misleading risk tray with a visible, state-aware lifecycle panel. Use separate native disclosures/forms and impact summaries for the following actions. Derive capability flags in `apps/admin_hub/views.py` using the existing registered-admin permission helper and fresh domain state; a new abstraction/file is not needed for a few flags.

| Action | Hub offer condition | Existing POST fields/writer |
|---|---|---|
| “Anulēt līguma dokumentu” | Current agreement in generated/sent/signed state and change permission | `action=void_agreement`, `void_reason`, `next`; `void_agreement(agreement, actor, reason) -> Agreement` |
| “Pārtraukt dalību un norēķinus” | Current signed agreement, linked active member and change permission | `action=discontinue_member`, `effective_date`, `reason`, repeated `selected_invoices`, `next`; `discontinue_agreement(agreement, actor, effective_date, reason, selected_invoice_ids: list[int]) -> Agreement` |
| Regenerate | Current void agreement and change permission | Existing `regenerate_agreement` action and service |

**Document-only void:** Explain that history, `is_current`, `external_id`, and the signed artifact are preserved; member status and all invoice/billing amounts and states remain unchanged. The existing parent void email and DocuSeal archive job remain; no new tracking/email is introduced. Require a nonblank reason through the Hub input's UI validation and warn explicitly before confirming a signed document: this does not end membership or cancel invoices. Do not globally tighten `void_agreement`'s shared reason/state policy or break native/family admin callers. It currently permits any non-void state and no-ops on void; forged/stale requests continue to follow that authoritative behavior. The Hub does not offer void on void/superseded/discontinued history. Do not claim that hidden controls globally forbid a forged terminal-state void.

Gate adjacent controls minimally: regenerate only on void; mark-sent only where its existing generated-state guard accepts it; do not show actionable signing/billing-setup controls for void/discontinued/superseded states. Preserve artifact/history access and avoid a broad template rewrite or changes to signing calculations. These presentation corrections are not new global lifecycle restrictions.

**Discontinuation:** Require ISO date `effective_date`, a nonblank `reason`, and an explicit selection of this member's existing `BillingInvoice` primary keys. Start with none selected. A visible warning must state that zero selection changes no invoices, even though membership ends. Never default to all invoices, use the effective date to invent a scheduler cutoff, or claim that all future invoicing stops.

The shared public helpers are `discontinuation_candidates(member) -> list[BillingInvoice]` and `proposed_action_for_invoice(invoice: BillingInvoice) -> str` in `apps/registrations/admin_panels.py`; the native-admin consumer uses the promoted names too. The Hub calls the narrow candidate helper, not `build_review_context`. Candidate rows carry `proposed_action`, `selectable`, `selectable_reason`, `cancellation_action_label`, `cancellation_status_label` and `cancellation_outcome`. This remains presentation-only: invoice ownership and allowed operations stay in billing services.

Render due date, amount/currency, payment status, external status, cancellation state and proposed outcome. Paid/partial rows are disabled with a manual-Invoice-Ninja explanation; unclear/previously cancelled rows are nonselectable with an explanation, without pretending that presentation is validation. `create_discontinuation_adjustments(member, event, invoice_ids, reason: str)` remains the writer's validation and handles only selected invoices:

- Unpushed and unsent: cancel locally.
- Invoice Ninja draft (`created`): cancel locally and queue archive after commit.
- Invoice Ninja sent/unpaid (`sent`): cancel locally and queue external cancel after commit.
- Paid/partial, foreign/unknown IDs or unclear external state: reject the whole operation without partial mutation.

There is no automatic refund or credit application. The existing credit-note/manual-apply policy is unchanged; ordinary unpaid discontinuation returns no new credit adjustments. No amount can be edited in this form.

### Writer guards and redirects

`review_action_view` loads the current agreement with `get_current_agreement(application.approved_member)`. Its `_signed_active_agreement(request, application, agreement) -> bool` checks linked member, signed state and active member, but does not independently test `is_current`. In the `discontinue_member` branch only, require the resolved agreement's `is_current` and reuse this guard before parsing or calling the service. The current lookup plus explicit flag establishes current ownership; the helper supplies signed/active validation on the server. Reject stale/forged noncurrent/unsigned/inactive requests before writes. Do not rely on the template flags or add a second Hub writer.

This narrow dispatcher guard is selected instead of globally tightening `discontinue_agreement`: the family admin also calls that service, and only signed state is currently checked there. This task does not rewrite all callers' lifecycle/concurrency policies. It also does not promise a new concurrency guarantee for pre-existing discontinuation writers. Manual correction retries, by contrast, have the explicit row-lock contract above.

Within **only** the discontinuation branch, change every return (missing agreement, guard failure, missing fields, invalid date/IDs, billing/state rejection and success) to `_after_review_redirect`. Without `next`, this still returns to native admin change view. Reject malformed invoice IDs with “Nederīga rēķinu atlase.”, invalid dates with “Nederīgs spēkā stāšanās datums.”, foreign/unknown selection with “Atlasē ir šim biedram nepiederīgi vai nezināmi rēķini.”, and unclear invoice state with “Atlasītā rēķina stāvoklis neļauj to apstrādāt. Pārbaudiet to Invoice Ninja.” Use the existing signed/active guard's Latvian message for signed/current/active state failures. Paid/partial selection uses “Apmaksāts vai daļēji apmaksāts rēķins jāapstrādā manuāli Invoice Ninja.” Missing date/reason keeps “Norādiet spēkā stāšanās datumu un iemeslu.” Map known domain errors; unexpected exceptions must remain observable, never reported as success or raw provider text in the UI. Keep unsafe/external `next` rejection.

Existing state/member/billing transaction, lifecycle event, parent notification and audit behavior remain. The service docstring was corrected to match implementation: the parent email is called after its inner `atomic()` block, not through `on_commit`; invoice archive/cancel jobs use `on_commit`. This is not a stronger outer-transaction email guarantee, and the dispatcher adds no outer transaction. The pre-existing discontinuation audit includes reason text; this scope does not broaden or relabel that as newly redacted. Only the new correction-resolution event has the strict structural metadata contract.

After a successful lifecycle POST, existing state badges and `build_agreement_timeline(agreement)` show persisted lifecycle state. The discontinued agreement/member page keeps a read-only cancelled-invoice outcome table: invoice, amount/currency, due date, cancellation timestamp, action, status and result. It reads stored cancellation fields and distinguishes local completion, external pending, done and failed; queued archive/cancel is never rendered as completed remote work. The table filters the member's candidate rows by nonnull `cancelled_at`, not by a new event-selection ledger, so it is not proof that each displayed row belongs to the latest discontinuation. The timeline description now reflects these actions without inventing events.

## Verification and acceptance

The implementation plan defines exact file ownership and focused commands. Test design covers each boundary, not only rendered buttons:

- **Operator lookup:** inspect the snippet against current model fields and runtime command; no production execution or PDF queue tests are part of this documentation-only unit.
- **Corrections:** all send statuses; several unresolved and previously resolved attempts; zero-history pretracking row; every disallowed state; submitted no-op versus inconsistent submitted history; atomic rollback; immutable email snapshots; deletion of resolving user; provenance backfill/reversal; concurrent PostgreSQL retry with one transition/audit; parent resolution unchanged except truthful provenance and serialized final write; no mail/analytics/member/agreement creation.
- **Destructive actions:** valid/blank rejection, stale state, escaped text, unchanged email/history exclusion; signed/generated/sent document-only void, repeat void with no duplicate email/job, preserved artifacts/ids/billing/member; discontinuation zero selection and each selected unpaid outcome; paid/partial/foreign/unknown/malformed selection and date failures with full rollback; actual server current/signed/active checks; safe/unsafe/no-next redirects, anonymous/no-change denial and enforced CSRF; native/family-admin regression coverage.

Run full `uv run pytest -q`, `uv run ruff check .`, `uv run mypy .`, `uv run python manage.py makemigrations --check` and `git diff --check` after implementation. Do not invent an expected new test count or call skipped tests passed. Browser acceptance uses an isolated PostgreSQL database, private temporary files, locmem email and stub providers, including real PDF fixtures, no-JS disclosures/history, keyboard/touch navigation and a genuine parent-browser resubmission. Expose user-accessible acceptance through the configured authenticated tunnel with matching origins; record browser/environment limitations rather than inferring release sign-off. No live email, provider mutation or deployment is needed for this acceptance.

## Rollout and documentation

Apply both new migrations before starting code that reads/writes resolution provenance and before enabling its UI. Unit 1 is operator documentation only; Unit 3 adds no schema. No new environment settings, dependencies, schedules or workers are required. Schema reversal loses new provenance fields only; it is not a rollback of membership/invoice business operations.

README, the separate follow-up milestone, plan/status and small AGENTS entry now link the separate scoped local acceptance report; the existing audit guide and public resolver/helper contracts remain unchanged by this documentation update. The report distinguishes actual browser mutations, controlled authenticated requests, seeded history and DB observations. Browser email was file-captured, not locmem; providers were stubbed and migrations applied only to disposable `fk_review_browser`. The original U3-F mobile failure remains historical; the reviewed fix bounds both tables with labelled focusable scroll regions and scoped mobile geometry/clearance, without changing lifecycle semantics. Normal 320/390 px, desktop 1280, keyboard/no-JS and limited Unit 2 cockpit checks passed. Cached-template discovery required restarting owned app 42472; fresh read-only 42473 was stopped. No further business mutations were made by those presentation checks.

The plan retains historical pre-mobile-fix controller evidence: `/tmp/opencode/run-fk-review-pg.py` against loopback 55705/database `fk_review_actions`, `review_settings`, temporary private storage, stub providers and locmem mail; inspected XML `/tmp/opencode/fk-review-actions-final-pg.xml` reports tests=2869/errors=0/failures=0/skipped=0/time=482.075s, with ancillary gates passed. Focused engineer 413/34 passes remain historical; mobile-fix review APPROVED includes the strengthened media-block test. Current parent-completed/personally inspected XML `/tmp/opencode/fk-review-actions-browser-final-pg.xml` reports **tests=2871/errors=0/failures=0/skipped=0/time=479.111s**, timestamp `2026-10-23T18:08:54.915291+03:00`; full ruff/mypy/`makemigrations --check`/diff checks passed, only existing mypy annotation notes. This documentation update inspected the XML suite header, not a new test or browser run. Authenticated tunnel is blocked after anonymous health 200 but loss of the session cookie on native POST, a setup finding rather than proven application-security defect or claimed infrastructure fix. Physical mobile, non-Chromium browsers and target rollout remain open. This documentation-only pass runs no tests and changes no application/tests/runtime; root default DB and prior gap report/spec/plan remain untouched. No production lookup, live effects, worktree, commit, push or deployment occurred. No complete release sign-off is claimed.

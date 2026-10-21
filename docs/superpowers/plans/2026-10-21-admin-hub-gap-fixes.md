# Admin Hub Gap Fixes Implementation Plan

> **For agentic workers:** Use the executing-plans skill for future implementation. Steps use checkbox syntax for tracking. This turn authorizes planning documentation only: do not implement, commit, or treat this plan as execution approval.

**Goal:** Close four Admin Hub gaps through independently shippable application search, native previews, medical uploads, and correction-request history.

**Architecture:** Keep the Hub a staff-only read/presentation layer whose mutations use existing Django admin endpoints. Reuse medical services and protected file proxies; add one registrations-owned history model solely for existing `request_fix` emails. No general messaging platform, resend, or file conversion is introduced.

**Tech stack:** Existing Django ORM/templates, plain JavaScript/CSS, private storage, pytest/pytest-django, `uv`, ruff, and mypy; no new dependency is expected.

**Design:** [Admin Hub gap fixes](../specs/2026-10-21-admin-hub-gap-fixes-design.md)

---

## Execution boundaries

- Recommended order: search, previews, medical uploads, correction history. Each slice can ship independently; tasks within correction history form one coherent slice.
- No new outbound message types. Track correction requests only, excluding approval/rejection, OTP, agreement, billing, and informational messages.
- No resend/retry system, conversion engine, provider monitoring, inferred historical messages, or unrelated refactoring.
- Keep source inspection proportional. Read immediate callers and existing tests before each change. Do not assume Guardian has a `full_name` column or MedicalPermit is a Document.
- Use focused tests as each behavior changes; mandatory test-first sequencing is not imposed. Do not add commits or execution approval gates to this plan.
- Update changed interfaces' docstrings and relevant README workflow notes during implementation. Preserve all unrelated documentation and code.

## File map

| Slice | Files and responsibility |
|---|---|
| Search | `apps/admin_hub/queries.py`: normalization/filtering/counts; `apps/admin_hub/views.py`: GET wiring; `templates/admin_hub/queue.html`: form/navigation/empty state; `static/admin_hub/hub.css`: minimal layout. |
| Previews | `templates/admin_hub/_viewer.html`, `static/admin_hub/viewer.js`, `static/admin_hub/hub.css`: bounded-format rendering, fallback, active-tab selection and controls. Inspect `apps/documents/services.py` and `apps/documents/views.py` for response behavior; change only a demonstrated trusted-PDF response blocker. |
| Medical | `apps/admin_hub/views.py`, `templates/admin_hub/cockpit.html`, `templates/admin_hub/_viewer.html`: permit context/form and explicit proxy URL adapter; `apps/registrations/admin.py`: upload-branch redirects only. Existing `apps/documents/medical_permits.py` owns rules and stays unchanged unless a focused regression proves a required fix. |
| History persistence | `apps/registrations/models.py`, next generated registrations migration, `apps/registrations/services.py`: model, send snapshots/outcomes and resolution. |
| History presentation | Create `apps/admin_hub/correction_messages.py`, `templates/admin_hub/_correction_messages.html`, `static/admin_hub/correction_messages.js`; modify `apps/admin_hub/queries.py`, `apps/admin_hub/views.py`, `apps/admin_hub/urls.py`, `templates/admin_hub/queue.html`, `templates/admin_hub/cockpit.html`, and `static/admin_hub/hub.css` for summaries and on-demand history. Load the script through the existing template script blocks. |
| Documentation | `README.md`: relevant Hub workflow notes; `docs/milestones.md`: evidence-based per-slice status; these design/plan documents: reconcile any actual contract changes. |

## Task 1 — Search contract and queue UI (slice 1)

- [ ] Read `queries.py`, `queue_view`, `queue.html`, Guardian fields in `apps/members/models.py`, and `tests/admin_hub/test_hub_queue.py`.
- [ ] Add `normalize_search(raw: str | None) -> str`: whitespace strip/collapse, then 200-character cap. Extend `_tab_queryset(tab: str, *, q: str = "")`, `queue_page(tab: str, page_number: Any, *, q: str = "")`, and `tab_counts(*, q: str = "")` without changing return shapes. Normalize inside the query boundary and document the contracts.
- [ ] Apply AND-token/OR-field `icontains` filtering over `member_full_name`, `guardian__first_name`, and `guardian__family_name` before counts and pagination. Keep child matches when guardian is null. Retain current tab predicates/order, 25-row pages, and invalid-page fallback.
- [ ] Wire normalized GET `q` through the view to both queries and template. Add a labeled search form and clear control. Encode the query in tab/page links; form submission, clear, and tab switches reset page 1. Preserve query text and distinguish no matches from an empty unfiltered tab. Do not add analytics/logging of search strings.
- [ ] Extend `tests/admin_hub/test_hub_queue.py` with child-name partial match; guardian first/family and reversed token order; tokens split across child/guardian; absent guardian; extra whitespace; blank query; overlong query; no match; punctuation/URL encoding; count/list parity across tabs; pagination and page reset; existing staff gate. Include mixed-case ASCII matching and exact Latvian Unicode names without assuming SQLite performs Latvian case folding.
- [ ] Run `uv run pytest -q tests/admin_hub/test_hub_queue.py`. Expect all selected tests to pass; inspect failures instead of weakening the filter contract.
- [ ] Manually search child and guardian names, navigate tabs/pages, and clear the query. Check Latvian case behavior separately on PostgreSQL and record database/collation limitations accurately.

**Slice acceptance:** The selected tab, tab counts, and pagination operate on one normalized query, with no scope expansion to invoices or families. No migration is generated.

## Task 2 — Safe native previews (slice 2)

- [ ] Read `_viewer.html`, `viewer.js`, relevant `hub.css` rules, `build_doc_panel`/`doc_preview_kind` in `apps/registrations/admin_panels.py`, and existing cockpit/viewer tests in `tests/admin_hub/test_hub_cockpit.py`. Inspect actual private response MIME, disposition, and frame headers through `apps/documents/services.py`/`views.py`.
- [ ] Render the existing `pdf` classification using a titled native iframe/object. Keep open/download fallback available regardless of embedded rendering. Never assign `data-viewer-doc` to a PDF. Retain the shared extension classifier and current upload allowlists.
- [ ] Keep JPEG/PNG/WebP image behavior; add a visible escaped fallback on image error, including unsupported HEIC. Do not add conversion or inline arbitrary HTML/SVG/office formats. Keep unknown-format open/download behavior.
- [ ] Select the first available document in server markup and JS initialization. Show a deliberate empty state when all are missing. Preserve active-tab toolbar URL synchronization. Disable image controls and keyboard transforms for PDF, unknown, missing, or failed images; do not show a misleading active zoom value.
- [ ] Only if a response test demonstrates a blocker, narrowly fix trusted PDF MIME/disposition/frame behavior. Cover that exact change with document response tests; leave unsafe content non-embedded and authorization/audit intact.
- [ ] Extend `tests/admin_hub/test_hub_cockpit.py` for PDF markup/title/fallback, no image-transform hook on PDF, all existing tabs (including child-ID back), first-missing/next-available and all-missing states, correct tab URLs, image-error fallback, and no unsafe embedding. Add focused response assertions to the existing relevant document test module if its builder changes.
- [ ] Run `uv run pytest -q tests/admin_hub/test_hub_cockpit.py tests/documents`. Expect selected tests to pass. Static/template assertions do not replace browser verification of JS controls.
- [ ] Open an actual multi-page PDF on desktop and mobile; exercise fallback where native rendering is unavailable. Switch image/PDF tabs, rotate/zoom/fit images, check keyboard shortcuts, force a failed HEIC/image load, and verify current-file links and disabled controls.

**Slice acceptance:** Supported native formats work without conversion; unsupported files remain usable through authorized fallback. Private authorization/audit is unchanged. No migration or dependency is generated.

## Task 3 — Medical upload adapter (slice 3)

- [ ] Read `upload_application_medical_permit`, `medical_permit_status`, the MedicalPermit model, the `medical_permit_upload` admin action, `_validated_next`/`_after_review_redirect`, medical proxy views/routes, and existing permit tests before wiring UI.
- [ ] Add cockpit context for permit status/date/file and upload capability consistent with the existing admin change permission. Add a standalone multipart CSRF form posting `action=medical_permit_upload`, `medical_permit_file`, and `next=<cockpit URL>` to `admin:registrations_registrationapplication_review-action`. Label accepted formats and the 25 MiB maximum. Do not add confirmation controls or OCR.
- [ ] Replace the three `_change_redirect` returns in that upload branch (missing file, ValueError, success) with `_after_review_redirect(request, object_id)`. Keep validation, service call, messages, authorization, unsafe-next rejection, and no-next fallback unchanged. Do not change confirm/clear-confirm branches.
- [ ] Adapt all existing Hub viewer panels to explicit resolved `preview_url` and `download_url` while retaining `active` and `preview_kind`. Build Document URLs at the Hub adapter boundary without changing other `build_doc_panel` consumers. Add a medical tab only for a real file, using `registrations:medical-permit-preview`/`medical-permit-download` with the permit ID. A confirmation-only row has status/date but no file tab. Retain all four original document tabs.
- [ ] Extend `tests/admin_hub/test_hub_cockpit.py` and `test_review_action_next_redirect.py`: form action/enctype/CSRF/field names; initial upload; replacement; missing file; oversized file; MIME/extension mismatch; valid next on success/error; unsafe next rejection; no-next admin fallback; no-change-permission denial; approved-member linkage; confirmation-only display; correct permit versus Document proxy URLs.
- [ ] Reuse and, where needed, extend `tests/documents/test_medical_permit_services.py`, `test_medical_permit_access.py`, and `test_medical_permit_admin.py` to pin safe replacement, confirmation clearing, N→30 September N+1 validity, and redacted audit metadata. Do not duplicate service rules in the Hub.
- [ ] Run `uv run pytest -q tests/admin_hub/test_hub_cockpit.py tests/admin_hub/test_review_action_next_redirect.py tests/documents`. Expect selected tests to pass.
- [ ] Manually upload and replace a PDF/image before and after approval. Check status/date, preview/download, failed upload preservation, localized messages, and return to the cockpit on success and validation errors.

**Slice acceptance:** Staff can upload/replace from the Hub using the existing writer; errors do not strand them in admin. Existing permit rules, privacy and audits remain intact. No migration is generated.

## Task 4 — Correction history model and send lifecycle (slice 4, domain)

- [ ] Read `request_application_fix`, `_render_and_send_notification`, `submit_application`, immediate admin callers and registration email tests. Confirm no caller wraps the outbound send in a transaction that would discard failed history. Inspect current migration leaves; `0012_submission_digest_settings.py` is the inspected baseline, not a reserved next number.
- [ ] Add `ApplicationCorrectionMessage` exactly as specified in the design: application CASCADE/reverse `correction_messages`; nullable actor SET_NULL; created/sent/resolved timestamps; text subject/body/review-note snapshots; pending/sent/failed choices; application+created index; stable chronological ordering. Do not add editable admin CRUD, recipient/provider snapshots, exception storage, or a mutable general timestamp.
- [ ] Generate the single additive model migration with `uv run python manage.py makemigrations registrations`. Inspect its dependencies and operations; include no unrelated schema changes and no data backfill.
- [ ] Preserve public service signatures. Add only optional keyword `correction_actor=None` to the private mail helper; supply the reviewer from request-fix. Track solely the request-fix template. Render once, persist pending before sending, and reuse that exact subject/body for the outgoing message. Save `sent`/`sent_at` only on return 1; return 0 records failed without adding a new exception; exceptions record failed then re-raise. Preserve all other message paths and existing application/audit failure semantics.
- [ ] Do not wrap SMTP and history in an atomic block. Document that interruption/outcome-write failure can leave pending after possible mail acceptance; do not automatically retry, recover by inference, or claim exactly-once sending.
- [ ] In `submit_application`, after validation, place submitted-status/review-reset saves and resolution of all unresolved history rows inside one small DB transaction. Set `resolved_at` for pending/failed/sent rows alike. Keep draft saves and failed submission from resolving anything. Include no SMTP in this transaction.
- [ ] Create `tests/registrations/test_correction_message_history.py`. Cover exact outgoing snapshot, stripped note, actor, return 1/0/exception, pending uncertainty, failed-history persistence after exception (using transaction-aware coverage where needed), unchanged public return values, repeated correction cycles, successful resolution, failed validation/draft save, rollback of resolution with submission save failure, application cascade, actor deletion, and exclusion of every other notification path. Use existing `patch`/`monkeypatch` conventions; never real SMTP.
- [ ] Run `uv run pytest -q tests/registrations/test_correction_message_history.py tests/registrations/test_review_action_emails.py`. Expect selected tests to pass. Check that failure tests verify persisted database state, not only mock calls.

**Domain acceptance:** Every newly attempted correction email has an honest send-time record; failed/pending attempts are not represented as sent, and resubmission preserves content while resolving the request lifecycle. There is no invented historical data.

## Task 5 — Correction summaries and accessible history (slice 4, Hub)

- [ ] Create `apps/admin_hub/correction_messages.py` as the sole Hub summary/history presenter. Define `correction_summaries(application_ids: list[int]) -> dict[int, dict[str, object]]` with each summary containing `sent_count`, `latest_status`, `latest_created_at`, `latest_sent_at`, and `has_history`; no full body/note fields. Compute awaiting-parent independently from application `fix_requested` in row/detail assembly. Fetch summaries for the current queue page in a bounded batch/annotations; do not query history in `_build_row` per application.
- [ ] Extend `QueueRow` with its correction summary and use the same presenter in the cockpit. Include no full history in queue HTML or hidden attributes. Show sent count, latest failed/pending warning, and separate awaiting-parent state; never count failures as sends. With no history use `Nav reģistrētas ziņas` plus explicit pre-tracking uncertainty.
- [ ] Add `correction_messages_view(request, pk: int)` and route `/hub/pieteikumi/<pk>/zinojumi/` named `admin_hub:correction-messages`. Require active staff and GET, return 404 for an unknown application, and render `_correction_messages.html` using 20-row chronological pages with explicit navigation and invalid-page fallback to 1. Return private/no-store response headers and perform no mutation.
- [ ] Add queue/detail triggers and `static/admin_hub/correction_messages.js`. Hover/focus shows summary only; click/tap loads the authorized history fragment into a dialog. Provide a usable endpoint link without JS. Share the endpoint/presenter with cockpit history. Keep pagination usable inside the dialog and show loading/fetch-error states without inventing empty history.
- [ ] Render escaped plain-text subject/body/note, actor when available, recorded outcome/timestamps, and resubmission resolution. Use `Nosūtīts e-pasta sistēmai` only for backend acceptance, not delivery/open proof. Supply dialog title, focus management, Escape/close/backdrop dismissal, and focus return. Never insert correspondence using unsafe HTML interpolation.
- [ ] Create `tests/admin_hub/test_correction_messages.py`: staff-only GET; non-staff denial; unknown application; POST refused; no GET mutation; escaping malicious note/body; paging >20 entries; bad page fallback; private cache headers; empty/pre-tracking copy; pending/failed/sent semantics; all unresolved versus resolved; shared queue/detail summary behavior. Extend `test_hub_queue.py` with bounded-history-query coverage comparing page sizes, without requiring all existing pipeline queries to be constant.
- [ ] Run `uv run pytest -q tests/admin_hub/test_correction_messages.py tests/admin_hub/test_hub_queue.py tests/admin_hub/test_hub_cockpit.py tests/registrations/test_correction_message_history.py`. Expect selected tests to pass.
- [ ] Manually verify hover, focus, click, touch, Escape, backdrop, focus return, pagination, network failure, and JavaScript-disabled endpoint navigation. Use multiple correction/resubmission cycles, a failed send, and an old application with no tracked history. Confirm full bodies are not downloaded with every queue row.

**Slice acceptance:** Queue and cockpit expose the same truthful correction history without N+1 history fetches, body leaks into list markup, unsafe HTML, or additional mutation routes.

## Task 6 — Documentation, verification and rollout

- [ ] Update README's relevant Admin Hub workflow section for name search, native-preview limitations, permit uploads, and correction-only history. Update docstrings for query signatures, viewer adapter input, private mail helper, and lifecycle semantics. Reconcile this spec/plan with any necessary narrow implementation adjustment; do not broaden scope silently.
- [ ] Update `docs/milestones.md` separately for each delivered slice with actual evidence and any pending browser/PostgreSQL acceptance. Keep unfinished slices planned. Document that history starts at deployment and follows application deletion, not audit retention.
- [ ] Run the full verification gate and inspect actual output:

  ```bash
  uv run pytest -q
  uv run ruff check .
  uv run mypy .
  uv run python manage.py makemigrations --check
  ```

  Expected: all executed tests pass, no lint/type errors, and no ungenerated model changes. Report skips and unrun acceptance explicitly; do not copy historical repository test counts as new evidence.
- [ ] Run `graphify update .` only if a knowledge graph exists at implementation time. The graph is absent during planning; do not generate one solely for this task.
- [ ] Deploy each schema-free slice independently if useful. For history, apply the additive migration before enabling tracked writes/UI. Do not backfill inferred emails. Verify pre-existing applications render the unknown-history state and new correction cycles produce records. No new env flag, provider, worker, or dependency is required.
- [ ] Record browser evidence for actual PDF desktop/mobile behavior, image/HEIC fallback, permit navigation/errors, search persistence and PostgreSQL Unicode behavior, and keyboard/touch history. Separate automated completion from outstanding live acceptance.

## Planning self-review

| Requirement | Coverage |
|---|---|
| Child/guardian search and matching tab counts | Task 1; split Guardian fields and null-safe token filtering. |
| PDF/native formats and safe fallback | Task 2; no classifier/upload expansion or arbitrary embedding. |
| Permit upload without a duplicate writer | Task 3; existing service/admin endpoint and safe return navigation. |
| Correction-request-only snapshots and honest send outcomes | Task 4; no extra message types, retries, historical reconstruction, or SMTP atomicity claim. |
| Queue hover/dialog and detail history | Task 5; bounded summaries, staff GET, escaping, accessibility and pagination. |
| Migration, privacy, docs and release evidence | Task 6 and design persistence/rollout sections. |

This session creates planning documentation only. No application behavior, migration, test execution, or commit is part of the planning result.

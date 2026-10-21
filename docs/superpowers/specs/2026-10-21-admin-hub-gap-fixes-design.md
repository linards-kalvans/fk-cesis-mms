# Admin Hub gap fixes design

**Date:** 2026-10-21  
**Status:** Planned; no implementation is authorized by this document-writing task.  
**Plan:** [Implementation plan](../plans/2026-10-21-admin-hub-gap-fixes.md)

## Context

Staff need four improvements to the application queue and review cockpit: child/guardian name search, inline PDF previews, medical-permit upload, and visible correction-request email history. These are four independently shippable slices, not a redesign of the Hub or a general notification platform.

The inspected baseline has the following constraints:

- `apps/admin_hub/views.py::queue_view` calls `queue_page(tab, page_number)` and `tab_counts()` in `queries.py`. Queue pages contain 25 applications. The queue template has no search input.
- `RegistrationApplication.member_full_name` is a database field. Guardian names are stored in `Guardian.first_name` and `family_name`; `display_name` is a property. There is no Guardian `full_name` database field to search.
- The cockpit constructs four viewer tabs using `build_doc_panel`: child ID, child ID back, guardian ID, and portrait. `_viewer.html` renders images or a fallback, despite the shared classifier already recognizing PDFs. The first tab is selected even when its document is missing.
- `viewer.js` applies image transforms through `[data-viewer-doc]`. Its toolbar links already follow the active tab. This behavior must survive all changes.
- `MedicalPermit` is separate from `Document`. Existing medical services already validate uploads, replace files safely, calculate validity, attach approved members, clear previous staff confirmation, and emit redacted audits. The existing admin upload action always returns to Django admin rather than honoring the Hub's `next` URL.
- `request_application_fix` changes a submitted application to `fix_requested`, saves its current review note, audits the transition, and sends `request_fix.txt`. `submit_application` clears the current review note on resubmission. Neither the current note nor an audit event is a durable record of the actual email text or send outcome.

## Scope and non-goals

Only action-required **correction-request emails (`request_fix`)** are tracked. Approval, rejection, OTP, magic links, agreements, billing, digests, and informational messages are excluded. Existing outbound message types and templates remain unchanged.

This work adds no resend control, automatic retry, general outbox, provider monitoring, delivery/open tracking, external conversion service, full-text search infrastructure, or new Hub mutation endpoint. It does not infer historical sends from status, review notes, or audit events. Invoice and family queues are outside the search scope.

All user-facing copy is Latvian. Existing authorization, CSRF protection, private-file access, and redacted audit rules remain mandatory.

## Decision record

### Context

Three gaps can largely reuse existing UI/domain machinery. Correction history cannot: the single mutable review note is cleared on resubmission and the mail helper does not persist its send-time content or outcome.

### Decision

Use focused, domain-backed correction history alongside small search/viewer/upload changes. Deliver in this order: **search → previews → medical uploads → correction history**. This gives useful increments early and lets the permit viewer reuse the preview work. Each slice remains releasable without the later slices; medical uploads can use the same viewer adapter independently if implemented first.

Alternatives considered:

1. **UI-only changes:** lowest schema cost, but cannot truthfully show previous correction emails or failed sends after the review note changes. Rejected for history; appropriate for the search and preview portions.
2. **Focused domain-backed history (selected):** one registrations model and a read-only Hub adapter preserve exact content and honest outcomes without introducing a second notification system.
3. **Broad notification hub and conversion engine:** could unify unrelated messages and file types, but adds providers, retention policies, retries, and unsafe-format concerns unrelated to these gaps. Rejected.

### Consequences

Search, previews, and medical upload require no schema changes or dependencies. Correction history requires one additive migration, stores sensitive staff correspondence, and must explicitly distinguish mail-backend acceptance from delivery. Historical coverage starts at rollout, not at the application's creation date. Native PDF and HEIC support remains browser-dependent; reliable open/download fallbacks are part of the feature rather than an exceptional path.

## Slice 1 — Application name search

### Query contract

Add `normalize_search(raw: str | None) -> str` in `apps/admin_hub/queries.py`. Strip leading/trailing whitespace, collapse internal whitespace to single spaces, and truncate to 200 characters. Normalize at the query boundary as well as in the view so direct query callers receive the same behavior.

Extend existing contracts, keeping their return values unchanged:

- `_tab_queryset(tab: str, *, q: str = "")`
- `queue_page(tab: str, page_number: Any, *, q: str = "") -> tuple[list[QueueRow], Any]`
- `tab_counts(*, q: str = "") -> dict[str, int]`

Split normalized `q` into tokens. AND the tokens; for each token, OR `icontains` over `member_full_name`, `guardian__first_name`, and `guardian__family_name`. A missing guardian must not exclude a child-name match. Apply this predicate to each existing tab queryset before counting or pagination. Preserve existing tab membership, order, page size, and invalid-page fallback.

This is ordinary database case-insensitive matching, not accent-insensitive matching. SQLite Unicode case behavior is not equivalent to PostgreSQL; verify Latvian names on the deployed PostgreSQL configuration without promising transliteration or diacritic folding.

### UI and acceptance

Provide a labeled GET search form, retained query value, submit button, clear action, and search-specific empty state. Preserve URL-encoded `q` across tabs and pagination. New searches, clearing, and tab changes start at page 1; pagination retains the selected tab and search. Tab counts always reflect the same query as the visible list. Do not log name queries or send them to analytics.

## Slice 2 — Native, bounded-format previews

Keep `doc_preview_kind` and upload acceptance unchanged. Existing JPEG, PNG, and WebP use the image path. HEIC uses the existing image path with an image-error fallback; no conversion dependency is introduced. PDFs use a native iframe or object with a descriptive title. Unknown types, including HTML, SVG, and office documents, receive open/download fallback only and are never embedded as arbitrary active content.

Use authorized private preview/download URLs only. Always make open/download actions visible for an available file, including PDF and image-load failure. Native PDF compatibility must be manually checked on desktop and mobile; no universal-browser rendering guarantee is made.

Choose the first available tab initially, both in rendered markup and JS initialization. If every tab is missing, show an explicit empty state with no stale file links. Maintain active-tab URL synchronization. Rotation, fit, zoom controls, zoom readout, and keyboard transforms apply only to a successfully loaded image; disable or mark them unavailable for PDF, missing, unknown, or failed-image panels. PDF elements never receive `data-viewer-doc`.

Before changing a response builder, test the existing PDF response MIME/disposition and frame policy. If these prevent trusted PDF display, narrowly correct the PDF response and add security tests. Do not loosen shared embedding/header policy for arbitrary uploaded types or bypass private authorization/auditing.

## Slice 3 — Medical permit in the cockpit

Show permit status, validity date, filename when present, and upload/replace controls in the cockpit. A confirmation-only permit must be distinguished from an uploaded file; it has no preview link. Reuse `medical_permit_status` and `medical_permit_status_label`, not duplicated date logic. Do not add confirmation or clear-confirmation controls; existing workflows remain unchanged.

Use a separate multipart POST form with CSRF, `action=medical_permit_upload`, `medical_permit_file`, and `next` set to the cockpit URL. Target `admin:registrations_registrationapplication_review-action`. Do not nest this form in another form. Continue to enforce the admin endpoint's `has_change_permission`; the Hub is not an alternate writer.

Change only the upload branch's missing-file, validation-error, and success returns to `_after_review_redirect(request, object_id)`. Preserve the existing safe-host/HTTPS validation, messages, and no-`next` Django-admin destination. External or unsafe `next` values must fall back to the admin change page.

Reuse `upload_application_medical_permit(application, upload, *, actor_label: str, actor=None) -> MedicalPermit` unchanged. Accepted matching declared MIME/extension pairs are PDF, JPG/JPEG, PNG, and HEIC, at most 25 MiB. WebP preview support does not imply medical-upload acceptance. The service owns safe replacement, validity through 30 September of N+1, confirmation clearing, approved-member attachment, and redacted audits. Do not run OCR on permits.

Add a medical viewer tab when a stored permit file exists. Generalize only the Hub viewer input to include explicit resolved `preview_url` and `download_url`, alongside `active` and `preview_kind`; adapt all four existing document tabs too. Build permit URLs with `registrations:medical-permit-preview` and `registrations:medical-permit-download`, using `permit_id`. Never reverse a `documents:*` URL with a permit ID or expose storage URLs. Existing Document panel consumers outside the Hub keep their current contract.

## Slice 4 — Correction-request history

### Persistence contract

Add `ApplicationCorrectionMessage` to `apps/registrations/models.py`:

| Field | Contract |
|---|---|
| `application` | FK to RegistrationApplication, CASCADE, `related_name="correction_messages"`. |
| `actor` | Nullable/blank FK to `settings.AUTH_USER_MODEL`, SET_NULL; the requesting reviewer. |
| `created_at` | Creation timestamp; no general-purpose mutable `updated_at` is needed. |
| `sent_at` | Nullable timestamp set only after `send_mail` returns 1. |
| `resolved_at` | Nullable timestamp set by successful resubmission. |
| `subject` | Text snapshot of the exact send-time subject. |
| `body` | Text snapshot of the exact rendered plain-text body passed to mail. |
| `review_message` | Text snapshot of the stripped correction note. |
| `status` | Choices `pending`, `sent`, `failed`; default `pending`. |

Add an index on `(application, created_at)` and deterministic history ordering by `(created_at, pk)`. Do not store a recipient snapshot, SMTP exception, provider payload, or delivery/open flags. The actor link is not a durable actor-name snapshot. Historical content is immutable except for send outcome/timestamps and resolution.

The history contains personal correspondence and can include names and the existing application/portal URL. It must not be copied into logs, analytics, or audit metadata. Render it escaped as plain text. Access is staff-only through the Hub; no public API or editable admin registration is required. Retention follows the owning application's lifecycle through CASCADE. The audit log's 730-day prune does **not** prune this model; do not claim otherwise. No separate correspondence-retention schedule is introduced.

### Sending and resolution

Keep `request_application_fix(application, reviewer, message) -> RegistrationApplication` and `submit_application(application, actor_account) -> RegistrationApplication` unchanged externally.

Minimally extend the private `_render_and_send_notification` helper with a keyword-only optional `correction_actor=None`, preserving its existing arguments and `None` return. Only `template_name="request_fix"` creates a history row; `request_application_fix` supplies the reviewer. Render once, create `pending` history before calling mail, and pass that exact subject/body to `send_mail(..., fail_silently=False)`.

- Return value 1: mark `sent`, set `sent_at`.
- Return value 0: mark `failed`, leave `sent_at` null; do not invent a successful send or introduce a new exception contract.
- Exception: mark `failed`, leave `sent_at` null, then re-raise the original exception. Persist no raw exception text.
- Interruption before the result is saved: leave `pending`, meaning uncertain/incomplete processing, not proven failure or success.

Untracked helper paths keep their existing behavior. Preserve the current application transition and audit semantics on mail failure. The inspected request-fix service is not atomic: do not introduce a transaction around history plus SMTP that rolls back the failed record. Verify real callers do not add such a rollback boundary. SMTP and database writes cannot be made atomic here; an accepted email followed by a failed outcome write remains uncertain, never automatically retried by this feature.

After successful resubmission validation, save the submitted status/review resets and set `resolved_at` on every unresolved correction row in one small database transaction. This includes pending and failed rows: resolution means the correction-request lifecycle was answered by resubmission, not that email was delivered or read. Invalid submission or merely saving a draft must not resolve history. No SMTP runs in this transaction.

### Queue and detail presentation

Add a focused presenter/query module `apps/admin_hub/correction_messages.py`. Queue summaries contain the successful-sent count, latest recorded request outcome/timestamp, and awaiting-parent state derived separately from application `fix_requested`. Fetch summaries for the current page in a bounded batch or annotations; do not introduce a history query for each row. Do not embed full bodies in queue markup.

Show successful-sent counts only. A latest pending/failed request has a separate warning, not a sent badge. Use accurate labels such as `Nosūtīts e-pasta sistēmai`, `Nosūtīšana neizdevās`, and `Nosūtīšanas iznākums nav apstiprināts`. Hover and keyboard focus reveal the latest recorded send summary. With no records, show `Nav reģistrētas ziņas` and explain that pre-tracking correspondence is unknown, not that no email was ever sent.

Click/tap opens an accessible dialog containing chronological history and exact subject/body/note, send outcome, timestamps, and resubmission resolution. Support Escape, close button, backdrop dismissal, focus management/return, loading/error states, and keyboard/touch operation. Staff must be able to distinguish mail-backend acceptance from delivery/open proof.

Add staff-only GET `/hub/pieteikumi/<pk>/zinojumi/`, named `admin_hub:correction-messages`, rendering `templates/admin_hub/_correction_messages.html`. Paginate at 20 rows, ordered oldest first, with explicit pagination links; invalid/out-of-range pages fall back to 1. Use the same presenter and endpoint for queue dialogs and cockpit history. The cockpit may show its summary and load full history on demand; it must not silently truncate history. GET performs no mutation. Unknown applications return 404; non-staff receive the existing Hub staff-login behavior. Return private, non-cacheable correspondence responses.

## Verification and rollout

Each slice has focused automated tests and manual acceptance in the linked plan. Future implementation uses tested changes; this planning task does not prescribe mandatory TDD or run application tests. Keep README workflow notes and changed query/helper docstrings accurate during implementation.

Only correction history adds a migration. Inspect migration leaves when implementing; the current registrations leaf is `0012_submission_digest_settings.py`, but do not reserve or fabricate a future migration number. There is no historical backfill. Deploy its additive schema before enabling the history UI and tracked writes. No new dependency is expected.

Before claiming implementation complete, run the full pytest, ruff, mypy, and migration checks, then exercise actual PDF/mobile fallback, image transforms, medical upload errors/navigation, search, and hover/keyboard/touch history. Report manual or PostgreSQL checks still pending rather than marking them passed. Update the milestone per slice only after its evidence exists.

# FK Cēsis MMS

FK Cēsis youth football club management system — MVP.

## Stack

- Python 3.12+, Django 5.x
- `uv` for dependency management
- pytest + pytest-django for testing
- SQLite for local development; PostgreSQL for production

## Local Development

### Prerequisites

- Python 3.12+
- [`uv`](https://github.com/astral-sh/uv) for dependency management

### Step-by-step setup

```bash
# 1. Install dependencies
uv sync

# 2. Ensure a .env file exists in the project root
#    The settings module auto-loads `.env` via `python-dotenv`.
#    A minimal file looks like:
#
#       DJANGO_SECRET_KEY=change-me
#       SITE_URL=http://localhost:8000
#
#    You can also inline the secret key as shown below if you
#    prefer not to create a file.

# 3. Run database migrations (creates db.sqlite3 if it does not exist)
DJANGO_SECRET_KEY=change-me uv run python manage.py migrate

# 4. Start the development server
DJANGO_SECRET_KEY=change-me uv run python manage.py runserver 0.0.0.0:8000

# 5. In a separate terminal, start the background-job worker.
#    REQUIRED for OCR — uploaded identity documents stay in
#    ocr_status=PENDING forever without it. The web process and the
#    worker share the same .env, so DJANGO_SECRET_KEY, OCR_ENCRYPTION_KEY,
#    and TINY_IDP_* (when OCR_PROVIDER_MODE=tiny_idp) must all be set in
#    the env that starts qcluster.
DJANGO_SECRET_KEY=change-me uv run python manage.py qcluster
```

> **First time on this branch?** Run `uv sync` (step 1) then `migrate` (step 3) again
> — Phase 0 added `django-q2` and 19 `django_q` migrations. Without the migration,
> the worker fails to start and uploads return 500.

### Database

The local development database is **SQLite** (`db.sqlite3` in the project root).
It is created automatically when you run `manage.py migrate` for the first time.

- **Safe to delete:** You can delete `db.sqlite3` at any time during local
development and re-run migrations to get a fresh database.
- **Migrations are source of truth:** The migration files in each app's
`migrations/` directory define the schema. Recreating the database simply
re-applies them.
- **When to recreate:** Delete the database when you need to reset data
(acceptance testing, schema experimentation) or after switching branches
with conflicting migration history.

### .env handling

Django settings auto-loads `.env` from the project root using
`python-dotenv`. If the file is missing, settings fall back to defaults
or environment variables. At minimum, set `DJANGO_SECRET_KEY` for
management commands to run without warnings.

### OCR runtime configuration

OCR is optional and controlled by four environment variables:

| Variable | Purpose | Required |
|---|---|---|
| `OCR_PROVIDER_MODE` | `stub` (deterministic dummy) or `tiny_idp` (real provider) | Yes |
| `TINY_IDP_API_URL` | tiny-IDP extraction endpoint | Only when `tiny_idp` |
| `TINY_IDP_API_KEY` | API key for tiny-IDP | Only when `tiny_idp` |
| `OCR_ENCRYPTION_KEY` | Fernet key for OCR payload/summary encryption | Yes (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |

For local development, leave `OCR_PROVIDER_MODE=stub` and set
`OCR_ENCRYPTION_KEY` to any valid Fernet key. The stub provider ignores
`TINY_IDP_*` variables entirely.

### Running tests and lint

```bash
uv run pytest                    # run test suite
uv run ruff check .              # lint
uv run mypy .                    # type check
```

## Project Structure

```
fk_cesis_mms/       # Django project package
apps/               # Domain apps
  accounts/
  registrations/
  members/
  billing/
  documents/
  integrations/
  admin_ops/        # Planned, not yet implemented
tests/              # Test suite
docs/               # Design docs, milestones
```

## Status

**Tasks 1–6 complete, P1 + P2 are complete, and P3 implementation baseline is now landed in code.** Registration workflow is usable for LAN acceptance testing, including OCR-backed parent/admin review flow. Live tiny-IDP sample-document validation is still pending before final P3 sign-off.

- `apps/` contains `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, and `integrations`
- `apps/core/models.py` defines the abstract `TimeStampedModel` base model
- `apps/accounts/models.py` defines `ParentAccount`, `MagicLinkToken`, and `EmailVerificationCode`
- `apps/accounts/services.py` provides magic-link helpers plus one-time code issue/send/verify services
- `apps/accounts/views.py` provides request, verify, logout, and one-time code verification views
- `apps/accounts/management/commands/ensure_admin_user.py` for env-driven admin creation
- `apps/registrations/models.py` defines `RegistrationApplication` with finalized P1 guardian/member/application snapshot fields plus admin review workflow metadata
- `apps/registrations/services.py` implements application lifecycle, same-address handling, chooser/prefill support, OCR-triggered identity processing, guardian-doc reuse, OCR-derived prefill, and admin review actions
- `apps/registrations/views.py` provides guardian email entry, new/edit registration, parent chooser portal, parent OCR summary rendering, and admin OCR review views
- `apps/members/models.py` defines `Member`, `Guardian`, `TrainingGroup`, and `KitSizeOption`
- `apps/documents/models.py` defines `Document` with private storage (`PRIVATE_DOCUMENTS_ROOT`), OCR process state, and `DocumentExtraction` for encrypted OCR payload/summary persistence
- `apps/documents` exposes admin-only protected preview/download endpoints; anonymous users are redirected to admin login, non-admin users receive `404`
- `.env` autoload works for management commands and app startup
- current acceptance-test URL: `http://192.168.3.245:8000`
- Billing domain and Invoice Ninja sync remain follow-up work

### Registration workflow UX
- `/register/` is guardian email entry for one-time code verification
- `/register/verify/` completes verified parent access before continuation
- `/portal/` acts as existing-guardian chooser/dashboard with draft continuation and start-new actions
- `/applications/new/` starts a new verified registration with guardian-only prefill
- Single edit form still uses **save draft** and **submit application**
- Member address supports **Adrese tāda pati kā vecāka** live sync and restore behavior

### Admin Hub (staff-facing, `apps/admin_hub`)
- `/hub/pieteikumi/` — review queue; each row opens the per-application cockpit, then agreement and plan/invoices pages
- Queue search (`?q=`) matches the child's full name and the guardian's first/family names. Whitespace-separated tokens are all required (AND), and each token may match either the child or the guardian; tab counts, the visible list and pagination all use the same normalized query. Matching is ordinary database case-insensitive search — not accent folding — so Latvian diacritics must be typed as stored.
- `/hub/rekini/` — club-wide outstanding-invoice review across all members
- Every Hub page is staff-only and renders derived state; all mutations still POST to the existing Django admin action endpoints
- The cockpit preserves all four document tabs and selects the first available file, or shows an empty state if none is available. PDFs use a titled native iframe through the private preview endpoint; every available file also has visible open/download fallback links. Native PDF support depends on the browser. JPEG, PNG, WebP, and HEIC use the image path, with an escaped-filename error fallback when decoding fails; no conversion is provided. HTML, SVG, office files, and other unsupported formats are not embedded.
- Rotation, zoom, keyboard transforms, and the zoom readout apply only to successfully loaded images; fit preserves rotation. Only inline responses with both a PDF extension and `application/pdf` MIME type permit same-origin framing (`SAMEORIGIN`); attachments, non-PDF files, and MIME/extension mismatches retain `DENY`. Authorization and auditing are unchanged. Slice 2 is implemented and review-approved with a green full automated gate; actual desktop/mobile multi-page PDF rendering, native fallback, HEIC errors, and image transforms/touch acceptance remain pending. See the [gap-fixes plan](docs/superpowers/plans/2026-10-21-admin-hub-gap-fixes.md) for evidence and remaining slices.
- The cockpit's medical-permit card and review checklist share the right column beside the viewer. Status and validity remain visible; upload/replace controls and file access require the registered application admin's change permission. A standalone multipart CSRF form uses the existing admin upload action. Matching PDF, JPG/JPEG, PNG, and HEIC MIME/extension pairs up to 25 MiB are accepted; WebP upload, OCR, and confirmation controls are not added. The existing writer retains replacement, validity, approved-member linkage, and audit responsibilities. Safe `next` returns to the cockpit on success and validation errors; unsafe or missing `next` falls back to Django admin.
- All four original viewer tabs now receive explicit private preview/download URLs. A fifth medical tab appears only for a real file and application-admin change permission; confirmation-only permits show status/date without a file tab. The designated registrations medical proxy now also permits authenticated active staff with `RegistrationApplicationAdmin.has_change_permission(request, permit.application)`, preserving parent ownership and anonymous/foreign/missing-file behavior. Its inline matching PDF MIME/extension responses alone use `SAMEORIGIN`; other responses retain `DENY`, with no global framing change.
- Correction history tracks only new `request_fix` attempts: exact subject/rendered plain-text body, stripped note, nullable reviewer, creation/send/resolution timestamps, and `pending`/`sent`/`failed` outcome. `sent` means mail-backend acceptance, not delivery or opening. A zero return or exception records failure; exceptions are re-raised. Interruption or a failed outcome write can leave an uncertain `pending` record. There is no SMTP/database transaction, retry/resend mechanism, historical backfill, or recipient/provider/error snapshot. Successful submission atomically resets submission/review/digest state and resolves every unresolved attempt, including pending/failed ones; draft saves and invalid submissions do not resolve history.
- Queue and cockpit share bounded, body-free summaries (two history queries for a nonempty application page); awaiting-parent state comes separately from application status. Hover/focus reveals the summary without fetching. Click/tap loads escaped correspondence into a shared dialog with loading/error states, pagination, native Escape, close/backdrop dismissal, and focus return. Staff-only GET `/hub/pieteikumi/<pk>/zinojumi/` (`admin_hub:correction-messages`) returns 20 oldest-first records per page, falling back to page 1 for invalid pages. AJAX requests receive a fragment; normal navigation provides a standalone no-JavaScript page. Unknown applications return 404; staff POST requests return 405; correspondence responses use `Cache-Control: private, no-store`.
- Apply additive migration `registrations/0013_applicationcorrectionmessage.py` before enabling tracked writes and history UI. History begins at rollout; an empty history does not prove no earlier email existed. Correspondence is sensitive, follows application deletion through CASCADE, and is not covered by audit-log pruning. No new dependency, environment setting, or worker is required.
- Slices 1–4 are implemented and review-approved; Slice 4 was re-approved after the rollback-coverage correction. The controller's final full automated gate recorded **2758 passed, 0 skipped, no failures/errors**, with ruff/type/migration/diff checks exiting 0. Task 6 documentation and automated verification are complete; deployment and all browser/PostgreSQL acceptance remain pending, so the milestone is **not acceptance-signed-off**. Outstanding checks cover search/Latvian collation, desktop/mobile PDF and HEIC fallback/image transforms, medical upload/replace before and after approval with navigation/errors, and correction-history hover/focus/click/touch/dismissal/focus return/paging/network failure/no-JavaScript/multiple-cycle/old-history behavior. DOM harness tests are not browser evidence. Nothing was deployed or sent live, committed, pushed, or worktreed. See the [gap-fixes plan](docs/superpowers/plans/2026-10-21-admin-hub-gap-fixes.md) for attributed evidence and unchecked acceptance items.

### Admin Hub review actions (2026-10-23 follow-up)

Units 2 and 3 are implemented and independently review-approved after fixes. [Scoped local acceptance](docs/acceptance/2026-10-23-admin-hub-review-actions.md) includes genuine parent OTP/wizard resubmission, staff resolution, rejection, document-only void and explicit selected-invoice discontinuation. Unit 2 recorded **25 PASS / 1 BLOCKED / 2 NOTRUN**; Unit 3 initially recorded **18 PASS / 1 FAIL**, with the mobile overflow/tap regression subsequently fixed, verified at 320/390 px and review-approved, including the strengthened media-block test. The current post-mobile-fix controller PostgreSQL gate is **2871 passed, 0 errors/failures/skips, 479.111s**, timestamp **2026-10-23**; the parent personally inspected `/tmp/opencode/fk-review-actions-browser-final-pg.xml`. Full ruff/mypy/`makemigrations --check`/diff checks passed, with only existing mypy annotation notes. The **2869** pre-mobile-fix gate and focused **413 Hub / 34 agreement/CSS** passes remain historical. Automated results are not new browser cases or a browser rerun. Authenticated tunnel acceptance is blocked; physical mobile, non-Chromium browsers and target migrations/deployment remain open. Local email capture and stub outcomes are not live delivery/provider proof. This is not release sign-off; prior gap acceptance remains separate. See the [review-actions plan](docs/superpowers/plans/2026-10-23-admin-hub-review-actions.md).

- **Close corrections:** From a `Jālabo` (`FIX_REQUESTED`) cockpit, staff with application-admin change permission can open “Atzīmēt labojumus kā atrisinātus” and explicitly confirm. This returns the application to `Jāizskata` (`SUBMITTED`), closes every unresolved attempt (including failed/pending sends), uses one timestamp, clears review metadata and rearms the daily submission digest. It does not rerun parent completeness gates, approve the application, create a member/agreement, send email or emit parent-submission analytics. The existing `Jālabo` queue tab remains the awaiting-parent filter.
- **Provenance:** Shared dialog and standalone history distinguish `staff_manual` from `parent_resubmission`, showing resolution time and nullable resolving staff separately from the original requesting actor. Deleting that staff user retains manual source/time and shows an unavailable-user label. Original subject/body/note, send outcome and send timestamps remain unchanged. Resolution is not proof of email delivery or a parent response.
- **Reject:** Submitted applications offer a separate native “Noraidīt” disclosure with required reason and deliberate confirmation, independent of request-fix. Rejection retains the existing notification and is not correction correspondence. A `FIX_REQUESTED` application must first return to review; rejection is submitted-only.
- **Void document:** “Anulēt līguma dokumentu” is offered for generated/sent/signed current agreements. Its independent form requires a reason in the Hub and warns that membership and invoices are unchanged. History, current flag, external ID and signed artifact remain; the existing void email/archive behavior remains. This is not a prerequisite to discontinuation and does not globally tighten the shared void service's policy.
- **Discontinue membership:** “Pārtraukt dalību un norēķinus” requires the current signed agreement and active member, a date/reason and explicit invoice selection. No invoice is selected by default; **zero selection changes no invoices**. Selected unpushed/unsent invoices cancel locally; external drafts queue archive, and sent unpaid invoices queue external cancellation after commit. Paid/partial, foreign/unknown or unclear-state selections are rejected without partial mutation. No global future-invoice stop, refund or automatic credit application is promised.
- **Persisted outcomes:** After discontinuation, a read-only table shows cancelled invoice rows with cancellation time, action and local/pending/done/failed outcome from stored fields. Enqueuing a job is not evidence of remote success. This is a member-level cancelled-row view, not a new per-event selection ledger. Terminal-state pages suppress misleading active controls while retaining artifacts/history.
- All writes use existing Django admin endpoints with change permission, POST, CSRF and validated `next`; native/family-admin behavior remains covered. There is no new Hub writer or PDF product filter.

Apply `registrations/0014_applicationcorrectionmessage_resolution.py` and `core/0013_alter_auditevent_action.py` **before code/UI uses resolution fields**. The registrations migration marks only already-resolved historical rows as parent resubmission; unresolved rows stay blank and no resolving staff is invented. Reversal removes new provenance, not pre-existing correspondence/resolution timestamps or completed business operations. The root default database was intentionally left unmigrated; isolated test migrations are not production rollout. No environment setting, dependency or worker was added, and no production action was taken.

### Task 6 follow-up debt
- Revisit desktop typography in Task 6 UI pass: blue text renders too heavy/thick on desktop and needs refinement.

### P3 delivered baseline
- synchronous OCR for `guardian_identity` and `member_identity`
- `member_portrait` excluded from OCR path
- encrypted OCR payload/summary persistence
- guardian identity default reuse on `/applications/new/`
- parent OCR summary/source-label rendering
- admin guardian/member OCR preview and confidence rendering

### Next task
Live tiny-IDP sample-document validation, agreement-handling first slice, and production email delivery remain active follow-up work.

## Development Workflow

- Develop all new work only inside a local git worktree directory; do not develop directly on checked-out `main`.
- Develop each task or feature in its own git worktree branch.
- Merge work back to `main` only after user approval.
- Expose usable app slices on LAN as early as practical for acceptance testing.
- Current preferred acceptance-test host is `192.168.3.245:8000` on the local network.
- Do not wait until end of MVP to share first working flow.

## Documentation

- Authoritative project guide: `AGENTS.md`
- Canonical product spec: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Milestones: `docs/milestones.md`
- Runtime contract: `docs/runtime-contract.md`
- Local Docker smoke: `docs/local-docker-smoke.md`
- Deployment ownership pointer: `docs/deployment.md` (deployed runtime lives in `https://github.com/linards-kalvans/fk-cesis`)
- Audit log (operator guide): `docs/audit-log.md`
- Historical plans archive: `docs/archive/plans/` *(read only when explicitly needed for history)*

## License

This project is licensed under the **GNU Affero General Public License v3.0
or later** (AGPL-3.0-or-later). See [`LICENSE`](./LICENSE) for the full text.

The AGPL applies the GPL's source-availability obligations to network-hosted
software: anyone running a modified copy of this code as a service for
others must make their changes available to those users under the same
license. This is intentional — it keeps a community sports-club tool a
shared commons rather than fuel for a closed-source product.

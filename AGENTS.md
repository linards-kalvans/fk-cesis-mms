# AGENTS.md — FK Cēsis MMS

*Authoritative project guide. Keep this file updated after major changes.*

## Project Purpose
Django MVP for FK Cēsis youth football club: parent registration, admin approval, secure identity-document handling, and Invoice Ninja billing orchestration.

## Stack
- **Python 3.12+**, **Django 5.x**, **PostgreSQL** (psycopg)
- **uv** for dependency management and script execution
- **pytest** + **pytest-django**, **ruff**, **mypy**
- Private file/object storage, background job runner (Celery / Django-Q)
- Server-rendered templates (parent + admin), minimal JS

## Architecture
Target Django monolith with domain apps:
- `apps/core` — shared base models, enums, audit helpers
- `apps/accounts` — ParentAccount, magic-link auth
- `apps/registrations` — RegistrationApplication workflow, OCR intake
- `apps/members` — Member, Guardian, TrainingGroup
- `apps/billing` — MembershipPlan, sibling discount, Invoice Ninja sync
- `apps/documents` — private Document model, audited access views
- `apps/integrations` — Invoice Ninja / OCR clients, retry state
- `apps/admin_ops` — admin dashboards, CSV export *(planned, not yet implemented)*

## Current Status
**Tasks 1–6 complete in current worktree, P1 + P2 are complete, and P3 implementation baseline is now landed in code.** Registration workflow is usable for LAN acceptance testing; admin review queue, member creation baseline, guardian-email-first verified registration gate, and OCR-backed parent/admin review flow are operational. P3 still requires live sample-document validation before implementation sign-off.
- Django project scaffold exists and boots.
- `apps/` package exists with app configs for `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, `integrations`.
- `apps/core/models.py` includes abstract `TimeStampedModel`.
- `apps/accounts/models.py` implements `ParentAccount`, `MagicLinkToken`, and `EmailVerificationCode`.
- `apps/accounts/services.py` implements `issue_magic_link`, `send_magic_link`, `consume_magic_link`, plus one-time email code issue/send/verify helpers.
- `apps/accounts/views.py` implements request, verify, logout, and one-time code verification views.
- `apps/accounts/management/commands/ensure_admin_user.py` for env-driven admin creation.
- `apps/registrations/models.py` implements `RegistrationApplication` with finalized P1 guardian/member/application fields, draft/submitted states, and fix/reject/approve workflow.
- `apps/registrations/services.py` implements application lifecycle: create, save draft, submit, chooser/prefill support, same-address handling, link to parent account, admin review actions (request_fix, reject, approve), OCR-triggered identity upload processing, guardian-doc reuse, and OCR-derived prefill/field-source mapping. `fix_requested` save preserves status (Task 3).
- `apps/registrations/views.py` provides guardian email entry, verified registration create/edit, chooser portal, admin review queue/detail views, canonical application workspace routing, parent OCR summary rendering, and admin OCR review context.
- `apps/registrations/presentation.py` implements grouped form rendering contract and workspace mode logic (Task 3).
- `apps/registrations/forms.py` implements the unified registration form with grouped sections (Task 3).
- `apps/registrations/templatetags/reg_filters.py` provides template filters for the form contract (Task 3).
- `apps/members/models.py` implements `Member`, `Guardian`, `TrainingGroup`, and `KitSizeOption` models; approval creates `Member` + `Guardian` with `training_group` left empty.
- `apps/documents/models.py` implements `Document` model with private storage (`PRIVATE_DOCUMENTS_ROOT`), OCR process state fields, and `DocumentExtraction` for encrypted OCR payload/summary persistence.
- `apps/documents` uses a dedicated private storage root (`private-uploads/`), Fernet-encrypted OCR payload/summary helpers in `apps/documents/ocr.py`, and admin-only protected preview/download endpoints (`/admin/documents/<id>/preview/`, `/admin/documents/<id>/download/`). Anonymous users are redirected to admin login; non-admin authenticated users receive `404`.
- `.env` autoload works for local commands and app startup.
- Current acceptance testing runs on LAN URL `http://192.168.3.245:8000`.

### P1 delivered registration workflow UX
- `/register/` is guardian email entry for one-time code verification.
- `/register/verify/` completes verified parent access before continuation.
- `/portal/` acts as chooser/dashboard for verified guardians.
- `/applications/new/` starts a new verified registration with guardian-only prefill.
- `/applications/<id>/` is the canonical parent application workspace (Task 3); legacy parent routes redirect here.
- Anonymous same-browser draft continuation was removed; edit/submit now require verified parent ownership.
- Edit page uses a single form with two actions: **save draft** and **submit application**.
- Member address supports live **Adrese tāda pati kā vecāka** sync and restore behavior.
- Grouped form rendering contract in place (Task 3): guardian, child/player, and document sections rendered via shared template primitives (`form_field.html`, `source_badge.html`).
- Application workspace supports read-only (submitted/approved/rejected) and editable (draft/fix_requested) modes; `fix_requested` save preserves status (Task 3).

### Task 4 delivered — document state, OCR source cues, error summary
- `templates/parent_ui/includes/document_card.html` — reusable document card partial showing filename, kind label, active/not-uploaded state, and replace/upload links for parent workspace.
- `templates/parent_ui/includes/error_summary.html` — updated to render field label, validation message, and anchor link to invalid field via `items` parameter.
- `templates/registrations/application_workspace.html` — includes document card section in both editable and read-only modes; replace/upload links only shown in editable mode; passes source labels to all form fields.
- Source badges render for `manual_only`, `derived_system_filled`, and OCR markers (`ocr_guardian_identity`, `ocr_member_identity`) using `SOURCE_LABEL_MAP` in `presentation.py`.
- Invalid-submit error summary shows heading, field label, validation message, and anchor target (`id-guardian_email` pattern).
- No schema changes, no business rule changes, no admin redesign.

### P2 delivered — visual system refinements, document-state/review-cue presentation
- Typography refined for readability (desktop and mobile).
- Active uploaded-document state and replace guidance clarified via document card partial.
- Review/correction cues completed at presentation layer without real OCR dependency: source badges, error summary with anchor links, invalid-submit error summary.
- No schema changes, no business rule changes, no admin redesign.

### P3 delivered — OCR integration + secure extracted metadata baseline
- `apps/integrations/ocr.py` provides OCR provider boundary with deterministic stub mode and tiny-IDP hook point.
- Identity uploads for `guardian_identity` and `member_identity` now run synchronous OCR in draft flow; `member_portrait` stays outside OCR scope.
- OCR success persists encrypted payload and encrypted summary in `DocumentExtraction`; OCR failure stays non-blocking and records failed state.
- `/applications/new/` reuses active guardian identity document by default for returning verified guardians and merges prior OCR extraction into new-app prefill.
- Parent workspace shows OCR-derived source labels and decrypted OCR summaries for uploaded identity documents.
- Admin review detail shows separate guardian/member document preview sections, decrypted OCR summaries, and confidence values when provider returns them.
- Test-client file upload workaround in `tests/conftest.py` supports Django 6 multipart posts with `files=`.
- Full repo verification after P3 landing: `uv run pytest -q` → `584 passed`, `uv run ruff check .` → passed, `uv run mypy .` → passed.
- Live sample-document validation is still required before final implementation sign-off.

### Task 6 follow-up debt
- Revisit desktop typography in Task 6 UI pass: blue text renders too heavy/thick on desktop and needs refinement.
- Django admin document UX should distinguish active vs replaced (soft-deleted) documents and hide or clearly disable preview/download actions for replaced rows.
- Training group assignment on approval (currently left empty).
- Admin activity audit entries for review actions.
- Run real tiny-IDP sample-document validation and capture evidence before calling P3 fully signed off.

### Approved design and research direction (2026-05-05)
- **Build now:** whole-app visual system and registration form redesign (major parent-flow changes allowed).
- **Registration entry direction:** implemented in P1 as guardian email entry with one-time email code verification, verified continuation, guardian-only prefill, and chooser/dashboard for existing guardians. See `docs/superpowers/specs/2026-05-08-p1-field-contract-and-verified-registration-gate-design.md`.
- **Security fix — parent identity verification:** implemented in P1. Typed email in registration draft is a claim, not proof of ownership. Verified access now gates registration continuation and portal access. See `docs/superpowers/specs/2026-05-08-p1-field-contract-and-verified-registration-gate-design.md`.
- **Research spikes / preferred directions:** OCR vendor direction narrowed to **tiny-IDP** only, agreement generation with manual signing first and **DocuSeal self-hosted** favored for future richer processing, and SMTP/email provider strategy for scale.
- **Hosting stance:** self-hosted is not assumed more secure by default; compare self-hosted and SaaS by security posture, ops maturity, compliance, and API portability.
- **Visual direction:** unified design system, calm centered parent flow, denser admin shell, club logo hero-style on parent entry screens.
- **Style source of truth:** `style-guide/` supersedes `design-template.html`. Canonical tokens currently: font `Anton`, blue `#0f0851`, red `#ce1c20`.
- **Agreement handling, first slice:** after admin approval, generate agreement, allow manual signing outside platform (LV qualified electronic signature or paper), then mark signed and optionally upload signed copy. Richer countersign/order automation may follow later.
- **GDPR/EU compliance mandatory** for all third-party integrations.
- **Service boundary:** self-hosted services may live in separate infrastructure/Ansible projects; this repo should integrate loosely via adapters and external config, not own their deployment lifecycle.
- Spec: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`.

Reference docs:
- Canonical product spec: `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`
- Milestones: `docs/milestones.md`
- Style guide assets: `style-guide/`
- Style guide tokens: `style-guide/tokens.md`, `style-guide/tokens.css`
- Design template (exploratory only, superseded by `style-guide/` on conflict): `design-template.html`

## Milestones
- `M1` — Foundation and security baseline
- `M2` — Parent registration intake
- `M3` — Admin review and member creation
- `M4` — Billing and Invoice Ninja sync
- `M5` — Admin operations and export
- `M6` — Production readiness

Use `docs/milestones.md` as authoritative milestone tracker and base for future development tasks. Keep it updated as scope/status changes.

Archive rule:
- `docs/archive/` is historical only.
- Do not use archived docs for planning, execution, or status by default.
- Read archived docs only when user explicitly asks for history/archive context.

## Commands
```bash
uv sync                                # install deps
uv run python manage.py migrate        # run migrations
uv run python manage.py runserver      # start dev server locally
uv run pytest                          # run test suite
uv run ruff check .                    # lint
uv run mypy .                          # type check
```

Rules:
- Always use `uv run` for Python commands.
- Do not assume `venv/` or `pip` exist.
- For user-accessible dev servers, expose app through `kimaki tunnel`, not localhost-only.
- For acceptance testing, expose usable app slices early, not only at end.

## Coding Conventions
- **TDD first** — write failing test, then implementation, then verify.
- **Plan before coding** — multi-step work needs written plan.
- **Verify before completion** — run `uv run pytest -q && uv run ruff check . && uv run mypy .` before claiming done.
- Use `apps/<domain>/` layout; each app should eventually contain `models.py`, `services.py`, `views.py`, `urls.py`.
- Business rules live in `services.py` / `rules.py`, not views or templates.
- No sensitive PII in logs. Mask personal IDs; redact external API payloads.
- All external API calls (Invoice Ninja, OCR) run through background jobs with retry state.
- Develop all new work only inside a local git worktree directory; do not develop directly on checked-out `main`.
- Develop each task or feature in its own git worktree branch, then merge back to `main` only after user approval.
- Create future worktrees inside project directory (for example `.worktrees/` or `worktrees/`), not outside repository.
- On future iterations, copy project-root `.env` into the worktree before running env-driven commands or local app flows.
- When app is exposed through a tunnel, ensure worktree `.env` uses the correct `SITE_URL` and related trusted-origin settings so CSRF-protected forms work over the tunnel.
- Current acceptance-test baseline uses LAN bind on `192.168.3.245:8000`.
- Ask before major structural changes or architecture changes.
- Keep context lean; read only files needed for current task.
- Keep `README.md` and project docs accurate when architecture or workflows change.

## Security Rules (PII / Documents)
- Registration identity documents stored under `PRIVATE_DOCUMENTS_ROOT` (`private-uploads/`), separate from `MEDIA_ROOT`.
- OCR-extracted document metadata (number, issuer, issuance date, expiry, etc.) is sensitive data and must be protected with same posture as underlying identity documents.
- No public file URLs for registration documents. Every preview/download passes through admin-only Django views that enforce staff authorization.
- Identity documents stored in private storage; streamed through authenticated backend views.
- No public file URLs. Every download checks application/member authorization.
- Personal IDs masked in list/search; full values only on restricted detail views.
- Magic links: single-use, short TTL, revoked after use, rate-limited.
- Document view/download/delete actions audited via `AuditEvent`.
- Secrets stored outside repo (`.env`); never committed.

## Scope Boundaries
**MVP in scope:** parent registration (Latvian), admin approval workflow, member registry, training group assignment, secure documents, OCR assist (non-blocking), Invoice Ninja billing sync, sibling discount, CSV export.

**Out of scope:** coach portal, adult members, attendance tracking, WhatsApp bot, event planning, direct FA integration.

## Skills / Workflows
- **brainstorming** — invoke before creative feature or design change.
- **writing-plans** — use when implementing multi-step work from spec.
- **test-driven-development** — required for feature and bugfix work.
- **verification-before-completion** — always run full verification before claiming done.
- **subagent-driven-development** — preferred execution mode for plan-driven work in this repo.
- **finishing-a-development-branch** — use when implementation is complete and ready for merge/PR decision.
- **uv** — always use `uv` for Python deps; never edit `pyproject.toml` manually without justification.

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
**Tasks 1–6 complete in current worktree.** Registration workflow is usable for LAN acceptance testing; admin review queue and member creation baseline are operational.
- Django project scaffold exists and boots.
- `apps/` package exists with app configs for `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, `integrations`.
- `apps/core/models.py` includes abstract `TimeStampedModel`.
- `apps/accounts/models.py` implements `ParentAccount` and `MagicLinkToken`.
- `apps/accounts/services.py` implements `issue_magic_link`, `send_magic_link`, `consume_magic_link`.
- `apps/accounts/views.py` implements request, verify, and logout views.
- `apps/accounts/management/commands/ensure_admin_user.py` for env-driven admin creation.
- `apps/registrations/models.py` implements `RegistrationApplication` with draft/submitted states and fix/reject/approve workflow.
- `apps/registrations/services.py` implements application lifecycle: create, save draft, submit, link to parent account, and admin review actions (request_fix, reject, approve).
- `apps/registrations/views.py` provides start, edit, parent portal, and admin review queue/detail views.
- `apps/members/models.py` implements `Member`, `Guardian`, and `TrainingGroup` models; approval creates `Member` + `Guardian` with `training_group` left empty.
- `apps/documents/models.py` implements `Document` model with private storage (`PRIVATE_DOCUMENTS_ROOT`) and placeholder OCR status.
- `apps/documents` uses a dedicated private storage root (`private-uploads/`) and admin-only protected preview/download endpoints (`/admin/documents/<id>/preview/`, `/admin/documents/<id>/download/`). Anonymous users are redirected to admin login; non-admin authenticated users receive `404`.
- `.env` autoload works for local commands and app startup.
- Current acceptance testing runs on LAN URL `http://192.168.3.245:8000`.

### Task 5 polish (registration workflow UX)
- `/register/` accessible without prior login in current implementation.
- Current implementation still allows anonymous same-browser draft continuation before verified-gate redesign lands.
- Edit page uses a single form with two actions: **save draft** and **submit application**.
- Child birth date field uses native browser `<input type="date">` picker.
- Conflicting birth-date hint text removed from edit form.

### Task 6 follow-up debt
- Revisit desktop typography in Task 6 UI pass: blue text renders too heavy/thick on desktop and needs refinement.
- Registration edit form does not show that an identity document was already uploaded; users can re-upload unnecessarily, which soft-deletes the earlier document and creates confusing duplicate admin rows.
- Django admin document UX should distinguish active vs replaced (soft-deleted) documents and hide or clearly disable preview/download actions for replaced rows.
- Training group assignment on approval (currently left empty).
- Admin activity audit entries for review actions.

### Approved design and research direction (2026-05-05)
- **Build now:** whole-app visual system and registration form redesign (major parent-flow changes allowed).
- **Registration entry direction:** registration starts with guardian email; existing guardian gets magic link for verified continuation and prefill, new guardian must verify email before continuing. Guardian and child/player field sets are not final and must be reviewed early. See `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`.
- **Security fix — parent identity verification:** typed email in registration draft is a claim, not proof of ownership. Verified access gates registration continuation and portal access; social login may later satisfy same gate. See `docs/superpowers/specs/2026-05-08-fk-cesis-mms-product-spec.md`.
- **Research spikes / preferred directions:** OCR vendor shortlist with **tiny-IDP** favored first, agreement generation with manual signing first and **DocuSeal self-hosted** favored for future richer processing, and SMTP/email provider strategy for scale.
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

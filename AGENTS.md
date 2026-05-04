# AGENTS.md — FK Cēsis MMS

## Project Purpose
Django MVP for FK Cēsis youth football club: parent registration, admin approval, secure identity-document handling, and Invoice Ninja billing orchestration.

## Stack
- **Python 3.12+**, **Django 5.x**, **PostgreSQL** (psycopg)
- **uv** for dependency management and script execution
- **pytest** + **pytest-django**, **ruff**, **mypy**
- Private file/object storage, background job runner (Celery / Django-Q)
- Server-rendered templates (parent + admin), minimal JS

## Architecture
Django monolith with domain apps:
- `apps/core` — shared base models, enums, audit helpers
- `apps/accounts` — ParentAccount, magic-link auth
- `apps/registrations` — RegistrationApplication workflow, OCR intake
- `apps/members` — Member, Guardian, TrainingGroup
- `apps/billing` — MembershipPlan, sibling discount, Invoice Ninja sync
- `apps/documents` — private Document model, audited access views
- `apps/integrations` — Invoice Ninja / OCR clients, retry state
- `apps/admin_ops` — admin dashboards, CSV export

## Current Status
**Task 1 complete.** Django project scaffold exists with minimal settings.
- Design spec: `docs/superpowers/specs/2026-05-04-fk-cesis-mms-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-04-fk-cesis-mms-mvp-implementation.md`
- Milestones: `docs/milestones.md`
- Design template: `design-template.html`

## Commands
```
uv sync                          # install deps
uv run python manage.py migrate  # run migrations
uv run python manage.py runserver  # start dev server
uv run pytest                    # run test suite
uv run ruff check .              # lint
uv run mypy .                    # type check
```
All commands use `uv run` prefix. Do not assume `venv/` or `pip` exist.
For acceptance testing, expose dev app on LAN as early as practical, not only at the end.

## Coding Conventions
- **TDD first** — write failing test, then implementation, then verify.
- **Plan before coding** — multi-step work needs a written plan.
- **Verify before completion** — run `pytest -q && ruff check . && mypy .` before claiming done.
- Use `apps/<domain>/` layout; each app has `models.py`, `services.py`, `views.py`, `urls.py`.
- Business rules live in `services.py` / `rules.py`, not views or templates.
- No sensitive PII in logs. Mask personal IDs; redact external API payloads.
- All external API calls (Invoice Ninja, OCR) run through background jobs with retry state.
- Develop each task or feature in its own git worktree branch, then merge back to `main` only after user approval.
- Launch usable app slices on LAN early and hand them to user for acceptance testing before late-stage polish.

## Security Rules (PII / Documents)
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
- **brainstorming** — invoke before any creative feature or design change.
- **writing-plans** — use when implementing multi-step work from spec.
- **verification-before-completion** — always run full verification before claiming done.
- **uv** — always use `uv` for Python deps, never edit `pyproject.toml` manually without justification.

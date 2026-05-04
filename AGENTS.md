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
**Tasks 1–3 complete in current worktree.**
- Django project scaffold exists and boots.
- `apps/` package exists with app configs for `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, `integrations`.
- `apps/core/models.py` includes abstract `TimeStampedModel`.
- Full business models, services, views, and URLs for most domain apps are **not implemented yet**.

Reference docs:
- Design spec: `docs/superpowers/specs/2026-05-04-fk-cesis-mms-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-04-fk-cesis-mms-mvp-implementation.md`
- Milestones: `docs/milestones.md`
- Design template: `design-template.html`

## Milestones
- `M1` — Foundation and security baseline
- `M2` — Parent registration intake
- `M3` — Admin review and member creation
- `M4` — Billing and Invoice Ninja sync
- `M5` — Admin operations and export
- `M6` — Production readiness

Use `docs/milestones.md` as authoritative milestone tracker. Keep it updated as scope/status changes.

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
- Develop each task or feature in its own git worktree branch, then merge back to `main` only after user approval.
- Ask before major structural changes or architecture changes.
- Keep context lean; read only files needed for current task.
- Keep `README.md` and project docs accurate when architecture or workflows change.

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
- **brainstorming** — invoke before creative feature or design change.
- **writing-plans** — use when implementing multi-step work from spec.
- **test-driven-development** — required for feature and bugfix work.
- **verification-before-completion** — always run full verification before claiming done.
- **subagent-driven-development** — preferred execution mode for plan-driven work in this repo.
- **finishing-a-development-branch** — use when implementation is complete and ready for merge/PR decision.
- **uv** — always use `uv` for Python deps; never edit `pyproject.toml` manually without justification.

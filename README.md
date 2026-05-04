# FK Cēsis MMS

FK Cēsis youth football club management system — MVP.

## Stack

- Python 3.12+, Django 5.x, PostgreSQL
- `uv` for dependency management
- pytest + pytest-django for testing

## Getting Started

```bash
uv sync                          # install deps
DJANGO_SECRET_KEY=change-me uv run python manage.py migrate  # run migrations
uv run python manage.py runserver  # start dev server
uv run pytest                    # run tests
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

**Tasks 1–4 complete.** Foundation, security baseline, and parent magic-link auth are implemented.

- `apps/` contains `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, and `integrations`
- `apps/core/models.py` defines the abstract `TimeStampedModel` base model
- `apps/accounts/models.py` defines `ParentAccount` and `MagicLinkToken`
- `apps/accounts/services.py` provides `issue_magic_link`, `send_magic_link`, `consume_magic_link`
- `apps/accounts/views.py` provides request, verify, and logout views
- `apps/accounts/management/commands/ensure_admin_user.py` for env-driven admin creation
- `.env` autoload works for management commands and app startup
- current acceptance-test URL: `http://192.168.3.245:8000`
- Full business models for registrations, members, billing, and documents are **not implemented yet**

## Development Workflow

- Develop each task or feature in its own git worktree branch.
- Merge work back to `main` only after user approval.
- Expose usable app slices on LAN as early as practical for acceptance testing.
- Current preferred acceptance-test host is `192.168.3.245:8000` on the local network.
- Do not wait until end of MVP to share first working flow.

## Documentation

- Authoritative project guide: `AGENTS.md`
- Design spec: `docs/superpowers/specs/2026-05-04-fk-cesis-mms-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-04-fk-cesis-mms-mvp-implementation.md`
- Milestones: `docs/milestones.md`

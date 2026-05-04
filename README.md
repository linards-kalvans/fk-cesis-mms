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
apps/               # Domain apps (planned — not yet created)
  accounts/
  registrations/
  members/
  billing/
  documents/
  integrations/
  admin_ops/
tests/              # Test suite
docs/               # Design docs, milestones
```

## Status

**Task 1 complete.** Django project scaffold and settings are in place.
Full app structure (`apps/`) and configuration will be added in subsequent tasks.

## Development Workflow

- Develop each task or feature in its own git worktree branch.
- Merge work back to `main` only after user approval.
- Expose usable app slices on LAN as early as practical for acceptance testing.
- Do not wait until end of MVP to share first working flow.

## Documentation

- Design spec: `docs/superpowers/specs/2026-05-04-fk-cesis-mms-mvp-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-04-fk-cesis-mms-mvp-implementation.md`
- Milestones: `docs/milestones.md`

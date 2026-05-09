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
```

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

**Tasks 1–6 complete, and P1 (field contract + guardian-email-first verified registration gate) is now complete.** Registration workflow is usable for LAN acceptance testing.

- `apps/` contains `core`, `accounts`, `registrations`, `members`, `billing`, `documents`, and `integrations`
- `apps/core/models.py` defines the abstract `TimeStampedModel` base model
- `apps/accounts/models.py` defines `ParentAccount`, `MagicLinkToken`, and `EmailVerificationCode`
- `apps/accounts/services.py` provides magic-link helpers plus one-time code issue/send/verify services
- `apps/accounts/views.py` provides request, verify, logout, and one-time code verification views
- `apps/accounts/management/commands/ensure_admin_user.py` for env-driven admin creation
- `apps/registrations/models.py` defines `RegistrationApplication` with finalized P1 guardian/member/application snapshot fields plus admin review workflow metadata
- `apps/registrations/services.py` implements P1 application lifecycle, same-address handling, chooser/prefill support, and admin review actions
- `apps/registrations/views.py` provides guardian email entry, new/edit registration, parent chooser portal, and admin review views
- `apps/members/models.py` defines `Member`, `Guardian`, `TrainingGroup`, and `KitSizeOption`
- `apps/documents/models.py` defines `Document` with private storage (`PRIVATE_DOCUMENTS_ROOT`), P1 document kinds, and placeholder OCR status
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

### Task 6 follow-up debt
- Revisit desktop typography in Task 6 UI pass: blue text renders too heavy/thick on desktop and needs refinement.

### Next task
P2 visual system + registration UX redesign, production email delivery setup, and agreement-handling first slice remain active follow-up work.

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
- Historical plans archive: `docs/archive/plans/` *(read only when explicitly needed for history)*

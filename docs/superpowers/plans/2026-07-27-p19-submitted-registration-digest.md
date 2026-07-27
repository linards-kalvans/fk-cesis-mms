# P19 — Daily Submitted-Registration Digest: Implementation Plan

**Date:** 2026-07-27
**Status:** Implementation accepted by focused tests + code review. After a PostgreSQL CI lock regression, full CI-equivalent PostgreSQL verification passed locally on 2026-07-27: `1855 passed`; ruff, mypy, and migration check clean. GitHub CI rerun and LAN acceptance pending.

## 1. Task Breakdown

### Task 0 — Red tests

**Files:**
- `tests/registrations/test_submission_digest.py` — task selection, Bcc privacy, current-status rendering, retry state, runtime recipient filtering, and admin permissions.
- `tests/registrations/test_submission_digest_schedule.py` — singleton and Schedule seed/idempotency contract.
- `tests/registrations/test_application_workflow.py` — correction-resubmission flag reset regression.

**Red-phase verification:**
```bash
uv run pytest tests/registrations/test_submission_digest.py \
  tests/registrations/test_submission_digest_schedule.py \
  tests/registrations/test_application_workflow.py::TestResubmissionClearsDigestSentAt -q
```

### Task 1 — Schema (model + migration)

**Files:**
- `apps/registrations/models.py` — add `submission_digest_sent_at` (nullable DateTimeField) to `RegistrationApplication`; add `RegistrationSubmissionDigestSettings` model (singleton, `last_successful_at`, M2M `recipients` with `limit_choices_to`).
- `apps/registrations/migrations/0012_submission_digest_settings.py` — AddField + CreateModel + `RunPython` to seed singleton (pk=1) + django-q2 Schedule (`registrations-submission-digest`, DAILY, next_run ≈ 08:00 Europe/Riga).

**Verification:**
```bash
uv run python manage.py makemigrations --check  # should pass (migration committed)
uv run python manage.py migrate  # apply migration cleanly
```

### Task 2 — Template

**Files:**
- `templates/emails/registrations/submission_digest.txt` — plain-text Latvian template. Per-entry: child name, guardian name, Riga datetime (`%Y-%m-%d %H:%M`), status display, admin URL. Loop over `{% for entry in entries %}`.

**Verification:**
```bash
uv run python manage.py shell -c "
from django.template.loader import render_to_string
r = render_to_string('emails/registrations/submission_digest.txt', {
    'entries': [{'child': 'Jānis', 'guardian': 'Māra', 'submitted_at': '2026-07-27 10:30', 'status': 'Iesniegts', 'admin_url': 'http://localhost/admin/registrations/registrationapplication/1/change/'}]
})
assert 'Jānis' in r
assert 'Māra' in r
assert 'admin' in r
"
```

### Task 3 — Service layer (flag clearing on submit)

**Files:**
- `apps/registrations/services.py` — `submit_application()`: after setting `submitted_at`, also set `submission_digest_sent_at = None` and include it in `update_fields`.

**Verification:**
```bash
uv run pytest tests/registrations/test_application_workflow.py::TestResubmissionClearsDigestSentAt -q
```

### Task 4 — Background job (tasks.py)

**Files:**
- `apps/registrations/tasks.py` — `send_submitted_registration_digest()` function:
  1. Lock singleton (`select_for_update().get(pk=1)`).
  2. Select pending rows (`submitted_at IS NOT NULL, submission_digest_sent_at IS NULL`) with `select_for_update()`.
  3. Re-query recipients at runtime (active staff only).
   4. Build data-minimised entries via `_build_entries()`.
  5. Render template.
  6. Send `EmailMessage(bcc=[…])` with `fail_silently=False`.
  7. On success (`sent == 1`): stamp per-row + singleton.
  8. On failure: log ERROR, return 0, flags untouched.

**Verification:**
```bash
uv run pytest tests/registrations/test_submission_digest.py -q
```

### Task 5 — Admin interface

**Files:**
- `apps/registrations/admin.py` — `RegistrationSubmissionDigestSettingsAdmin`: superuser-only (`has_view_permission`, `has_change_permission`), no add/delete, `filter_horizontal` on recipients, `formfield_for_manytomany` restricted to active staff Users.

**Verification:**
```bash
uv run pytest tests/registrations/test_submission_digest.py -q
```

### Task 6 — Documentation + gates

**Files:**
- `docs/superpowers/specs/2026-07-27-p19-submitted-registration-digest-design.md` — design spec (above).
- `docs/milestones.md` — add P19 entry after P18 with correct status.
- `AGENTS.md` — add P19 current-status entry.

## 2. Verification Commands

### Focused tests (accepted)
```bash
uv run pytest -q tests/registrations/test_submission_digest*.py -xvs
```

### Full CI-equivalent PostgreSQL gate (passed locally 2026-07-27)
```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

### Migration verification
```bash
uv run python manage.py makemigrations --check
uv run python manage.py migrate
```

### Manual LAN acceptance (PENDING)
1. Configure recipients in admin (superuser).
2. Submit a draft application.
3. Run `send_submitted_registration_digest()` manually via shell or wait for next scheduled run.
4. Verify staff inbox receives one Bcc email with allowed fields only; contact, identity, address, document, and review-message data must be absent.
5. Verify `submission_digest_sent_at` is stamped on the application.
6. Verify re-submit clears the flag and the next run includes it again.
7. Verify with no recipients, the job returns 0 and flags stay `NULL`.

## 3. Files Changed

| File | Change |
|------|--------|
| `apps/registrations/models.py` | Added `submission_digest_sent_at` + `RegistrationSubmissionDigestSettings` |
| `apps/registrations/migrations/0012_submission_digest_settings.py` | Schema migration + singleton/Schedule seed |
| `apps/registrations/services.py` | `submit_application()` clears digest flag on submit |
| `apps/registrations/tasks.py` | `send_submitted_registration_digest()` job + `_build_entries()` helper |
| `apps/registrations/admin.py` | `RegistrationSubmissionDigestSettingsAdmin` (superuser-only) |
| `templates/emails/registrations/submission_digest.txt` | Plain-text Latvian email template |
| `tests/registrations/test_submission_digest.py` | Digest behavior, privacy, retry, and admin tests |
| `tests/registrations/test_submission_digest_schedule.py` | Singleton/Schedule seed tests |
| `tests/registrations/test_application_workflow.py` | Re-submit flag-reset regression |
| `docs/superpowers/specs/2026-07-27-p19-submitted-registration-digest-design.md` | Design spec (new) |
| `docs/superpowers/plans/2026-07-27-p19-submitted-registration-digest.md` | This plan |
| `docs/milestones.md` | P19 entry added |
| `AGENTS.md` | P19 current-status entry added |

## 4. Open Items

| Item | Status |
|------|--------|
| Full CI-equivalent PostgreSQL verification | Passed locally 2026-07-27 — 1855 tests; ruff, mypy, migration check clean. GitHub CI rerun pending. |
| LAN acceptance (live instance) | Pending |
| Schedule time default (08:00 Riga) | Migration seed; admin-editable after deploy |
| SMTP configuration for `DEFAULT_FROM_EMAIL` | Operational (env, not in scope) |

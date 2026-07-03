# P5 Slice B — Training-Group Assignment Workflow

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline training-group assignment to the admin review-detail page — bundled into the approval form for one-click approve+assign, and as a standalone post-approval module for change/clear — backed by a clean service layer. Enrich the approval email with the assigned group name.

**Architecture:** Two services (`apps/members/services.py::assign_training_group` for standalone changes; extended `apps/registrations/services.py::approve_application` accepting an optional `training_group`). One view (`apps/registrations/views.py::admin_review_detail`) grows context entries + a new `assign_training_group` POST branch. The Django-admin-shell review-detail template adds (a) a `<select>` inside the existing approve form and (b) a new post-approval "Treniņu grupa" module. The existing `_render_and_send_notification` helper is template-driven, so the approval email enrichment is a one-line conditional in `templates/emails/registrations/approve.txt`. No schema change, no migration, no new dependencies.

**Tech Stack:** Django 5.x, pytest + pytest-django, ruff, mypy, uv. Branch: `dev`. Base SHA: `51cd0c4` (the Slice B spec commit). All work lands on `dev`; nothing is pushed by tasks below.

**Spec reference:** `docs/superpowers/specs/2026-05-28-p5-slice-b-training-group-assignment-design.md`.

**Baseline test count:** `891` passing. Target after this slice: `~913` (slice adds ~22 tests across four files).

**Pre-existing fixtures to reuse (do NOT recreate):**
- `tests/conftest.py` provides cross-app fixtures including `staff_client` (a logged-in staff test client) and `verified_client` (a verified parent test client).
- `tests/registrations/conftest.py` provides `submitted_application` (a fresh `RegistrationApplication` in SUBMITTED status with documents attached) and several siblings (`draft_application`, `fix_requested_application`, `rejected_application`).
- The new `tests/members/conftest.py` (Task 1) adds members-app fixtures: `guardian`, `member`, `training_group_a`, `training_group_b`, `inactive_training_group`.
- A local `reviewer` fixture (`User.objects.create_user(username="staff", is_staff=True)`) appears in Tasks 2, 3, and 4 — keep it local per file rather than promoting it to a shared conftest; it's only needed inside the three new test files.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `apps/members/services.py` | **Create** | `assign_training_group(member, group, actor)` — sets/clears `Member.training_group`, idempotent, no notification. |
| `apps/registrations/services.py` | Modify | Extend `approve_application` to accept optional `training_group`; raise `ValueError` on inactive group. |
| `apps/registrations/views.py` | Modify | Extend `admin_review_detail` context with `active_training_groups` + `current_inactive_group`; add `assign_training_group` POST branch; thread `training_group` into `approve_application` call. |
| `templates/registrations/admin_review_detail.html` | Modify | Add `<select name="training_group">` inside the existing approve form; add post-approval Treniņu grupa module. |
| `templates/emails/registrations/approve.txt` | Modify | Conditional `Treniņu grupa: {{ … }}.` line. |
| `static/admin/css/review.css` | Modify | Small additions: `.mms-review-group-module`, picker spacing. |
| `tests/members/conftest.py` | **Create** | Shared fixtures: `training_group_a`, `training_group_b`, `inactive_training_group`, `guardian`, `member`. |
| `tests/members/test_assign_training_group_service.py` | **Create** | Service-level behavior. |
| `tests/registrations/test_admin_approval_with_group.py` | **Create** | `approve_application` extension behavior. |
| `tests/registrations/test_admin_review_group_assignment_ui.py` | **Create** | End-to-end view + template behavior for both approve+assign and post-approval reassign. |
| `tests/registrations/test_review_action_emails.py` | Modify | Two new tests for approve-email enrichment. |

Each test file is single-responsibility, so the suite stays grep-friendly. The service file is created up front so tests in Tasks 1 and 2 reference real symbols.

---

## Task 1 — `assign_training_group` service + members fixtures

**Files:**
- Create: `apps/members/services.py`
- Create: `tests/members/conftest.py`
- Create: `tests/members/test_assign_training_group_service.py`

- [ ] **Step 1.1: Create `tests/members/conftest.py` with fixtures**

```python
"""Shared fixtures for tests/members/."""

from __future__ import annotations

import pytest

from apps.members.models import Guardian, Member, TrainingGroup


@pytest.fixture
def guardian(db):
    return Guardian.objects.create(
        full_name="Anna Bērziņa",
        personal_id="111111-11111",
        email="anna@example.test",
        phone="+37120000000",
        address="Rīgas iela 1, Cēsis",
    )


@pytest.fixture
def member(db, guardian):
    return Member.objects.create(
        full_name="Jānis Bērziņš",
        personal_id="151210-22222",
        birth_date="2015-12-10",
        guardian=guardian,
        training_group=None,
    )


@pytest.fixture
def training_group_a(db):
    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def training_group_b(db):
    return TrainingGroup.objects.create(name="U10 B", is_active=True)


@pytest.fixture
def inactive_training_group(db):
    return TrainingGroup.objects.create(name="U10 Arhīvs", is_active=False)
```

- [ ] **Step 1.2: Write failing tests in `tests/members/test_assign_training_group_service.py`**

```python
"""Tests for apps.members.services.assign_training_group."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User

from apps.members.services import assign_training_group


pytestmark = pytest.mark.django_db


@pytest.fixture
def actor(db):
    return User.objects.create_user(username="staff", is_staff=True)


def test_assign_group_to_member_with_no_group(member, training_group_a, actor):
    result = assign_training_group(member, training_group_a, actor)
    member.refresh_from_db()
    assert member.training_group_id == training_group_a.id
    assert result.pk == member.pk


def test_reassign_from_one_group_to_another(member, training_group_a, training_group_b, actor):
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])
    assign_training_group(member, training_group_b, actor)
    member.refresh_from_db()
    assert member.training_group_id == training_group_b.id


def test_clear_assignment_with_none(member, training_group_a, actor):
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])
    assign_training_group(member, None, actor)
    member.refresh_from_db()
    assert member.training_group is None


def test_idempotent_when_already_assigned_to_same_group(member, training_group_a, actor):
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])
    # Returning early is the only observable guarantee — we assert that no
    # extra UPDATE happens by capturing the queries.
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        assign_training_group(member, training_group_a, actor)
    update_queries = [q for q in ctx.captured_queries if "UPDATE" in q["sql"].upper()]
    assert update_queries == []


def test_idempotent_when_clearing_already_clear_member(member, actor):
    assert member.training_group is None
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        assign_training_group(member, None, actor)
    update_queries = [q for q in ctx.captured_queries if "UPDATE" in q["sql"].upper()]
    assert update_queries == []


def test_inactive_group_allowed_at_service_layer(member, inactive_training_group, actor):
    """Service layer is permissive — picker filtering is the view's job."""
    assign_training_group(member, inactive_training_group, actor)
    member.refresh_from_db()
    assert member.training_group_id == inactive_training_group.id
```

- [ ] **Step 1.3: Run tests, confirm they fail**

```bash
uv run pytest tests/members/test_assign_training_group_service.py -v
```

Expected: ImportError / ModuleNotFoundError on `apps.members.services` (file doesn't exist yet).

- [ ] **Step 1.4: Create `apps/members/services.py`**

```python
"""Service functions for the members domain."""

from __future__ import annotations

from django.conf import settings

from apps.members.models import Member, TrainingGroup


def assign_training_group(
    member: Member,
    group: TrainingGroup | None,
    actor: settings.AUTH_USER_MODEL,  # noqa: ARG001 — plumbed for future P7 audit hook
) -> Member:
    """Set or clear a member's training group. Idempotent.

    Service layer is intentionally permissive: it does not reject inactive
    groups. The view layer's picker filters for active groups; this service
    accepts whatever it is given so administrators can deliberately keep an
    inactive (legacy) assignment in place.
    """
    current_id = member.training_group_id
    new_id = group.id if group is not None else None
    if current_id == new_id:
        return member
    member.training_group = group
    member.save(update_fields=["training_group"])
    return member
```

- [ ] **Step 1.5: Run tests, confirm they pass**

```bash
uv run pytest tests/members/test_assign_training_group_service.py -v
```

Expected: 6 passed.

- [ ] **Step 1.6: Run full suite + lint + types**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected: ≥897 passing (891 baseline + 6 new), ruff + mypy clean.

- [ ] **Step 1.7: Commit**

```bash
git add apps/members/services.py tests/members/conftest.py tests/members/test_assign_training_group_service.py
git commit -m "$(cat <<'EOF'
feat(members): assign_training_group service (P5 Slice B)

Idempotent set/clear of Member.training_group. Service layer is permissive
on inactive groups — picker filtering happens at the view layer. The actor
parameter is plumbed but unused this slice (P7 audit hook).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Extend `approve_application` to accept `training_group`

**Files:**
- Modify: `apps/registrations/services.py:692-733` (the `approve_application` function)
- Create: `tests/registrations/test_admin_approval_with_group.py`

- [ ] **Step 2.1: Write failing tests**

```python
"""Tests for the training_group argument extension of approve_application."""

from __future__ import annotations

import pytest

from apps.members.models import TrainingGroup
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def training_group_a(db):
    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def inactive_group(db):
    return TrainingGroup.objects.create(name="U10 Arhīvs", is_active=False)


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


def test_approve_without_group_creates_member_with_no_group(submitted_application, reviewer):
    """Regression: existing call site signature still works."""
    app = approve_application(submitted_application, reviewer)
    assert app.approved_member is not None
    assert app.approved_member.training_group is None


def test_approve_with_active_group_assigns_member(submitted_application, reviewer, training_group_a):
    app = approve_application(submitted_application, reviewer, training_group=training_group_a)
    assert app.approved_member is not None
    assert app.approved_member.training_group_id == training_group_a.id


def test_approve_with_inactive_group_raises_value_error(submitted_application, reviewer, inactive_group):
    with pytest.raises(ValueError, match="inactive"):
        approve_application(submitted_application, reviewer, training_group=inactive_group)

    # And no Member was created — application stayed submitted.
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.SUBMITTED
    assert submitted_application.approved_member_id is None


def test_idempotent_reapprove_ignores_different_group(submitted_application, reviewer, training_group_a):
    other_group = TrainingGroup.objects.create(name="U10 C", is_active=True)
    first = approve_application(submitted_application, reviewer, training_group=training_group_a)
    assigned_member_id = first.approved_member_id
    assigned_group_id = first.approved_member.training_group_id

    # Second call with a different group must not mutate.
    second = approve_application(submitted_application, reviewer, training_group=other_group)
    assert second.approved_member_id == assigned_member_id
    second.approved_member.refresh_from_db()
    assert second.approved_member.training_group_id == assigned_group_id
```

- [ ] **Step 2.2: Run tests, confirm they fail**

```bash
uv run pytest tests/registrations/test_admin_approval_with_group.py -v
```

Expected: `test_approve_with_active_group_assigns_member` and `test_approve_with_inactive_group_raises_value_error` fail (the `training_group` kwarg isn't accepted). Other tests may pass or also fail — that's fine.

- [ ] **Step 2.3: Update `approve_application` in `apps/registrations/services.py`**

Find the function near line 692. Update the signature and body:

```python
def approve_application(
    application: RegistrationApplication,
    reviewer: settings.AUTH_USER_MODEL,
    training_group: "TrainingGroup | None" = None,
) -> RegistrationApplication:
    """Approve an application, creating Guardian + Member. Idempotent.

    Optionally assigns the new Member to a TrainingGroup at create-time.
    Idempotent re-approval ignores the training_group argument — assignment
    edits go through apps.members.services.assign_training_group.
    """
    # Idempotent: if already approved with linked member, return as-is
    if application.approved_member_id is not None:
        return application

    if application.status != RegistrationApplication.Status.SUBMITTED:
        raise ValueError("can only approve submitted application")

    if training_group is not None and not training_group.is_active:
        raise ValueError("cannot assign inactive training group at approval time")

    # Create Guardian from application guardian data
    guardian = Guardian.objects.create(
        full_name=application.guardian_full_name,
        personal_id=application.guardian_personal_id,
        email=application.guardian_email,
        phone=application.guardian_phone,
        address=application.guardian_declared_address,
    )

    # Create Member linked to Guardian, optionally to a TrainingGroup
    member = Member.objects.create(
        full_name=application.member_full_name,
        personal_id=application.member_personal_id,
        birth_date=application.member_birth_date,
        guardian=guardian,
        training_group=training_group,
    )

    application.status = RegistrationApplication.Status.APPROVED
    application.approved_member = member
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(
        update_fields=[
            "status",
            "approved_member_id",
            "reviewed_by_id",
            "reviewed_at",
            "updated_at",
        ]
    )

    _render_and_send_notification(
        application,
        template_name="approve",
        subject="Jūsu pieteikums ir apstiprināts",
    )
    return application
```

Also ensure `from apps.members.models import Guardian, KitSizeOption, Member, TrainingGroup` includes `TrainingGroup` (it currently does not — verify by reading the existing import line near the top of `apps/registrations/services.py` and add `TrainingGroup` if missing). The string-form annotation `"TrainingGroup | None"` removes the need for the import to be at the top, but importing it cleanly is preferable; use whichever keeps the test green.

- [ ] **Step 2.4: Run failing tests + full suite**

```bash
uv run pytest tests/registrations/test_admin_approval_with_group.py -v
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected: all 4 new tests pass; full suite ≥901 passing.

- [ ] **Step 2.5: Commit**

```bash
git add apps/registrations/services.py tests/registrations/test_admin_approval_with_group.py
git commit -m "$(cat <<'EOF'
feat(registrations): approve_application accepts optional training_group (P5 Slice B)

Bundled approve+assign path. Inactive groups rejected with ValueError at
approval time. Idempotency rule unchanged: re-approval ignores the
training_group argument; assignment edits go through assign_training_group.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Approve-email enrichment

**Files:**
- Modify: `templates/emails/registrations/approve.txt`
- Modify: `tests/registrations/test_review_action_emails.py` (extend with 2 tests)

- [ ] **Step 3.1: Add the two failing tests to `tests/registrations/test_review_action_emails.py`**

Open the existing file, locate the existing `TestApproveEmail` (or equivalent) class / function, and append:

```python
def test_approve_email_includes_training_group_when_assigned(
    submitted_application, reviewer, mailoutbox
):
    from apps.members.models import TrainingGroup
    from apps.registrations.services import approve_application

    group = TrainingGroup.objects.create(name="U10 A", is_active=True)
    approve_application(submitted_application, reviewer, training_group=group)

    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    assert "Treniņu grupa: U10 A." in body


def test_approve_email_omits_training_group_when_unassigned(
    submitted_application, reviewer, mailoutbox
):
    from apps.registrations.services import approve_application

    approve_application(submitted_application, reviewer)

    assert len(mailoutbox) == 1
    body = mailoutbox[0].body
    assert "Treniņu grupa" not in body
```

If the existing file uses a different `reviewer` fixture name or doesn't have one, add it inline using the pattern at the top of the file (or read `tests/conftest.py` to find the cross-app staff fixture — `staff_client` exists but we need a `User`; the simplest is to mirror Task 2's local `reviewer` fixture).

If `mailoutbox` is not the established fixture name in this file, use the same fixture the existing email tests use (likely `django.core.mail.outbox` accessed via `from django.core import mail` then `mail.outbox[0]`).

- [ ] **Step 3.2: Run the two new tests, confirm they fail**

```bash
uv run pytest tests/registrations/test_review_action_emails.py::test_approve_email_includes_training_group_when_assigned tests/registrations/test_review_action_emails.py::test_approve_email_omits_training_group_when_unassigned -v
```

Expected: first one fails on the "Treniņu grupa: U10 A." assertion (template doesn't render it yet). Second one passes (template never has "Treniņu grupa" today) — that's fine; we want it to keep passing after the template change.

- [ ] **Step 3.3: Edit `templates/emails/registrations/approve.txt`**

Read the current template first (`cat templates/emails/registrations/approve.txt`). Find the line containing "ir pievienots kluba dalībnieku reģistram." (set by Slice A.1). Immediately after that line, before the blank line that separates it from the next paragraph, add:

```
{% if application.approved_member.training_group %}Treniņu grupa: {{ application.approved_member.training_group.name }}.
{% endif %}
```

The `{% if %}` and `{% endif %}` are on their own lines so when the conditional is false there's no extra blank line in the rendered output. Verify by running the existing email-rendering tests after the change.

- [ ] **Step 3.4: Run the two new tests + the full email test file**

```bash
uv run pytest tests/registrations/test_review_action_emails.py -v
```

Expected: all tests in the file pass (existing + 2 new).

- [ ] **Step 3.5: Run full suite + lint + types**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected: ≥903 passing.

- [ ] **Step 3.6: Commit**

```bash
git add templates/emails/registrations/approve.txt tests/registrations/test_review_action_emails.py
git commit -m "$(cat <<'EOF'
feat(registrations): approve email names the assigned training group (P5 Slice B)

Conditional one-liner in approve.txt. Reassignment and standalone
post-approval first-assignment remain silent (per spec).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — View + template + CSS

**Files:**
- Modify: `apps/registrations/views.py` (`admin_review_detail`)
- Modify: `templates/registrations/admin_review_detail.html`
- Modify: `static/admin/css/review.css`
- Create: `tests/registrations/test_admin_review_group_assignment_ui.py`

- [ ] **Step 4.1: Write failing tests**

```python
"""End-to-end view + template tests for training-group assignment UI."""

from __future__ import annotations

import re

import pytest

from apps.members.models import TrainingGroup
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True)


@pytest.fixture
def group_a(db):
    return TrainingGroup.objects.create(name="U10 A", is_active=True)


@pytest.fixture
def group_b(db):
    return TrainingGroup.objects.create(name="U10 B", is_active=True)


@pytest.fixture
def inactive_group(db):
    return TrainingGroup.objects.create(name="U10 Arhīvs", is_active=False)


def _detail_url(app_id):
    from django.urls import reverse

    return reverse("registrations:admin-review-detail", args=[app_id])


# --- Submitted application: approve-form dropdown ---


def test_submitted_app_dropdown_contains_active_groups_only(
    submitted_application, staff_client, group_a, group_b, inactive_group
):
    resp = staff_client.get(_detail_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert 'name="training_group"' in html
    assert '— Piešķirsim vēlāk —' in html
    assert "U10 A" in html
    assert "U10 B" in html
    assert "U10 Arhīvs" not in html


def test_approve_post_with_group_assigns_member(
    submitted_application, staff_client, group_a
):
    resp = staff_client.post(
        _detail_url(submitted_application.id),
        {"action": "approve", "training_group": str(group_a.id)},
    )
    assert resp.status_code in (302, 200)  # redirect to queue
    submitted_application.refresh_from_db()
    assert submitted_application.approved_member is not None
    assert submitted_application.approved_member.training_group_id == group_a.id


def test_approve_post_with_empty_group_leaves_member_unassigned(
    submitted_application, staff_client
):
    resp = staff_client.post(
        _detail_url(submitted_application.id),
        {"action": "approve", "training_group": ""},
    )
    assert resp.status_code in (302, 200)
    submitted_application.refresh_from_db()
    assert submitted_application.approved_member is not None
    assert submitted_application.approved_member.training_group is None


# --- Approved application: post-approval module ---


def test_approved_app_without_group_shows_unassigned_message_and_picker(
    submitted_application, staff_client, reviewer
):
    approve_application(submitted_application, reviewer)
    resp = staff_client.get(_detail_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "Treniņu grupa" in html
    assert "Vēl nav piešķirta" in html
    assert 'name="training_group"' in html
    assert 'value="assign_training_group"' in html


def test_approved_app_with_group_shows_current_and_preselects_option(
    submitted_application, staff_client, reviewer, group_a, group_b
):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = staff_client.get(_detail_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert f"Pašreizējā grupa:" in html
    assert "U10 A" in html
    # Pre-selection on the matching option:
    assert re.search(r'<option[^>]+value="' + str(group_a.id) + r'"[^>]*selected', html)


def test_assign_post_updates_member_group(
    submitted_application, staff_client, reviewer, group_a, group_b
):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = staff_client.post(
        _detail_url(submitted_application.id),
        {"action": "assign_training_group", "training_group": str(group_b.id)},
    )
    assert resp.status_code in (302, 200)
    submitted_application.refresh_from_db()
    submitted_application.approved_member.refresh_from_db()
    assert submitted_application.approved_member.training_group_id == group_b.id


def test_assign_post_with_empty_clears_member_group(
    submitted_application, staff_client, reviewer, group_a
):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = staff_client.post(
        _detail_url(submitted_application.id),
        {"action": "assign_training_group", "training_group": ""},
    )
    assert resp.status_code in (302, 200)
    submitted_application.approved_member.refresh_from_db()
    assert submitted_application.approved_member.training_group is None


def test_currently_inactive_group_appears_in_picker_with_marker(
    submitted_application, staff_client, reviewer, group_a, inactive_group
):
    # Approve, then manually demote the assigned group to inactive.
    approve_application(submitted_application, reviewer, training_group=group_a)
    group_a.is_active = False
    group_a.save(update_fields=["is_active"])

    resp = staff_client.get(_detail_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    # The inactive currently-assigned group appears in the picker:
    assert "U10 A" in html
    assert "neaktīva" in html
    # Marker attribute on its option:
    assert re.search(
        r'<option[^>]+value="' + str(group_a.id) + r'"[^>]+data-inactive="true"',
        html,
    )


def test_anonymous_assign_post_is_blocked(submitted_application, client, reviewer, group_a):
    approve_application(submitted_application, reviewer, training_group=group_a)
    resp = client.post(
        _detail_url(submitted_application.id),
        {"action": "assign_training_group", "training_group": ""},
    )
    # Existing access-control gives 404 / redirect; both are acceptable.
    assert resp.status_code in (302, 404)
    submitted_application.approved_member.refresh_from_db()
    assert submitted_application.approved_member.training_group_id == group_a.id  # unchanged
```

- [ ] **Step 4.2: Run tests, confirm they fail meaningfully**

```bash
uv run pytest tests/registrations/test_admin_review_group_assignment_ui.py -v
```

Expected: most fail because the view doesn't pass `active_training_groups` and the template renders no `<select>`. Read the failures, confirm they're contract failures (not infrastructure errors).

- [ ] **Step 4.3: Update `apps/registrations/views.py::admin_review_detail`**

Locate the function near line 536. Make these changes (do not retype the whole function — apply targeted edits):

**3a. Import additions at the top of the file** (verify they aren't already present):

```python
from apps.members.models import TrainingGroup
from apps.members.services import assign_training_group
```

**3b. Inside `admin_review_detail`, after the OCR decryption block and before the `context = {...}` dict construction, add:**

```python
active_training_groups = list(
    TrainingGroup.objects.filter(is_active=True).order_by("name")
)

current_inactive_group = None
if application.approved_member_id is not None:
    assigned = application.approved_member.training_group
    if assigned is not None and not assigned.is_active:
        current_inactive_group = assigned
```

**3c. Add the two new keys to the `context` dict** (find the existing `context = {...}` literal):

```python
"active_training_groups": active_training_groups,
"current_inactive_group": current_inactive_group,
```

**3d. In the POST handler block (currently dispatching on `action in ("request_fix", "reject", "approve")`), update the `"approve"` branch and add a new `"assign_training_group"` branch.** The exact code, replacing the existing `"approve"` branch:

```python
elif action == "approve":
    raw_group = request.POST.get("training_group", "").strip()
    selected_group = None
    if raw_group:
        try:
            selected_group = TrainingGroup.objects.get(pk=int(raw_group))
        except (TrainingGroup.DoesNotExist, ValueError):
            return render(
                request,
                "registrations/admin_review_detail.html",
                {**context, "error": "Nezināma treniņu grupa."},
                status=400,
            )
    try:
        approve_application(application, request.user, training_group=selected_group)
    except ValueError as exc:
        return render(
            request,
            "registrations/admin_review_detail.html",
            {**context, "error": str(exc)},
            status=400,
        )
    return redirect("registrations:admin-review-queue")

elif action == "assign_training_group":
    if application.approved_member_id is None:
        return render(
            request,
            "registrations/admin_review_detail.html",
            {**context, "error": "Var piešķirt grupu tikai apstiprinātam pieteikumam."},
            status=400,
        )
    raw_group = request.POST.get("training_group", "").strip()
    selected_group = None
    if raw_group:
        try:
            selected_group = TrainingGroup.objects.get(pk=int(raw_group))
        except (TrainingGroup.DoesNotExist, ValueError):
            return render(
                request,
                "registrations/admin_review_detail.html",
                {**context, "error": "Nezināma treniņu grupa."},
                status=400,
            )
    assign_training_group(application.approved_member, selected_group, request.user)
    return redirect("registrations:admin-review-detail", application_id=application.id)
```

Verify the existing `approve_application` import already covers the new keyword usage. No other view changes needed.

- [ ] **Step 4.4: Update `templates/registrations/admin_review_detail.html`**

**4a. Inside the existing approve form** (find `<form method="post" class="mms-review-actions__form">` containing the `value="approve"` button), insert this block before the submit button:

```html
<div class="form-row mms-review-group-pick">
  <label for="approve_training_group">Treniņu grupa (neobligāti):</label>
  <select name="training_group" id="approve_training_group">
    <option value="">— Piešķirsim vēlāk —</option>
    {% for grp in active_training_groups %}
      <option value="{{ grp.id }}">{{ grp.name }}</option>
    {% endfor %}
  </select>
</div>
```

**4b. Add a new post-approval module** anywhere after the existing review-message module and before the `<script>` tag at the bottom of `{% block content %}`. Use this template block (replacing the existing `{% if application.status == "submitted" %}` opening if needed — the new block uses `{% if application.approved_member %}` instead):

```html
{% if application.approved_member %}
<div class="module mms-review-group-module">
  <h2>Treniņu grupa</h2>
  {% if application.approved_member.training_group %}
    <p>Pašreizējā grupa: <strong>{{ application.approved_member.training_group.name }}</strong>{% if current_inactive_group %} <em>(neaktīva)</em>{% endif %}</p>
  {% else %}
    <p>Vēl nav piešķirta.</p>
  {% endif %}

  <form method="post" class="mms-review-actions__form">
    {% csrf_token %}
    <div class="form-row">
      <label for="reassign_training_group">Mainīt grupu:</label>
      <select name="training_group" id="reassign_training_group">
        <option value="">— Notīrīt piešķīrumu —</option>
        {% for grp in active_training_groups %}
          <option value="{{ grp.id }}"{% if application.approved_member.training_group_id == grp.id %} selected{% endif %}>{{ grp.name }}</option>
        {% endfor %}
        {% if current_inactive_group %}
          <option value="{{ current_inactive_group.id }}" selected data-inactive="true">{{ current_inactive_group.name }} (neaktīva)</option>
        {% endif %}
      </select>
    </div>
    <button type="submit" name="action" value="assign_training_group" class="default">Saglabāt</button>
  </form>
</div>
{% endif %}
```

- [ ] **Step 4.5: Update `static/admin/css/review.css` — add this block at the end of the file**

```css
/* P5 Slice B — training-group assignment */
.mms-review-group-module .form-row { margin: 8px 0; }
.mms-review-group-module .mms-review-actions__form select,
.mms-review-actions .mms-review-group-pick select { min-width: 200px; }
.mms-review-group-module em { color: #999; font-style: italic; margin-left: 4px; }
```

- [ ] **Step 4.6: Run the UI tests**

```bash
uv run pytest tests/registrations/test_admin_review_group_assignment_ui.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 4.7: Run full suite + lint + types**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected: ≥913 passing (903 after Task 3 + 10 new). Ruff + mypy clean.

If any pre-existing admin-review test breaks because of the new context keys or the new approve-form layout, update the affected assertions in those test files (do not weaken coverage). Likely candidate: `tests/registrations/test_admin_review_flow.py` if it scans the action form's HTML. The approve POST still accepts the same `action=approve` value, so workflow tests should be unaffected.

- [ ] **Step 4.8: Commit**

Split into two commits if the diff is large; otherwise one commit is fine:

```bash
git add apps/registrations/views.py templates/registrations/admin_review_detail.html static/admin/css/review.css tests/registrations/test_admin_review_group_assignment_ui.py
git commit -m "$(cat <<'EOF'
feat(registrations): training-group picker on admin review detail (P5 Slice B)

Approve form gains an optional training_group dropdown (active groups
only + "Piešķirsim vēlāk"). Post-approval review detail adds a Treniņu
grupa module with current state + reassign/clear picker; currently-
assigned-inactive groups surface with a (neaktīva) marker and
data-inactive="true" so existing state is never hidden.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — Final verification, docs, and self-review

**Files:**
- Modify: `AGENTS.md` (Current Status — add P5 Slice B delivered entry)
- Modify: `docs/milestones.md` (P5 status block — mark Slice B delivered)

- [ ] **Step 5.1: Run all gates one more time**

```bash
uv run pytest -q && uv run ruff check . && uv run mypy .
```

Expected: ≥913 passing, ruff + mypy clean.

- [ ] **Step 5.2: Update `AGENTS.md`**

Find the latest "P5 Slice A delivered" entry block (it currently includes Revision A + Slice A.1 as bullets within it). After the closing line of that block (the "Full repo verification … `891 passed`" line), insert a new entry following the same shape:

```markdown
- **P5 Slice B delivered — training-group assignment workflow (2026-05-28)**
  - Closes P5 acceptance item 3. Items 5, 7, 11 → Slice C; items 6, 8, 9, 10 → Slice D.
  - New service `apps/members/services.py::assign_training_group(member, group, actor)` — idempotent set/clear of `Member.training_group`. Service layer is permissive (accepts inactive groups; picker filtering happens at the view). The `actor` parameter is plumbed but unused this slice (forward-compat with the P7 audit hook).
  - `apps/registrations/services.py::approve_application` extended to accept an optional `training_group: TrainingGroup | None = None` kwarg. On first approval, passes it into `Member.objects.create(...)`. Inactive groups rejected with `ValueError` at approval time (defensive — the picker already filters). Idempotency rule unchanged: re-approval ignores the kwarg; assignment edits go through `assign_training_group`.
  - `apps/registrations/views.py::admin_review_detail` gains `active_training_groups` and `current_inactive_group` context entries, plus a new `action == "assign_training_group"` POST branch. The existing `action == "approve"` branch now reads an optional `training_group` from POST.
  - `templates/registrations/admin_review_detail.html` adds (a) a `<select name="training_group">` inside the existing approve form with a "— Piešķirsim vēlāk —" empty option, and (b) a new post-approval `Treniņu grupa` module with current-state copy + reassign/clear picker. Currently-assigned-but-inactive groups appear in the picker as a pre-selected option with `data-inactive="true"` and a `(neaktīva)` marker so existing state is never hidden.
  - `templates/emails/registrations/approve.txt` gains a conditional `Treniņu grupa: {{ application.approved_member.training_group.name }}.` line. Standalone post-approval first-assignment and reassignment stay silent (no email).
  - `static/admin/css/review.css` gains a small `.mms-review-group-module` / `.mms-review-group-pick` block.
  - New tests: `tests/members/conftest.py` (shared fixtures), `tests/members/test_assign_training_group_service.py`, `tests/registrations/test_admin_approval_with_group.py`, `tests/registrations/test_admin_review_group_assignment_ui.py`. Existing `tests/registrations/test_review_action_emails.py` extended with two new tests for the conditional email line.
  - No schema change, no migration, no new dependencies.
  - Full repo verification: `uv run pytest -q` → `<final-count> passed`, `uv run ruff check .` → passed, `uv run mypy .` → passed.
  - Manual LAN verification on `http://192.168.3.245:8000/admin/review/applications/<id>/` PENDING.
```

Replace `<final-count>` with the actual `uv run pytest -q` tail from Step 5.1.

- [ ] **Step 5.3: Update `docs/milestones.md`**

Find the existing P5 status block (added during Slice A docs). Inside the "Status: in progress" bullet list, change the Slice B bullet from `(queued)` to a delivered line. Replace:

```markdown
- Slice B (queued) — training-group assignment workflow (item 3).
```

with:

```markdown
- Slice B delivered 2026-05-28 — training-group assignment inline on the review detail page (during approval via a bundled dropdown; post-approval via a Treniņu grupa module with reassign/clear). New `assign_training_group` service. Approve email enriched with the assigned group name. No model changes. Item 3 closed; items 5, 7, 11 → Slice C; items 6, 8, 9, 10 → Slice D.
```

- [ ] **Step 5.4: Commit docs**

```bash
git add AGENTS.md docs/milestones.md
git commit -m "$(cat <<'EOF'
docs: P5 Slice B delivered — training-group assignment

AGENTS.md: detailed Slice B entry (service, approve extension, view +
template + email enrichment).
docs/milestones.md: mark P5 Slice B delivered.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5.5: Surface the LAN walkthrough script to the user**

When reporting back, include this manual check list verbatim (the user runs it from a browser):

1. Open Django admin (`/admin/`), create two active `TrainingGroup` rows (e.g. `U10 A`, `U10 B`) and one inactive (`U10 Arhīvs`).
2. From a parent account, submit a fresh registration.
3. Open the staff review detail page. Confirm the approve form dropdown shows the two active groups + `— Piešķirsim vēlāk —`; inactive group is hidden.
4. Approve with `U10 A` selected. Confirm the post-approval `Treniņu grupa` module appears with `Pašreizējā grupa: U10 A`. Confirm the approve email arrived with `Treniņu grupa: U10 A.` in the body.
5. Reassign to `U10 B` via the post-approval module. Confirm "Pašreizējā grupa" updates. Confirm no extra email arrived.
6. Clear assignment via `— Notīrīt piešķīrumu —`. Confirm `Vēl nav piešķirta` shows.
7. Reassign to `U10 A`, then mark `U10 A` inactive via Django admin. Refresh the review detail. Confirm `U10 A` appears in the picker with `(neaktīva)` suffix and `data-inactive="true"` in the option markup (view-source check).
8. Approve a second test application without selecting a group. Confirm the approve email arrives without the `Treniņu grupa` line.
9. Anonymous browser hits the assign POST URL — confirm it still redirects / 404s.

---

## Done-When

- All 5 tasks committed on `dev` (commits land in order; intermediate `uv run pytest -q` runs green).
- Final suite count ≥ ~913 (a couple of tests may shift if existing assertions need updates; do not weaken).
- `uv run ruff check .` and `uv run mypy .` both clean.
- `AGENTS.md` and `docs/milestones.md` reflect Slice B delivered.
- Manual LAN walkthrough above completed by the user. (PR + push are not in this plan — finishing-a-development-branch handles that after Slice B + the rest of the queued P5 work is ready.)

# P7 C-ii batch 2 — Plan 3: Training-group de-duplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate training groups (case-insensitive unique name + a friendly admin-form error) and let staff merge existing duplicates from the admin (reparenting members, deleting the spares).

**Architecture:** A `UniqueConstraint(Lower("name"))` on `TrainingGroup` (one migration) backs a model `clean()` that raises a Latvian `ValidationError` on a case-insensitive clash. A `merge_training_groups` admin action opens a confirmation page where staff pick the target group; on confirm it reparents all members of the other selected groups to the target inside a transaction and deletes the spares.

**Tech Stack:** Django 5.x admin, pytest-django, `uv run`. **One** new migration (the constraint).

Spec: `docs/superpowers/specs/2026-06-15-p7-cii-batch2-admin-polish-design.md` (§5 Plan 3).

---

## File Structure

- `apps/members/models.py` — `TrainingGroup.Meta.constraints` (Lower-name unique) + `clean()`.
- `apps/members/migrations/0012_traininggroup_unique_name_ci.py` — **new** (number is whatever `makemigrations` assigns; do not hand-pick — run the command).
- `apps/members/admin.py` — `search_fields` + `merge_training_groups` action on `TrainingGroupAdmin`.
- `templates/admin/members/traininggroup/merge_confirm.html` — **new** confirmation page.
- Tests (new): `tests/members/test_training_group_unique.py`, `tests/members/test_admin_group_merge.py`.

**Verified facts:**
- `TrainingGroup` (apps/members/models.py:45) = `name = CharField(max_length=255)` + `is_active = BooleanField(default=True)`; no constraints today.
- `Member.training_group` (apps/members/models.py:66) FK `on_delete=SET_NULL, null=True, related_name="members"`.
- There are **no existing duplicate names** in the live DB (verified) — the constraint migrates cleanly.
- `TrainingGroupAdmin` (apps/members/admin.py:19) currently `list_display=("name","is_active")`, `list_filter=("is_active",)`. (Plan 2 Task 5 may have already added `search_fields=("name",)`; if so, treat it as present and skip that part.)

> **Sequencing note:** This plan adds the only migration in batch 2. If run after Plans 1/2, `search_fields` on `TrainingGroupAdmin` may already exist — extend, don't duplicate.

---

### Task 1: Case-insensitive unique-name constraint + `clean()`

**Files:**
- Modify: `apps/members/models.py`
- Create: migration (via `makemigrations`)
- Test: `tests/members/test_training_group_unique.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/members/test_training_group_unique.py
"""TrainingGroup names are unique case-insensitively."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.members.models import TrainingGroup

pytestmark = pytest.mark.django_db


def test_duplicate_name_case_insensitive_raises_integrity_error():
    TrainingGroup.objects.create(name="U10 A")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            TrainingGroup.objects.create(name="u10 a")


def test_distinct_names_allowed():
    TrainingGroup.objects.create(name="U10 A")
    TrainingGroup.objects.create(name="U12 B")  # no error
    assert TrainingGroup.objects.count() == 2


def test_clean_raises_validation_error_on_case_insensitive_clash():
    TrainingGroup.objects.create(name="U10 A")
    dup = TrainingGroup(name="u10 a")
    with pytest.raises(ValidationError):
        dup.clean()


def test_clean_allows_saving_same_instance():
    g = TrainingGroup.objects.create(name="U10 A")
    g.name = "U10 A"
    g.clean()  # editing the same row must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/members/test_training_group_unique.py -v`
Expected: FAIL — duplicate `create` succeeds (no constraint); `clean()` does not raise.

- [ ] **Step 3: Add the constraint + `clean()`**

In `apps/members/models.py`, add the import near the top:

```python
from django.db.models.functions import Lower
```

(Also ensure `from django.core.exceptions import ValidationError` is imported.)

On the `TrainingGroup` model, add a `Meta` with the constraint and a `clean()`:

```python
    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), name="uniq_training_group_name_ci"
            )
        ]

    def clean(self):
        super().clean()
        clash = TrainingGroup.objects.filter(name__iexact=self.name)
        if self.pk is not None:
            clash = clash.exclude(pk=self.pk)
        if clash.exists():
            raise ValidationError(
                {"name": "Treniņu grupa ar šādu nosaukumu jau pastāv."}
            )
```

- [ ] **Step 4: Generate + run the migration, verify tests pass**

```bash
uv run python manage.py makemigrations members
uv run pytest tests/members/test_training_group_unique.py -v
```
Expected: a new migration `apps/members/migrations/00XX_*.py` adding the constraint; tests PASS (4 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/members/ -q && \
uv run ruff check apps/members/models.py tests/members/test_training_group_unique.py && \
uv run mypy apps/members/models.py && \
git add apps/members/models.py apps/members/migrations/ tests/members/test_training_group_unique.py && \
git commit -m "feat(members): case-insensitive unique TrainingGroup name + clean (P7 C-ii b2)"
```

---

### Task 2: Search + merge admin action

**Files:**
- Modify: `apps/members/admin.py`
- Create: `templates/admin/members/traininggroup/merge_confirm.html`
- Test: `tests/members/test_admin_group_merge.py`

**Context:** A two-step admin action: first POST (from the changelist action dropdown) renders a confirmation page listing the selected groups and a radio to choose the target; second POST (`apply=1`) performs the merge in a transaction. Mirror Django's built-in delete-selected confirmation shape.

- [ ] **Step 1: Write the failing tests**

```python
# tests/members/test_admin_group_merge.py
"""Merge admin action reparents members and deletes duplicate groups."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.members.models import Guardian, Member, TrainingGroup

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_merge_confirmation_page_lists_selected_groups():
    a = TrainingGroup.objects.create(name="U10 A")
    b = TrainingGroup.objects.create(name="U10 A dublikāts")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk), str(b.pk)],
    })
    assert resp.status_code == 200
    assert b"U10 A" in resp.content
    assert b"Apvienot" in resp.content  # confirm button label


def test_merge_reparents_members_and_deletes_others():
    g = Guardian.objects.create(full_name="V")
    target = TrainingGroup.objects.create(name="U10 A")
    dup = TrainingGroup.objects.create(name="U10 A dublikāts")
    m1 = Member.objects.create(full_name="A", guardian=g, training_group=target)
    m2 = Member.objects.create(full_name="B", guardian=g, training_group=dup)
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(target.pk), str(dup.pk)],
        "target": str(target.pk),
        "apply": "1",
    })
    assert resp.status_code == 302
    m1.refresh_from_db(); m2.refresh_from_db()
    assert m1.training_group_id == target.pk
    assert m2.training_group_id == target.pk
    assert not TrainingGroup.objects.filter(pk=dup.pk).exists()
    assert TrainingGroup.objects.filter(pk=target.pk).exists()


def test_merge_single_group_is_rejected():
    a = TrainingGroup.objects.create(name="U10 A")
    c = _staff_client()
    url = reverse("admin:members_traininggroup_changelist")
    resp = c.post(url, {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk)],
    }, follow=True)
    assert TrainingGroup.objects.filter(pk=a.pk).exists()  # nothing merged
    assert b"vismaz divas" in resp.content.lower()  # "at least two" message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/members/test_admin_group_merge.py -v`
Expected: FAIL — `merge_training_groups` action does not exist.

- [ ] **Step 3: Implement the action + template**

In `apps/members/admin.py`, add imports:

```python
from django.db import transaction
from django.template.response import TemplateResponse
```

On `TrainingGroupAdmin`, ensure `search_fields = ("name",)` (add if Plan 2 didn't) and add the action:

```python
    actions = ["merge_training_groups"]

    @admin.action(description="Apvienot atlasītās grupas")
    def merge_training_groups(self, request, queryset):
        groups = list(queryset.order_by("name"))
        if len(groups) < 2:
            self.message_user(
                request,
                "Apvienošanai atlasiet vismaz divas grupas.",
                level=messages.WARNING,
            )
            return None
        if request.POST.get("apply") == "1":
            target = get_object_or_404(TrainingGroup, pk=request.POST.get("target"))
            others = [g for g in groups if g.pk != target.pk]
            with transaction.atomic():
                reparented = Member.objects.filter(
                    training_group__in=others
                ).update(training_group=target)
                other_count = len(others)
                for g in others:
                    g.delete()
            self.message_user(
                request,
                f"Apvienotas {other_count} grupas grupā “{target.name}”; "
                f"pārvietoti {reparented} biedri.",
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": "Apvienot treniņu grupas",
            "groups": groups,
            "action_name": "merge_training_groups",
            "selected": [str(g.pk) for g in groups],
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/members/traininggroup/merge_confirm.html", context
        )
```

Add the imports `get_object_or_404` (`from django.shortcuts import get_object_or_404`) and confirm `messages` is imported (it is, at module top).

Create `templates/admin/members/traininggroup/merge_confirm.html`:

```django
{% extends "admin/base_site.html" %}
{% block content %}
<p>Izvēlieties mērķa grupu. Pārējo atlasīto grupu biedri tiks pārvietoti uz mērķa grupu, un pārējās grupas tiks dzēstas.</p>
<form method="post">
  {% csrf_token %}
  {% for g in groups %}
    <input type="hidden" name="_selected_action" value="{{ g.pk }}">
  {% endfor %}
  <input type="hidden" name="action" value="merge_training_groups">
  <input type="hidden" name="apply" value="1">
  <ul style="list-style:none">
    {% for g in groups %}
      <li>
        <label>
          <input type="radio" name="target" value="{{ g.pk }}" {% if forloop.first %}checked{% endif %}>
          {{ g.name }} ({{ g.members.count }} biedri)
        </label>
      </li>
    {% endfor %}
  </ul>
  <button type="submit" class="button default">Apvienot</button>
  <a href="{% url 'admin:members_traininggroup_changelist' %}" class="button">Atcelt</a>
</form>
{% endblock %}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/members/test_admin_group_merge.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/members/ -q && \
uv run ruff check apps/members/admin.py tests/members/test_admin_group_merge.py && \
uv run mypy apps/members/admin.py && \
git add apps/members/admin.py templates/admin/members/traininggroup/merge_confirm.html tests/members/test_admin_group_merge.py && \
git commit -m "feat(members): merge-duplicate-groups admin action + search (P7 C-ii b2)"
```

---

### Task 3: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: pytest/ruff/mypy green; **"No changes detected"** (the constraint migration from Task 1 is already committed, so `--check` is clean now). Fail loud on any failure.

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add "P7 C-ii batch 2 — Plan 3 (training-group dedup) delivered": case-insensitive unique `TrainingGroup.name` constraint (migration `00XX`) + `clean()` Latvian form error; `merge_training_groups` admin action (confirmation page → reparent members → delete spares) + name search. **This completes P7 Slice C-ii** (all of batch 1 + batch 2). Note merge is not audited (deferred).
- `docs/milestones.md`: mark batch-2 Plan 3 delivered and **C-ii complete**.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record P7 C-ii batch 2 Plan 3 group dedup; C-ii complete"
```

---

## Self-Review Notes

- **Spec coverage:** §5 constraint+migration → T1; §5 `clean()` Latvian error → T1; §5 search → T2; §5 merge action (confirmation → reparent → delete, single-group guard) → T2; §6 testing → T1/T2; docs → T3.
- **Migration numbering:** the plan deliberately does NOT hard-code the migration filename — the implementer runs `makemigrations members` and commits whatever number Django assigns (the File Structure note shows `0012_*` only as an illustrative guess).
- **`Lower("name")` UniqueConstraint** is supported in Django 4.0+ (project is 5.x). The DB is SQLite in tests; expression constraints work on SQLite 3.9+.
- **Merge safety:** reparent + delete run inside `transaction.atomic()`; `Member.training_group` is `on_delete=SET_NULL`, but reparenting first means no member is orphaned. The single-group selection is guarded with a warning and no-op.
- **Audit:** merge is intentionally not audited this batch (consistent with batch-1's confirm-audit deferral) — noted in the docs task.
- **Type consistency:** action method name `merge_training_groups`, POST keys `target` / `apply` / `_selected_action`, and template path `admin/members/traininggroup/merge_confirm.html` are identical across the action, the template, and all tests.
- **No `clean()` auto-call caveat:** Django does not call `Model.clean()` on bare `.save()`; the DB constraint is the real guard (tested via `IntegrityError`), and `clean()` is exercised by the admin form (tested directly). Both are covered.

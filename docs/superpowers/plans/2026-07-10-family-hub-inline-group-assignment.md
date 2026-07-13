# Family Hub Inline Group Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let staff assign a missing training group directly from the Family hub `Dalība` lane.

**Architecture:** Reuse the existing Family hub POST action pattern and existing `apps.members.services.assign_training_group` service. Render a no-JS inline form only for members without a group, using the active training groups already present in hub context.

**Tech Stack:** Django admin templates, Django ModelAdmin action view, pytest/pytest-django.

---

## File-by-file plan

- Modify `apps/members/admin.py`
  - Import `assign_training_group` from `apps.members.services`.
  - Add `_family_hub_handle_assign_training_group(self, request, guardian)`.

- Modify `templates/admin/members/guardian/family_hub.html`
  - Under `Dalība`, render inline assign form when `child.member` exists and `child.member.training_group_id` is empty.

- Modify `tests/admin_hub/test_family_hub_page.py`
  - Add tests for form visible/hidden and active group options.

- Modify `tests/admin_hub/test_family_hub_actions.py`
  - Add tests for successful assignment and cross-family rejection.

- Modify docs:
  - `docs/admin-hub.md`
  - `docs/milestones.md` count after final verification.

## Acceptance criteria per unit

- Template:
  - unassigned member shows `name="action" value="assign_training_group"`, `name="member_id"`, `name="training_group"`, and button text `Piešķirt grupu`.
  - assigned member does not show the inline `assign_training_group` action.
  - inactive groups are absent because hub context already filters `is_active=True`.

- Action handler:
  - valid POST assigns selected active group.
  - empty/invalid group shows an error message and does not assign.
  - member from another Guardian returns 404 through `_get_guardian_member`.

## Test strategy

- Use existing admin hub tests and fixtures.
- No new fixtures unless absolutely necessary.
- No JavaScript/browser test; this is plain HTML form + POST.
- Run targeted admin hub tests, then full gate.

---

## Task 1: Tests

**Files:**
- Modify: `tests/admin_hub/test_family_hub_page.py`
- Modify: `tests/admin_hub/test_family_hub_actions.py`

- [ ] **Step 1: Add page tests**

Add to `tests/admin_hub/test_family_hub_page.py`:

```python
def test_hub_shows_inline_group_assignment_for_member_without_group(
    staff_client, approved_application, training_group_a,
):
    member = approved_application.approved_member
    member.training_group = None
    member.save(update_fields=["training_group"])

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    assert 'value="assign_training_group"' in html
    assert f'value="{member.pk}"' in html
    assert 'name="training_group"' in html
    assert "Piešķirt grupu" in html
    assert training_group_a.name in html


def test_hub_hides_inline_group_assignment_for_member_with_group(
    staff_client, approved_application, training_group_a,
):
    member = approved_application.approved_member
    member.training_group = training_group_a
    member.save(update_fields=["training_group"])

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    assert 'value="assign_training_group"' not in html
```

- [ ] **Step 2: Add action tests**

Add to `tests/admin_hub/test_family_hub_actions.py`:

```python
def test_assign_training_group_from_hub(
    staff_client, approved_application, training_group_a,
):
    member = approved_application.approved_member
    member.training_group = None
    member.save(update_fields=["training_group"])

    response = staff_client.post(
        _action_url(approved_application.guardian),
        {
            "action": "assign_training_group",
            "member_id": member.pk,
            "training_group": training_group_a.pk,
        },
    )

    assert response.status_code == 302
    member.refresh_from_db()
    assert member.training_group_id == training_group_a.pk


def test_assign_training_group_rejects_cross_family_member(
    staff_client, submitted_application, training_group_a,
):
    from apps.accounts.models import ParentAccount
    from apps.members.models import Member
    from tests.support import make_guardian as _make_guardian

    other_account = ParentAccount.objects.create(email="group-other@example.com")
    other_guardian = _make_guardian(account=other_account, full_name="Other Parent")
    other_member = Member.objects.create(full_name="Other Child", guardian=other_guardian)

    response = staff_client.post(
        _action_url(submitted_application.guardian),
        {
            "action": "assign_training_group",
            "member_id": other_member.pk,
            "training_group": training_group_a.pk,
        },
    )

    assert response.status_code == 404
```

- [ ] **Step 3: Run red tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py::test_hub_shows_inline_group_assignment_for_member_without_group tests/admin_hub/test_family_hub_page.py::test_hub_hides_inline_group_assignment_for_member_with_group tests/admin_hub/test_family_hub_actions.py::test_assign_training_group_from_hub tests/admin_hub/test_family_hub_actions.py::test_assign_training_group_rejects_cross_family_member -q
```

Expected: at least the visible-form and action tests fail because production code is absent.

## Task 2: Implementation

**Files:**
- Modify: `apps/members/admin.py`
- Modify: `templates/admin/members/guardian/family_hub.html`
- Modify: `docs/admin-hub.md`

- [ ] **Step 1: Import service**

In `apps/members/admin.py`, change:

```python
from apps.members.services import assign_training_group
```

Use existing import area near other member imports.

- [ ] **Step 2: Add action handler**

In `GuardianAdmin`, near other `_family_hub_handle_*` handlers, add:

```python
    def _family_hub_handle_assign_training_group(self, request, guardian):
        member = self._get_guardian_member(guardian, request.POST.get("member_id", ""))
        group = self._resolve_training_group(request, request.POST.get("training_group", ""))
        if group is None:
            self.message_user(
                request, "Lūdzu izvēlieties treniņu grupu.", level=messages.ERROR
            )
            return
        assign_training_group(member, group, request.user)
        self.message_user(request, "Treniņu grupa piešķirta.")
```

- [ ] **Step 3: Add template form**

In `templates/admin/members/guardian/family_hub.html`, after `Formas izmērs` line and before member deep link, add:

```django
  {% if child.member and not child.member.training_group_id %}
    <form method="post" action="{{ action_url }}" style="display:inline">
      {% csrf_token %}
      <input type="hidden" name="action" value="assign_training_group">
      <input type="hidden" name="member_id" value="{{ child.member.pk }}">
      <label for="hub_member_group_{{ child.member.pk }}">Treniņu grupa:</label>
      <select name="training_group" id="hub_member_group_{{ child.member.pk }}" required>
        <option value="">— Izvēlieties grupu —</option>
        {% for grp in hub.active_training_groups %}
          <option value="{{ grp.pk }}">{{ grp.name }}</option>
        {% endfor %}
      </select>
      <button type="submit">Piešķirt grupu</button>
    </form>
  {% endif %}
```

- [ ] **Step 4: Update docs**

In `docs/admin-hub.md`, add a short sentence under the lane list or workflow section:

```markdown
In **Dalība**, an active member without a training group shows an inline **Treniņu grupa** dropdown and **Piešķirt grupu** button.
```

## Task 3: Verification

- [ ] **Step 1: Run targeted tests**

```bash
uv run pytest tests/admin_hub -q
uv run ruff check apps/members tests/admin_hub
uv run mypy apps/members
```

Expected: pass.

- [ ] **Step 2: Run full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: pass, clean, no migrations.

- [ ] **Step 3: Update milestone count**

Update P11 in `docs/milestones.md` if test count changes.

- [ ] **Step 4: Generate diff URL**

```bash
bunx critique --web "Family hub inline group assignment" \
  --filter "apps/members/admin.py" \
  --filter "templates/admin/members/guardian/family_hub.html" \
  --filter "tests/admin_hub/test_family_hub_page.py" \
  --filter "tests/admin_hub/test_family_hub_actions.py" \
  --filter "docs/admin-hub.md" \
  --filter "docs/milestones.md" \
  --filter "docs/superpowers/specs/2026-07-10-family-hub-inline-group-assignment-design.md" \
  --filter "docs/superpowers/plans/2026-07-10-family-hub-inline-group-assignment.md"
```

## Self-review

- Scope is one UI/action path.
- No migration.
- Tests cover form visibility, successful assignment, and cross-family guard.
- Implementation reuses existing service and hub active group context.

# P5 Slice B — Training-group assignment workflow

**Status:** Approved 2026-05-28. Awaiting implementation plan.
**Spec for:** P5 acceptance item 3 only. Items 5, 7, 11 → Slice C. Items 6, 8, 9, 10 → Slice D.
**Predecessor:** P5 Slice A delivered + Revision A + Slice A.1 (merged to `dev`, awaiting PR to `main`).

## Context

The post-approval member record currently has no surface for assigning a training group. `apps/registrations/services.py::approve_application` hardcodes `training_group=None`. Vanilla Django admin (`MemberAdmin`) supports the assignment via its FK widget, but that pulls staff away from the review-decision context entirely.

Slice B keeps assignment inside the admin review flow:

- During approval (one click): the approval form gains an "optional" training-group dropdown; selecting one assigns the member at create-time.
- After approval (any time): the same review-detail page exposes a Treneru grupa module showing the current group and a picker for change/clear.

No schema changes. No new endpoints. No new dependencies. Latvian copy throughout.

## Decisions locked in (no re-debate)

1. **Assignment surface (post-approval) = inline on review detail page.** No separate page; no redirect to Django admin's Member change page.
2. **Approve form bundles the dropdown.** Single POST = approve + (optionally) assign. Empty option = approve without group.
3. **Dropdown shows `is_active=True` groups only.** Exception: if the member is currently assigned to a now-inactive group, that group also appears in the picker with a `(neaktīva)` marker so existing state is never hidden.
4. **No email notification on standalone assignment or reassignment.** The approval email gets a conditional line naming the group when it was assigned at approval time. Standalone post-approval assignments (or later reassignments) stay silent.
5. **TrainingGroup model unchanged.** No `description`, no `age_band`, no `coach`, no `season`. YAGNI; revisit when operational pain shows up.

## Architecture

### Services

**`apps/members/services.py` — new file** (this app has no `services.py` yet):

```python
def assign_training_group(
    member: Member,
    group: TrainingGroup | None,
    actor,  # AUTH_USER_MODEL — kept for future audit hook, unused today
) -> Member:
    """Set or clear a member's training group. Idempotent."""
```

Behavior:
- If `member.training_group_id == (group.id if group else None)`: return as-is (idempotent no-op).
- Otherwise: `member.training_group = group; member.save(update_fields=["training_group"])`.
- `actor` accepted but unused in this slice (forward-compat for the P7 audit baseline).
- No notification, no validation that the group is active — staff can deliberately assign an inactive group via the service layer if the picker exposes it (which it only does for the "currently assigned but now inactive" case).

**`apps/registrations/services.py::approve_application` — extended:**

```python
def approve_application(
    application: RegistrationApplication,
    reviewer,  # AUTH_USER_MODEL
    training_group: TrainingGroup | None = None,
) -> RegistrationApplication:
```

Behavior changes:
- On first approval, pass `training_group` into `Member.objects.create(...)` instead of the hardcoded `None`.
- Validation: if `training_group` is provided and `training_group.is_active is False`, raise `ValueError` (the approve form picker should not present inactive groups; defensive guard against malformed POSTs).
- Idempotency rule is unchanged: when `approved_member_id is not None`, return as-is. A second call with a different `training_group` argument **does not** mutate the assignment — assignment edits go through `assign_training_group`.

### View

**`apps/registrations/views.py::admin_review_detail`** gains:

- Context entry `active_training_groups`: `TrainingGroup.objects.filter(is_active=True).order_by("name")`.
- Context entry `current_inactive_group`: `application.approved_member.training_group if application.approved_member and application.approved_member.training_group and not application.approved_member.training_group.is_active else None` — surfaced to the template so the picker can include it with the `(neaktīva)` suffix.
- New POST branch: `action == "assign_training_group"` reads `request.POST.get("training_group")`. Empty / missing value → `assign_training_group(member, None, request.user)`. Non-empty → resolve the FK by id (404 on miss), call `assign_training_group(member, group, request.user)`. Always redirects back to the same detail URL.
- Existing `action == "approve"` branch reads optional `training_group` POST value the same way and passes it to `approve_application`. `ValueError` from `approve_application` (existing pattern) renders the page with a 400 + `error` context.

### Template

**`templates/registrations/admin_review_detail.html`** picks up two additions inside the existing `{% block content %}`:

1. **Inside the existing `if application.status == "submitted"` block**, before the `<button name="action" value="approve">`:

```html
<label for="approve_training_group">Treneru grupa (neobligāti):</label>
<select name="training_group" id="approve_training_group">
  <option value="">— Piešķirsim vēlāk —</option>
  {% for grp in active_training_groups %}
    <option value="{{ grp.id }}">{{ grp.name }}</option>
  {% endfor %}
</select>
```

2. **New module rendered only when `application.approved_member`** (i.e. post-approval):

```html
<div class="module mms-review-group-module">
  <h2>Treneru grupa</h2>
  {% if application.approved_member.training_group %}
    <p>Pašreizējā grupa: <strong>{{ application.approved_member.training_group.name }}</strong>
       {% if current_inactive_group %} <em>(neaktīva)</em>{% endif %}</p>
  {% else %}
    <p>Vēl nav piešķirta.</p>
  {% endif %}

  <form method="post">
    {% csrf_token %}
    <label for="reassign_training_group">Mainīt grupu:</label>
    <select name="training_group" id="reassign_training_group">
      <option value="">— Notīrīt piešķīrumu —</option>
      {% for grp in active_training_groups %}
        <option value="{{ grp.id }}"
                {% if application.approved_member.training_group_id == grp.id %}selected{% endif %}>
          {{ grp.name }}
        </option>
      {% endfor %}
      {% if current_inactive_group %}
        <option value="{{ current_inactive_group.id }}" selected data-inactive="true">
          {{ current_inactive_group.name }} (neaktīva)
        </option>
      {% endif %}
    </select>
    <button type="submit" name="action" value="assign_training_group" class="default">Saglabāt</button>
  </form>
</div>
```

CSS: tiny additions in `static/admin/css/review.css` — `.mms-review-group-module` (matches the `.module` rhythm of other Slice A sections); inline `em` for the `(neaktīva)` marker; spacing for the form-row. No new variables.

### Email enrichment

**`templates/emails/registrations/approve.txt`** gains one conditional line after the "ir pievienots kluba dalībnieku reģistram" sentence:

```
{% if application.approved_member.training_group %}
Treniņu grupa: {{ application.approved_member.training_group.name }}.
{% endif %}
```

No other changes to the email plumbing — context already includes `application`, and `_render_and_send_notification` is template-driven so the conditional renders correctly with or without an assignment.

Reassignment (post-approval) and standalone first-assignment (post-approval) do not send any email. Only the bundled approve+assign path enriches the existing approval email.

## Tests

Three new files, each focused on one responsibility:

### `tests/members/test_assign_training_group_service.py` (new)
- Assigns a group when member had none.
- Reassigns from group A to group B.
- Clears assignment with `group=None`.
- Idempotent: re-assigning the same group does not bump `updated_at` (or returns early — verify whichever guarantee is implemented).
- Allows assigning an inactive group via the service (admin-driven override; picker filtering happens at the view layer).
- Uses fixtures from `tests/members/conftest.py` (create one if missing — at minimum `training_group_a`, `training_group_b`, `inactive_training_group`, `member`).

### `tests/registrations/test_admin_approval_with_group.py` (new)
- `approve_application` without `training_group` creates Member with `training_group=None` (regression of the pre-Slice-B baseline).
- `approve_application` with an active group creates Member with the group set.
- `approve_application` with an inactive group raises `ValueError`; no Member is created, application status is unchanged.
- Idempotent re-approval with a different `training_group` argument does NOT mutate the Member's assignment.
- The new positional/keyword argument doesn't break the existing one-arg-positional call sites (regression).

### `tests/registrations/test_admin_review_group_assignment_ui.py` (new)
- Review detail page for a submitted application contains the `<select name="training_group">` with the "— Piešķirsim vēlāk —" empty option + every active group + no inactive groups.
- POST `action=approve` with `training_group=<id>` approves the application and assigns the group on the new Member.
- POST `action=approve` with `training_group=""` approves and leaves `training_group=None`.
- Review detail page for an approved application without a group shows the "Vēl nav piešķirta" message and the picker.
- Review detail page for an approved application with a group shows "Pašreizējā grupa: <name>" with the option pre-selected in the picker.
- POST `action=assign_training_group` with a group id updates the Member.
- POST `action=assign_training_group` with empty value clears the Member's group.
- Currently-assigned-but-inactive group appears as a pre-selected option with `data-inactive="true"`; switching to another option clears the inactive assignment.
- Non-staff hitting the assign POST receives the same 404/redirect the existing access-control gives the other admin endpoints.

### `tests/registrations/test_review_action_emails.py` (extend existing file)
- `test_approve_email_includes_training_group_when_assigned`: approve with an active group, assert `outbox[0].body` contains `Treniņu grupa: <name>.`.
- `test_approve_email_omits_training_group_when_unassigned`: approve without a group, assert `outbox[0].body` does NOT contain `Treniņu grupa`.

Expect ~12 new tests across the three new files + 2 extensions, target suite ≈ **905** from the 891 baseline.

## Files touched

- `apps/members/services.py` (new)
- `apps/registrations/services.py` (extend `approve_application`)
- `apps/registrations/views.py` (extend `admin_review_detail` context + POST branches)
- `templates/registrations/admin_review_detail.html` (two additions inside `{% block content %}`)
- `templates/emails/registrations/approve.txt` (conditional `Treniņu grupa: ...` line)
- `static/admin/css/review.css` (small additions for `.mms-review-group-module`)
- `tests/members/conftest.py` (new or extended)
- `tests/members/test_assign_training_group_service.py` (new)
- `tests/registrations/test_admin_approval_with_group.py` (new)
- `tests/registrations/test_admin_review_group_assignment_ui.py` (new)
- `tests/registrations/test_review_action_emails.py` (extend with 2 tests)

## Files NOT touched

- `apps/members/models.py` — no model change.
- `apps/registrations/models.py` — no schema change.
- `apps/members/admin.py` — vanilla `MemberAdmin` / `TrainingGroupAdmin` stay as-is (no `formfield_for_foreignkey` polish in this slice).
- `apps/accounts/services.py` — magic-link / verification emails unrelated.
- Parent surfaces, parent-portal templates.
- DocuSeal / Agreement work — Slices C, D.

## Out of scope (explicit)

- Email notification to parent on standalone assignment or reassignment.
- TrainingGroup model enrichment (description, age_band, coach, season).
- Group capacity / headcount tracking.
- Auto-suggestion of a group based on member birth date.
- Audit-log entry for assignments (P7 target — `actor` is plumbed through `assign_training_group` so the wire-up is trivial later).
- Bulk assignment / re-assignment UI.
- Django admin `MemberAdmin` polish (filtered FK widget).

## Verification

1. `uv run pytest -q` → ≥ 905 passing (891 baseline + ~14 new).
2. `uv run ruff check .` and `uv run mypy .` clean.
3. Manual LAN check at `http://192.168.3.245:8000/admin/review/applications/<id>/`:
   - Seed 2 active TrainingGroups + 1 inactive via Django admin.
   - Submit a fresh application as a parent.
   - On the staff review page: dropdown shows the 2 active groups + "— Piešķirsim vēlāk —". Inactive group hidden.
   - Approve with a group selected → page reloads, post-approval Treneru grupa module shows "Pašreizējā grupa: <name>". Approve email arrives with the new "Treniņu grupa: <name>." line.
   - Reassign via the module → "Pašreizējā grupa" updates. No email sent.
   - Clear assignment → "Vēl nav piešķirta" + picker. No email sent.
   - Mark the assigned group inactive via Django admin → review page picker shows the current group with `(neaktīva)` suffix, plus the other active groups for reassignment.
   - Approve a second test application without a group → approve email arrives without the "Treniņu grupa" line.
4. Update `AGENTS.md` (Current Status + new "P5 Slice B delivered" entry) and `docs/milestones.md` (add Slice B delivered bullet under the P5 in-progress status block).

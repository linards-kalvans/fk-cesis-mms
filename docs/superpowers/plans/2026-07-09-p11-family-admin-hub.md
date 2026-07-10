# P11 Family Admin Action Hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Django-admin family hub where staff can see a Guardian family's application, agreement, membership, kit-size, and billing state and complete the normal workflow without jumping across deep admin pages.

**Architecture:** Add a thin Guardian-centered admin orchestration layer that reuses existing models, services, admin auth, CSRF, audit paths, and background enqueue helpers. Put pure status/context helpers in `apps/members/family_hub.py`, expose queue/detail/action URLs from `GuardianAdmin`, and render server-side Django admin templates. No new business logic, model states, or migrations.

**Tech Stack:** Django 5 admin, pytest + pytest-django, existing domain services, existing `uv run` verification commands.

---

## Current constraints

- Branch: `dev`.
- Existing dirty working tree contains unrelated agreement-number/DocuSeal changes; do not touch those files unless P11 explicitly requires it.
- Use `uv run` for Python commands.
- Do not add dependencies.
- Do not create new model fields or migrations.
- Keep parent-facing pages unchanged.
- Hub actions must reuse existing services/enqueue helpers.

## Existing code to reuse

- `apps.members.admin.GuardianAdmin` — add queue/detail/action URLs here.
- `apps.registrations.admin.RegistrationApplicationAdmin.review_action_view()` — existing action dispatch to mirror/reuse for application/agreement/member actions.
- `apps.registrations.admin.RegistrationApplicationAdmin.approve_view()` — existing approval behavior.
- `apps.registrations.admin_panels.build_review_context()` — existing document/agreement/discontinuation panel context; reuse pieces where useful, do not duplicate document preview work unless needed.
- `apps.billing.admin.BillingRecordAdmin.confirm_view()` — existing confirmation behavior/audit pattern.
- `apps.integrations.tasks.enqueue_push_billing_record()` and `enqueue_sync_billing_record_payments()` — billing actions.
- `apps.core.admin_badges.status_badge()` and `static/admin/fk_badges.css` — status badges.
- `apps.core.admin_links.admin_link()` / `admin_links()` — deep links.

## Files

### Create

- `apps/members/family_hub.py` — pure context/status builders for queue and hub.
- `templates/admin/members/guardian/family_queue.html` — action-needed queue page.
- `templates/admin/members/guardian/family_hub.html` — per-family hub page.
- `static/admin/family_hub.css` — small layout-only admin CSS, if `fk_badges.css` is insufficient.
- `docs/admin-hub.md` — staff operator guide.
- `tests/admin_hub/test_family_queue.py` — queue behavior.
- `tests/admin_hub/test_family_hub_page.py` — detail page rendering and kit-size display.
- `tests/admin_hub/test_family_hub_actions.py` — POST actions and permissions.
- `tests/admin_hub/test_family_hub_billing.py` — billing block grouping/rows/errors.

### Modify

- `apps/members/admin.py` — add GuardianAdmin URLs, links, media, views, and action dispatch.
- `docs/milestones.md` — after implementation verification, mark P11 complete with evidence summary.
- `docs/superpowers/specs/2026-07-02-p11-family-admin-hub-design.md` — add explicit kit-size admin acceptance/test scope so spec matches milestone.

---

## Design details

### Data flow

```text
GuardianAdmin queue URL
  -> build_family_queue_rows()
  -> family_queue.html
  -> open Guardian hub

GuardianAdmin hub URL
  -> build_family_hub_context(guardian)
  -> family_hub.html
  -> POST action to GuardianAdmin.family_hub_action_view
  -> existing service/enqueue helper
  -> redirect back to hub
```

### Status helpers

Define in `apps/members/family_hub.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FamilyLaneStatus:
    key: str
    label: str
    badge: str
    level: str
    icon: str
    next_action: str
    urgency: int
```

Status levels must be accepted by existing `status_badge`: `ok`, `fail`, `pending`, `muted`.

Urgency order, high to low:

1. Submitted application needs staff review.
2. Agreement generated/sent/failed needs staff action.
3. Signed agreement with draft billing needs confirmation.
4. Confirmed billing without pushed invoices or failed push needs push/retry.
5. Synced billing needs payment sync.
6. Informational states only.

### Hub context shape

`build_family_hub_context(guardian)` returns a dict with at least:

```python
{
    "guardian": guardian,
    "members": [...],
    "applications": [...],
    "children": [
        {
            "member": member_or_none,
            "application": application_or_none,
            "agreement": agreement_or_none,
            "kit_size_label": "128" or "—",
            "application_status": FamilyLaneStatus,
            "agreement_status": FamilyLaneStatus,
            "membership_status": FamilyLaneStatus,
            "billing_groups": [...],
            "deep_links": {...},
        }
    ],
    "queue_statuses": [...],
    "needs_action": bool,
    "highest_urgency": int,
    "active_training_groups": [...],
    "membership_plans": [...],
}
```

Billing group shape:

```python
{
    "record": billing_record,
    "member": member,
    "season": billing_record.season,
    "status": FamilyLaneStatus,
    "invoices": [...],
    "error_message": "..." or "",
    "deep_link": safe_html_link,
}
```

### Action endpoint contract

`GuardianAdmin.family_hub_action_view(request, guardian_id)` accepts POST only. It reads:

- `action`
- `application_id` when action targets application/review/agreement through source application
- `agreement_id` when action targets agreement directly
- `member_id` when action targets membership
- `billing_record_id` when action targets billing
- action-specific fields already used elsewhere:
  - `review_message`
  - `training_group`
  - `void_reason`
  - `note`
  - `effective_date`
  - `reason`
  - `selected_invoices`

Return: redirect to family hub with Django admin messages.

Supported `action` values:

- `approve_application`
- `request_fix`
- `reject`
- `mark_agreement_sent`
- `mark_agreement_signed`
- `retry_docuseal`
- `sync_docuseal`
- `void_agreement`
- `regenerate_agreement`
- `minor_amendment`
- `material_amendment`
- `discontinue_member`
- `confirm_billing`
- `push_billing`
- `sync_billing_payments`

No action may mutate an object outside the selected Guardian's family. Check ownership before calling a service:

- application belongs if `application.guardian_id == guardian.id` or approved member's guardian matches.
- agreement belongs if `agreement.member.guardian_id == guardian.id`.
- member belongs if `member.guardian_id == guardian.id`.
- billing record belongs if `record.member.guardian_id == guardian.id`.

### Kit-size rule

Hub and Guardian/Member family controls must show one label: **Formas izmērs**.

Use canonical value only:

1. For approved member: `member.kit_size_shirt.label` if field exists and value present.
2. For pending application: `application.member_kit_size_shirt.label`.
3. Else `—`.

Do not render `member_kit_size_shorts`, `kit_size_shorts`, `Šortu izmērs`, or `Shorts` in hub templates.

---

## Task 1: Queue and status context tests

**Files:**
- Create: `tests/admin_hub/test_family_queue.py`
- Create: `apps/members/family_hub.py`
- Modify: `apps/members/admin.py`
- Create: `templates/admin/members/guardian/family_queue.html`

- [ ] **Step 1: Write failing tests for pure queue/status helpers**

Create `tests/admin_hub/test_family_queue.py` with tests that use existing fixtures from `tests/conftest.py` and helper factories already present in the repo. If a fixture name differs, use the local repo fixture with the same semantic role.

Test cases:

```python
import pytest
from django.urls import reverse

from apps.members.family_hub import build_family_queue_rows
from apps.registrations.models import RegistrationApplication
from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord

pytestmark = pytest.mark.django_db


def test_queue_rows_include_submitted_application_needing_review(make_guardian, submitted_application):
    guardian = submitted_application.guardian
    rows = build_family_queue_rows()

    matching = [row for row in rows if row["guardian"].pk == guardian.pk]

    assert matching
    assert matching[0]["needs_action"] is True
    assert any(status.key == "application" for status in matching[0]["statuses"])
    assert "Apstiprināt" in matching[0]["next_action"]


def test_queue_rows_exclude_family_with_only_draft_application(make_guardian, draft_application):
    guardian = draft_application.guardian

    rows = build_family_queue_rows()

    assert guardian.pk not in {row["guardian"].pk for row in rows}


def test_queue_orders_submitted_application_before_billing_sync(make_guardian, submitted_application, billing_record_factory):
    urgent_guardian = submitted_application.guardian
    billing_record = billing_record_factory(status=BillingRecord.Status.CONFIRMED, external_status="synced")
    billing_guardian = billing_record.member.guardian

    rows = build_family_queue_rows()
    guardian_ids = [row["guardian"].pk for row in rows]

    assert guardian_ids.index(urgent_guardian.pk) < guardian_ids.index(billing_guardian.pk)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/admin_hub/test_family_queue.py -q
```

Expected: fail because `apps.members.family_hub` and queue admin URL do not exist.

- [ ] **Step 3: Implement minimal pure helper**

Create `apps/members/family_hub.py` with:

- `FamilyLaneStatus`
- `application_lane`
- `agreement_lane`
- `membership_lane`
- `billing_lane`
- `build_family_queue_rows`

Use simple ORM queries with `select_related`/`prefetch_related`:

- Guardians with submitted/fix/review applications.
- Guardians with members and current agreements.
- Guardians with members and billing records.

Keep ranking simple and deterministic: sort by `(-highest_urgency, guardian.full_name.lower(), guardian.pk)`.

- [ ] **Step 4: Add queue URL and template**

In `GuardianAdmin.get_urls()`, add:

```python
path(
    "family-hub/",
    self.admin_site.admin_view(self.family_queue_view),
    name="members_guardian_family_queue",
)
```

Add `family_queue_view()` rendering `templates/admin/members/guardian/family_queue.html` with:

- `rows`
- `opts`
- admin context

- [ ] **Step 5: Run task tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_queue.py -q
```

Expected: pass.

---

## Task 2: Family hub page rendering and kit-size display

**Files:**
- Create/modify: `tests/admin_hub/test_family_hub_page.py`
- Modify: `apps/members/family_hub.py`
- Modify: `apps/members/admin.py`
- Create: `templates/admin/members/guardian/family_hub.html`
- Create: `static/admin/family_hub.css` if needed

- [ ] **Step 1: Write failing hub rendering tests**

Create `tests/admin_hub/test_family_hub_page.py`:

```python
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def hub_url(guardian):
    return reverse("admin:members_guardian_family_hub", args=[guardian.pk])


def test_family_hub_requires_staff(client, guardian):
    response = client.get(hub_url(guardian))

    assert response.status_code in (302, 403)


def test_family_hub_renders_all_lanes(staff_client, submitted_application):
    guardian = submitted_application.guardian

    response = staff_client.get(hub_url(guardian))

    assert response.status_code == 200
    html = response.content.decode()
    assert "Pieteikumi" in html
    assert "Līgumi" in html
    assert "Dalība" in html
    assert "Norēķini un rēķini" in html
    assert "Apstiprināt" in html


def test_family_hub_renders_single_form_size_label(staff_client, submitted_application, kit_sizes):
    submitted_application.member_kit_size_shirt = kit_sizes[0]
    submitted_application.save(update_fields=["member_kit_size_shirt", "updated_at"])

    response = staff_client.get(hub_url(submitted_application.guardian))

    html = response.content.decode()
    assert "Formas izmērs" in html
    assert kit_sizes[0].label in html
    assert "Šortu izmērs" not in html
    assert "member_kit_size_shorts" not in html


def test_family_hub_has_deep_admin_links(staff_client, approved_application):
    guardian = approved_application.guardian

    response = staff_client.get(hub_url(guardian))

    html = response.content.decode()
    assert "Atvērt detalizēti" in html
    assert "/admin/members/guardian/" in html
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py -q
```

Expected: fail because hub URL/template/context is missing.

- [ ] **Step 3: Implement `build_family_hub_context`**

In `apps/members/family_hub.py`, add:

- `build_family_hub_context(guardian)`
- `canonical_kit_size_label(obj)`
- billing group builder shell returning empty groups for no billing

Use existing `get_current_agreement(member)` for current agreement.

- [ ] **Step 4: Add GuardianAdmin hub URL/view/media/link**

In `GuardianAdmin`:

- Add `family_hub_link` to `list_display`.
- Add URL:

```python
path(
    "<int:guardian_id>/family-hub/",
    self.admin_site.admin_view(self.family_hub_view),
    name="members_guardian_family_hub",
)
```

- Add `family_hub_view()`:
  - permission check
  - `get_object_or_404(Guardian.objects.select_related("parent_account"), pk=guardian_id)`
  - context from `build_family_hub_context`
  - render template

- Add Media CSS: `admin/fk_badges.css` and optional `admin/family_hub.css`.

- [ ] **Step 5: Implement hub template**

Create `templates/admin/members/guardian/family_hub.html` extending `admin/base_site.html`.

Required visible text:

- `Ģimenes darbību centrs`
- `Pieteikumi`
- `Līgumi`
- `Dalība`
- `Norēķini un rēķini`
- `Formas izmērs`
- `Atvērt detalizēti`

Use `<details>` for expandable invoices. Use normal POST forms with CSRF.

- [ ] **Step 6: Run hub page tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_page.py -q
```

Expected: pass.

---

## Task 3: Hub action dispatch tests and implementation

**Files:**
- Create/modify: `tests/admin_hub/test_family_hub_actions.py`
- Modify: `apps/members/admin.py`
- Modify: `templates/admin/members/guardian/family_hub.html`

- [ ] **Step 1: Write failing action tests**

Create `tests/admin_hub/test_family_hub_actions.py`.

Include helper:

```python
from django.urls import reverse


def action_url(guardian):
    return reverse("admin:members_guardian_family_hub_action", args=[guardian.pk])
```

Test cases:

```python
import pytest
from unittest.mock import patch

from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord
from apps.members.models import Member
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def test_non_staff_cannot_post_action(client, guardian):
    response = client.post(action_url(guardian), {"action": "confirm_billing"})

    assert response.status_code in (302, 403)


def test_approve_application_from_hub(staff_client, submitted_application):
    guardian = submitted_application.guardian

    response = staff_client.post(
        action_url(guardian),
        {"action": "approve_application", "application_id": submitted_application.pk},
    )

    assert response.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.APPROVED
    assert submitted_application.approved_member_id is not None


def test_mark_agreement_sent_from_hub(staff_client, approved_application):
    guardian = approved_application.guardian
    agreement = approved_application.approved_member.agreements.get(is_current=True)

    response = staff_client.post(
        action_url(guardian),
        {"action": "mark_agreement_sent", "agreement_id": agreement.pk},
    )

    assert response.status_code == 302
    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SENT


def test_void_agreement_does_not_discontinue_member(staff_client, signed_agreement):
    guardian = signed_agreement.member.guardian

    response = staff_client.post(
        action_url(guardian),
        {"action": "void_agreement", "agreement_id": signed_agreement.pk, "void_reason": "Kļūda"},
    )

    assert response.status_code == 302
    signed_agreement.refresh_from_db()
    signed_agreement.member.refresh_from_db()
    assert signed_agreement.state == Agreement.State.VOID
    assert signed_agreement.member.status == Member.Status.ACTIVE


def test_confirm_billing_from_hub(staff_client, billing_record_factory):
    record = billing_record_factory(status=BillingRecord.Status.DRAFT)
    guardian = record.member.guardian

    response = staff_client.post(
        action_url(guardian),
        {"action": "confirm_billing", "billing_record_id": record.pk},
    )

    assert response.status_code == 302
    record.refresh_from_db()
    assert record.status == BillingRecord.Status.CONFIRMED


def test_push_billing_from_hub_uses_enqueue(staff_client, billing_record_factory):
    record = billing_record_factory(status=BillingRecord.Status.CONFIRMED)
    guardian = record.member.guardian

    with patch("apps.members.admin.enqueue_push_billing_record") as enqueue:
        response = staff_client.post(
            action_url(guardian),
            {"action": "push_billing", "billing_record_id": record.pk},
        )

    assert response.status_code == 302
    enqueue.assert_called_once_with(record.pk)


def test_action_rejects_cross_family_object(staff_client, guardian, billing_record_factory):
    other_record = billing_record_factory(status=BillingRecord.Status.DRAFT)

    response = staff_client.post(
        action_url(guardian),
        {"action": "confirm_billing", "billing_record_id": other_record.pk},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_actions.py -q
```

Expected: fail because action URL/dispatch missing.

- [ ] **Step 3: Implement action URL and ownership helpers**

In `GuardianAdmin.get_urls()`, add:

```python
path(
    "<int:guardian_id>/family-hub/action/",
    self.admin_site.admin_view(self.family_hub_action_view),
    name="members_guardian_family_hub_action",
)
```

Add private helper methods on `GuardianAdmin`:

- `_get_guardian_application(guardian, application_id)`
- `_get_guardian_agreement(guardian, agreement_id)`
- `_get_guardian_member(guardian, member_id)`
- `_get_guardian_billing_record(guardian, billing_record_id)`
- `_family_hub_redirect(guardian)`

Each helper must filter by Guardian ownership in the query and use `get_object_or_404`.

- [ ] **Step 4: Implement action dispatch**

In `family_hub_action_view`:

- reject non-POST by redirecting to hub
- read `action`
- route to existing services/enqueue helpers
- use `message_user` for success/error
- catch the same expected exceptions as `RegistrationApplicationAdmin.review_action_view`
- redirect back to hub

Billing confirm implementation must audit like `BillingRecordAdmin.confirm_view`:

```python
if record.status == BillingRecord.Status.DRAFT:
    record.status = BillingRecord.Status.CONFIRMED
    record.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
        actor=request.user,
        request=request,
        target=record,
    )
```

- [ ] **Step 5: Add action forms to hub template**

Add buttons/forms only when context says they are applicable:

- submitted app: approve, request fix, reject
- generated agreement: mark sent
- sent agreement: mark signed
- failed external agreement: retry/sync
- signed agreement/member active: minor/material/discontinue sections
- draft billing: confirm
- confirmed billing: push/sync

Use separate `<details>` for destructive/verbose forms: reject, void, material amendment, discontinue.

- [ ] **Step 6: Run action tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_actions.py -q
```

Expected: pass.

---

## Task 4: Unified billing block tests and implementation

**Files:**
- Create/modify: `tests/admin_hub/test_family_hub_billing.py`
- Modify: `apps/members/family_hub.py`
- Modify: `templates/admin/members/guardian/family_hub.html`

- [ ] **Step 1: Write failing billing block tests**

Create `tests/admin_hub/test_family_hub_billing.py`:

```python
import pytest
from django.urls import reverse

from apps.billing.models import BillingInvoice, BillingRecord

pytestmark = pytest.mark.django_db


def hub_url(guardian):
    return reverse("admin:members_guardian_family_hub", args=[guardian.pk])


def test_billing_block_groups_by_child_and_season(staff_client, billing_record_factory):
    record = billing_record_factory(season="2026")
    guardian = record.member.guardian

    response = staff_client.get(hub_url(guardian))

    html = response.content.decode()
    assert "Norēķini un rēķini" in html
    assert record.member.full_name in html
    assert "2026" in html
    assert str(record.final_amount) in html


def test_billing_block_renders_invoice_rows_in_details(staff_client, billing_record_factory):
    record = billing_record_factory(status=BillingRecord.Status.CONFIRMED)
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date="2026-01-20",
        amount="100.00",
        external_status="created",
    )

    response = staff_client.get(hub_url(record.member.guardian))

    html = response.content.decode()
    assert "<details" in html
    assert "2026-01-20" in html
    assert "100.00" in html
    assert "Izveidots" in html or "created" not in html


def test_billing_block_renders_error_badge(staff_client, billing_record_factory):
    record = billing_record_factory(
        status=BillingRecord.Status.CONFIRMED,
        external_status="failed",
        external_error_code="auth_failed",
    )

    response = staff_client.get(hub_url(record.member.guardian))

    html = response.content.decode()
    assert "Neizdevās" in html or "Kļūda" in html
    assert "auth_failed" not in html
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_billing.py -q
```

Expected: fail until billing group rendering exists.

- [ ] **Step 3: Complete billing group builder**

In `apps/members/family_hub.py`, implement:

- records ordered by `member.full_name`, `-season`, `pk`
- prefetch invoices ordered by `sequence`
- display labels for invoice external/payment statuses using existing choices or message maps
- error message via `apps.billing.messages.get_invoice_error_message`

- [ ] **Step 4: Render billing block**

In `family_hub.html`, render:

- one card per billing record
- record header with member, season, final amount, payment status
- `<details>` containing invoices
- buttons for confirm/push/sync where applicable
- deep link to BillingRecord admin

- [ ] **Step 5: Run billing tests**

Run:

```bash
uv run pytest tests/admin_hub/test_family_hub_billing.py -q
```

Expected: pass.

---

## Task 5: Documentation and spec/milestone update

**Files:**
- Create: `docs/admin-hub.md`
- Modify: `docs/milestones.md`
- Modify: `docs/superpowers/specs/2026-07-02-p11-family-admin-hub-design.md`

- [ ] **Step 1: Update P11 spec for kit-size requirement**

Modify `docs/superpowers/specs/2026-07-02-p11-family-admin-hub-design.md`:

- Add to goals: hub/admin family/member controls show one **Formas izmērs** value.
- Add to acceptance: kit-size admin display/control exposes one value, not shirt/shorts.
- Add to tests: kit-size admin display coverage.

- [ ] **Step 2: Write operator guide**

Create `docs/admin-hub.md` with:

- entry point: Django admin → Vecāki → Family action queue
- what queue badges mean
- how to process normal workflow in order
- void agreement vs discontinue membership difference
- billing block explanation
- kit-size note: **Formas izmērs** is canonical; old shorts values are legacy
- what still requires deep edit pages

- [ ] **Step 3: Update milestone after verification only**

After full tests pass and code review is accepted, update `docs/milestones.md` P11 status with:

- delivered date
- short feature list
- verification commands and results
- LAN acceptance still needed if not completed

Do not claim LAN acceptance unless actually done.

---

## Verification commands

Run after implementation:

```bash
uv run pytest tests/admin_hub -q
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected:

- all tests pass
- ruff clean
- mypy clean
- makemigrations reports no changes

## Final review checklist

- Staff-only permission enforced on queue, hub, and actions.
- POST actions enforce Guardian ownership before mutation/enqueue.
- Normal workflow works from hub: approve → send agreement → mark signed → confirm billing → push invoices.
- Agreement void and membership discontinuation live in separate sections and tests prove they do not mutate the wrong lane.
- Billing is one unified block grouped by child + season with invoice rows inside `<details>`.
- Kit size appears only as **Formas izmērs** in hub/admin family context.
- No new models, migrations, dependencies, or parent-facing changes.
- Existing unrelated agreement-number/DocuSeal files are not modified by P11 work.

# P7 close-out — audit confirm + merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the billing one-click confirm (DRAFT→CONFIRMED) and the training-group merge as `AuditEvent`s, closing the last P7 audit gap.

**Architecture:** Two new `AuditEvent.Action` choices (one choices-only `core` migration), then a `record_audit_event(...)` call in `BillingRecordAdmin.confirm_view` (on the real transition only) and in `TrainingGroupAdmin.merge_training_groups` (after the atomic merge commits). No behaviour change to the actions.

**Tech Stack:** Django 5.x admin, pytest-django, `uv run`. One choices-only migration (`core/0004`).

Spec: `docs/superpowers/specs/2026-06-16-p7-audit-confirm-merge-design.md`.

---

## File Structure

- `apps/core/models.py` — add two `AuditEvent.Action` choices.
- `apps/core/migrations/0004_alter_auditevent_action.py` — **new** (via `makemigrations`), choices-only `AlterField`.
- `apps/billing/admin.py` — `confirm_view`: one `record_audit_event` on the DRAFT→CONFIRMED branch.
- `apps/members/admin.py` — `merge_training_groups`: one `record_audit_event` after the atomic block.
- Tests (new): `tests/billing/test_admin_confirm_audit.py`, `tests/members/test_admin_merge_audit.py`.

**Verified facts:**
- `AuditEvent.Action` (apps/core/models.py:24-42) is a `TextChoices`; latest catalog value `DATA_EXPORTED`. `AuditEvent` stores `actor` (FK), `actor_label`, `target_type` (model_name, lowercased), `target_id` (str pk), `target_repr`, `metadata` (JSON). Latest core migration: `0003_alter_auditevent_action`.
- `record_audit_event(*, action, actor=None, actor_label="", target=None, target_type="", target_id="", target_repr="", metadata=None, request=None)` (apps/core/audit.py) — fail-safe (returns the row or None; never raises). Passing `target=<instance>` fills target_type/id/repr.
- Both admins already import `from apps.core.audit import record_audit_event` and `from apps.core.models import AuditEvent`.
- `BillingRecordAdmin.confirm_view` (apps/billing/admin.py:123-135): `has_change_permission`-gated, POST-only effect; DRAFT branch does `record.status = CONFIRMED; record.save(update_fields=["status","updated_at"]); message_user(...)`; else info no-op. Endpoint name `billing_billingrecord_confirm`.
- `TrainingGroupAdmin.merge_training_groups` (apps/members/admin.py): gated on `has_delete_permission`; single-group → warning no-op; on `apply=1` validates the target is one of the selected, computes `others`/`other_count`, then `with transaction.atomic(): reparented = Member.objects.filter(training_group__in=others).update(training_group=target); TrainingGroup.objects.filter(pk__in=[...]).delete()`, then `message_user(...)`.
- Test fixtures: billing `active_plan` + `guardian` (tests/billing/conftest.py); `tests/support.py::make_guardian` (account-linked Guardian).

---

### Task 1: Action choices + migration + audit the billing confirm

**Files:**
- Modify: `apps/core/models.py`, `apps/billing/admin.py`
- Create: `apps/core/migrations/0004_alter_auditevent_action.py` (via makemigrations)
- Test: `tests/billing/test_admin_confirm_audit.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/billing/test_admin_confirm_audit.py
"""Confirming a billing record from the admin emits an AuditEvent."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.billing.models import BillingRecord
from apps.core.models import AuditEvent
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _draft(active_plan, guardian):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT, status=BillingRecord.Status.DRAFT,
    )


def test_confirm_emits_audit_event(active_plan, guardian):
    rec = _draft(active_plan, guardian)
    c = _staff_client()
    c.post(reverse("admin:billing_billingrecord_confirm", args=[rec.pk]))
    e = AuditEvent.objects.get(action=AuditEvent.Action.BILLING_RECORD_CONFIRMED)
    assert e.target_type == "billingrecord"
    assert e.target_id == str(rec.pk)
    assert e.actor is not None


def test_already_confirmed_confirm_emits_no_audit(active_plan, guardian):
    rec = _draft(active_plan, guardian)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save(update_fields=["status"])
    c = _staff_client()
    c.post(reverse("admin:billing_billingrecord_confirm", args=[rec.pk]))
    assert not AuditEvent.objects.filter(
        action=AuditEvent.Action.BILLING_RECORD_CONFIRMED
    ).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_admin_confirm_audit.py -v`
Expected: FAIL — `AttributeError: BILLING_RECORD_CONFIRMED` (the choice doesn't exist yet).

- [ ] **Step 3: Add BOTH new Action choices**

In `apps/core/models.py`, in `AuditEvent.Action` (after `DATA_EXPORTED`), add:
```python
        BILLING_RECORD_CONFIRMED = "billing_record_confirmed", "Billing record confirmed"
        TRAINING_GROUPS_MERGED = "training_groups_merged", "Training groups merged"
```
(Both are added now so the single migration covers Task 1 and Task 2.)

- [ ] **Step 4: Generate the choices-only migration**

```bash
uv run python manage.py makemigrations core
```
Confirm a `0004_alter_auditevent_action.py` with a single `AlterField` on `auditevent.action` (choices-only) depending on `0003`.

- [ ] **Step 5: Wire the confirm audit**

In `apps/billing/admin.py` `confirm_view`, add the audit call in the DRAFT branch (after the save, before `message_user`):
```python
        if record.status == BillingRecord.Status.DRAFT:
            record.status = BillingRecord.Status.CONFIRMED
            record.save(update_fields=["status", "updated_at"])
            record_audit_event(
                action=str(AuditEvent.Action.BILLING_RECORD_CONFIRMED),
                actor=request.user, request=request, target=record,
            )
            self.message_user(request, "Ieraksts apstiprināts.")
        else:
            self.message_user(request, "Ieraksts jau ir apstiprināts.", level=messages.INFO)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_admin_confirm_audit.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Lint/type + commit**

```bash
uv run pytest tests/billing/ -q && \
uv run ruff check apps/core/models.py apps/billing/admin.py tests/billing/test_admin_confirm_audit.py && \
uv run mypy apps/core/models.py apps/billing/admin.py && \
git add apps/core/models.py apps/core/migrations/0004_alter_auditevent_action.py apps/billing/admin.py tests/billing/test_admin_confirm_audit.py && \
git commit -m "feat(billing): audit one-click confirm (DRAFT→CONFIRMED) (P7 close-out)"
```

---

### Task 2: Audit the training-group merge

**Files:**
- Modify: `apps/members/admin.py`
- Test: `tests/members/test_admin_merge_audit.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/members/test_admin_merge_audit.py
"""Merging training groups from the admin emits an AuditEvent."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditEvent
from apps.members.models import Member, TrainingGroup
from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_merge_emits_audit_event():
    g = make_guardian(full_name="V")
    target = TrainingGroup.objects.create(name="U10 A")
    dup = TrainingGroup.objects.create(name="U10 A dublikāts")
    Member.objects.create(full_name="A", guardian=g, training_group=dup)
    c = _staff_client()
    c.post(reverse("admin:members_traininggroup_changelist"), {
        "action": "merge_training_groups",
        "_selected_action": [str(target.pk), str(dup.pk)],
        "target": str(target.pk),
        "apply": "1",
    })
    e = AuditEvent.objects.get(action=AuditEvent.Action.TRAINING_GROUPS_MERGED)
    assert e.target_type == "traininggroup"
    assert e.target_id == str(target.pk)
    assert e.actor is not None
    assert e.metadata["merged_group_ids"] == [dup.pk]
    assert e.metadata["merged_names"] == ["U10 A dublikāts"]
    assert e.metadata["members_reparented"] == 1


def test_single_group_merge_emits_no_audit():
    a = TrainingGroup.objects.create(name="U10 A")
    c = _staff_client()
    c.post(reverse("admin:members_traininggroup_changelist"), {
        "action": "merge_training_groups",
        "_selected_action": [str(a.pk)],
    }, follow=True)
    assert not AuditEvent.objects.filter(
        action=AuditEvent.Action.TRAINING_GROUPS_MERGED
    ).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/members/test_admin_merge_audit.py -v`
Expected: FAIL — no `TRAINING_GROUPS_MERGED` audit row written (the choice exists from Task 1, but nothing emits it yet).

- [ ] **Step 3: Wire the merge audit**

In `apps/members/admin.py` `merge_training_groups`, in the `apply == "1"` branch: capture the deleted groups' ids/names before deletion, then record the event after the atomic block. Replace the block so it reads:
```python
            target = get_object_or_404(TrainingGroup, pk=request.POST.get("target"))
            others = [g for g in groups if g.pk != target.pk]
            other_count = len(others)
            merged_ids = [g.pk for g in others]
            merged_names = [g.name for g in others]
            with transaction.atomic():
                reparented = Member.objects.filter(
                    training_group__in=others
                ).update(training_group=target)
                TrainingGroup.objects.filter(pk__in=merged_ids).delete()
            record_audit_event(
                action=str(AuditEvent.Action.TRAINING_GROUPS_MERGED),
                actor=request.user, request=request, target=target,
                metadata={
                    "merged_group_ids": merged_ids,
                    "merged_names": merged_names,
                    "members_reparented": reparented,
                },
            )
            self.message_user(
                request,
                f"Apvienotas {other_count} grupas grupā “{target.name}”; "
                f"pārvietoti {reparented} biedri.",
            )
            return None
```
(`record_audit_event` and `AuditEvent` are already imported in this file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/members/test_admin_merge_audit.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run pytest tests/members/ -q && \
uv run ruff check apps/members/admin.py tests/members/test_admin_merge_audit.py && \
uv run mypy apps/members/admin.py && \
git add apps/members/admin.py tests/members/test_admin_merge_audit.py && \
git commit -m "feat(members): audit training-group merge (P7 close-out)"
```

---

### Task 3: Full gate + docs (P7 complete)

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check --dry-run
```
Expected: pytest/ruff/mypy green; "No changes detected" (migration `0004` committed). Fail loud on any failure.

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "P7 audit close-out delivered" entry — the billing confirm + training-group merge admin actions now emit `AuditEvent`s (`BILLING_RECORD_CONFIRMED` / `TRAINING_GROUPS_MERGED`; merge metadata carries merged ids/names + reparented count); migration `core/0004`. Note **P7 is complete** (pending the manual admin-verification pass).
- `docs/milestones.md`: in the "P7 — remaining / deferred follow-ups" block, mark the audit gap **closed** (confirm + merge now audited); the remaining open items are the manual verification pass and the explicitly-deferred non-P7 items (account-without-guardian admin, parent self-service email change).

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md && git commit -m "docs: record P7 audit close-out; P7 dev work complete"
```

---

## Self-Review Notes

- **Spec coverage:** §2.1 new Action choices + migration → T1 (both choices in one migration); §2.2 confirm wiring → T1; §2.2 merge wiring → T2; §3 testing → T1 (confirm + no-op), T2 (merge + single-group no-op); docs → T3.
- **One migration:** both choices land in `core/0004` during T1, so T2 adds no migration and `makemigrations --check` stays clean.
- **No-op coverage:** the already-confirmed confirm and the single-group merge both assert **no** audit row. (The no-delete-permission merge path also no-ops before the merge; the single-group test covers the "rejected → no audit" contract; a permission test is optional and not added to keep the suite lean — the existing `tests/members/test_admin_group_merge.py::test_merge_requires_delete_permission` already proves that path no-ops.)
- **Fail-safe:** `record_audit_event` never raises, so adding it cannot break the confirm/merge actions.
- **Type/name consistency:** `BILLING_RECORD_CONFIRMED` / `TRAINING_GROUPS_MERGED` choice names and the metadata keys (`merged_group_ids`/`merged_names`/`members_reparented`) are identical across the wiring and the tests.
- **Placeholder scan:** none.

# P7 Slice A — Audit Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record an immutable, queryable audit trail of sensitive staff/system actions (registration review, document access/deletion, agreement state changes, billing push/sync) with who/when/where, a read-only admin viewer, and configurable retention.

**Architecture:** A single append-only `AuditEvent` model in `apps/core`, written through one `record_audit_event(...)` helper called explicitly at each action site (reusing the already-plumbed `actor` params). The target is a denormalized string snapshot (survives deletion). Recording is fail-safe — it never raises into the audited action. A nightly django-q schedule prunes events past `AUDIT_RETENTION_DAYS`.

**Tech Stack:** Django 5.x, django-q2 (scheduled prune), pytest-django, `uv run` for everything. SQLite for tests.

Spec: `docs/superpowers/specs/2026-06-13-p7-audit-baseline-design.md`.

---

## File Structure

- `apps/core/models.py` — add the `AuditEvent` model (+ nested `Action` TextChoices).
- `apps/core/migrations/0001_initial.py` — **core's first migration** (auto-generated; creates the migrations package).
- `apps/core/audit.py` — `record_audit_event(...)` helper + `_client_ip` / `_user_agent` (replaces the empty placeholder).
- `apps/core/admin.py` — **new** read-only `AuditEventAdmin`.
- `apps/core/tasks.py` — **new** `prune_audit_events()`.
- `apps/core/migrations/0002_audit_retention_schedule.py` — register the daily django-q Schedule.
- `fk_cesis_mms/settings.py` — `AUDIT_RETENTION_DAYS`, `AUDIT_PRUNE_HOUR`.
- `tests/helpers/print_settings_snapshot.py` — add the two new keys to the isolation set + snapshot.
- Wiring (modify): `apps/registrations/services.py`, `apps/members/services.py`, `apps/documents/views.py`, `apps/documents/admin.py`, `apps/agreements/services.py`, `apps/integrations/tasks.py`, `apps/billing/admin.py`.
- Tests (new): `tests/core/test_audit_event_model.py`, `tests/core/test_record_audit_event.py`, `tests/core/test_audit_admin.py`, `tests/core/test_prune_audit_events.py`, `tests/core/test_audit_retention_schedule.py`, `tests/<app>/test_audit_*` per wiring task; extend `tests/test_settings_env.py`.

**Conventions to reuse (don't reinvent):**
- Schedule-migration pattern + its test: `apps/billing/migrations/0005_billing_payment_sync_schedule.py`, `tests/billing/test_payment_sync_schedule.py`.
- Env-flag idiom in `settings.py`: `int(os.environ.get("NAME", "<default>"))`.
- Settings-default tests use the **subprocess-isolation pattern** in `tests/test_settings_env.py` (helper `tests/helpers/print_settings_snapshot.py`, `_ENV_ISOLATION_KEYS`, `_run_helper`) — do NOT assert defaults via in-process `django.conf.settings` (ambient env can pollute it).
- Actor params already plumbed: `assign_training_group(member, group, actor)`, `approve_application(application, reviewer, ...)`, `reject_application(application, reviewer, message)`, `request_application_fix(application, reviewer, message)`, `mark_agreement_sent/signed(agreement, actor=...)`, `void_agreement(agreement, actor=...)`.

---

### Task 1: `AuditEvent` model + core's first migration

**Files:**
- Modify: `apps/core/models.py`
- Create: `apps/core/migrations/0001_initial.py` (generated)
- Test: `tests/core/test_audit_event_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_audit_event_model.py
"""AuditEvent model — append-only audit row."""

import pytest

from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_minimal_event_defaults():
    e = AuditEvent.objects.create(action=AuditEvent.Action.APPLICATION_APPROVED)
    e.refresh_from_db()
    assert e.actor is None
    assert e.actor_label == ""
    assert e.metadata == {}
    assert e.ip_address is None
    assert e.user_agent == ""
    assert e.created_at is not None


def test_action_choices_include_catalog():
    values = set(AuditEvent.Action.values)
    assert {
        "application_approved",
        "application_rejected",
        "application_fix_requested",
        "training_group_assigned",
        "training_group_cleared",
        "document_previewed",
        "document_downloaded",
        "document_deleted",
        "agreement_sent",
        "agreement_signed",
        "agreement_voided",
        "agreement_sync_failed",
        "billing_push_triggered",
        "payment_sync_triggered",
        "invoice_push_failed",
        "invoice_send_failed",
        "payment_sync_failed",
    } <= values


def test_default_ordering_newest_first():
    a = AuditEvent.objects.create(action=AuditEvent.Action.DOCUMENT_DOWNLOADED)
    b = AuditEvent.objects.create(action=AuditEvent.Action.DOCUMENT_PREVIEWED)
    assert list(AuditEvent.objects.all()) == [b, a]


def test_no_updated_at_field():
    # Append-only: must not inherit TimeStampedModel's updated_at.
    field_names = {f.name for f in AuditEvent._meta.get_fields()}
    assert "updated_at" not in field_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_audit_event_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'AuditEvent'`.

- [ ] **Step 3: Add the model**

In `apps/core/models.py`, append (keep the existing `TimeStampedModel`):

```python
class AuditEvent(models.Model):
    """Append-only audit record of a sensitive staff/system action.

    Immutable by design — no updated_at. The target is a denormalized string
    snapshot so the row survives the target's deletion (we audit deletions).
    """

    class Action(models.TextChoices):
        APPLICATION_APPROVED = "application_approved", "Application approved"
        APPLICATION_REJECTED = "application_rejected", "Application rejected"
        APPLICATION_FIX_REQUESTED = "application_fix_requested", "Application fix requested"
        TRAINING_GROUP_ASSIGNED = "training_group_assigned", "Training group assigned"
        TRAINING_GROUP_CLEARED = "training_group_cleared", "Training group cleared"
        DOCUMENT_PREVIEWED = "document_previewed", "Document previewed"
        DOCUMENT_DOWNLOADED = "document_downloaded", "Document downloaded"
        DOCUMENT_DELETED = "document_deleted", "Document deleted"
        AGREEMENT_SENT = "agreement_sent", "Agreement sent"
        AGREEMENT_SIGNED = "agreement_signed", "Agreement signed"
        AGREEMENT_VOIDED = "agreement_voided", "Agreement voided"
        AGREEMENT_SYNC_FAILED = "agreement_sync_failed", "Agreement sync failed"
        BILLING_PUSH_TRIGGERED = "billing_push_triggered", "Billing push triggered"
        PAYMENT_SYNC_TRIGGERED = "payment_sync_triggered", "Payment sync triggered"
        INVOICE_PUSH_FAILED = "invoice_push_failed", "Invoice push failed"
        INVOICE_SEND_FAILED = "invoice_send_failed", "Invoice send failed"
        PAYMENT_SYNC_FAILED = "payment_sync_failed", "Payment sync failed"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_events",
    )
    actor_label = models.CharField(max_length=255, blank=True, default="")
    action = models.CharField(max_length=64, choices=Action.choices)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    target_repr = models.CharField(max_length=255, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target_repr}".strip()
```

Ensure `from django.conf import settings` is imported at the top of `apps/core/models.py` (add it if missing).

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations core`
Expected: creates `apps/core/migrations/__init__.py` + `apps/core/migrations/0001_initial.py` with the `AuditEvent` `CreateModel`. If it proposes anything else, STOP and report.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_audit_event_model.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add apps/core/models.py apps/core/migrations/ tests/core/test_audit_event_model.py
git commit -m "feat(core): AuditEvent append-only model (P7 audit baseline)"
```

---

### Task 2: `record_audit_event` helper

**Files:**
- Modify: `apps/core/audit.py` (currently just a docstring)
- Test: `tests/core/test_record_audit_event.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_record_audit_event.py
"""record_audit_event — fail-safe explicit audit recording."""

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_records_system_event_with_label():
    e = record_audit_event(
        action=AuditEvent.Action.INVOICE_PUSH_FAILED,
        actor_label="system: push_billing_record",
        metadata={"error_code": "unavailable"},
    )
    assert e is not None
    assert e.actor is None
    assert e.actor_label == "system: push_billing_record"
    assert e.metadata == {"error_code": "unavailable"}


def test_derives_target_from_instance_and_actor_label_from_user():
    user = User.objects.create_user(username="staff", email="s@example.com")
    plan = User.objects.create_user(username="x")  # any model with a pk/str works as a stand-in
    e = record_audit_event(action=AuditEvent.Action.APPLICATION_APPROVED, actor=user, target=plan)
    assert e.actor == user
    assert e.actor_label == "s@example.com"  # email preferred, else username
    assert e.target_type == "user"
    assert e.target_id == str(plan.pk)
    assert e.target_repr == str(plan)


def test_extracts_ip_and_user_agent_from_request():
    rf = RequestFactory()
    req = rf.get("/x", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1", HTTP_USER_AGENT="UA/1.0")
    e = record_audit_event(action=AuditEvent.Action.DOCUMENT_DOWNLOADED, request=req)
    assert e.ip_address == "203.0.113.9"
    assert e.user_agent == "UA/1.0"


def test_uses_request_user_when_actor_unset():
    rf = RequestFactory()
    user = User.objects.create_user(username="staff2", email="s2@example.com")
    req = rf.get("/x")
    req.user = user
    e = record_audit_event(action=AuditEvent.Action.DOCUMENT_PREVIEWED, request=req)
    assert e.actor == user


def test_never_raises_on_write_error(monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditEvent.objects, "create", boom)
    # Must not raise; returns None.
    result = record_audit_event(action=AuditEvent.Action.APPLICATION_APPROVED)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_record_audit_event.py -v`
Expected: FAIL — `ImportError: cannot import name 'record_audit_event'`.

- [ ] **Step 3: Implement the helper**

Replace the body of `apps/core/audit.py` with:

```python
"""Audit helpers for FK Cēsis MMS.

record_audit_event is the single write path for the AuditEvent log. It is
fail-safe: any error while recording is swallowed and logged, never raised
into the audited business action.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def _user_agent(request) -> str:
    return str(request.META.get("HTTP_USER_AGENT", ""))[:400]


def _label_for(user) -> str:
    return getattr(user, "email", "") or getattr(user, "get_username", lambda: "")() or ""


def record_audit_event(
    *,
    action: str,
    actor=None,
    actor_label: str = "",
    target: Any = None,
    target_type: str = "",
    target_id: str = "",
    target_repr: str = "",
    metadata: dict | None = None,
    request=None,
):
    """Write one AuditEvent. Returns the row, or None if recording failed.

    Never raises — auditing must not break or roll back the audited action.
    """
    try:
        from apps.core.models import AuditEvent

        if request is not None and actor is None:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                actor = user

        if not actor_label and actor is not None:
            actor_label = _label_for(actor)

        if target is not None:
            if not target_type:
                target_type = target._meta.model_name
            if not target_id:
                target_id = str(getattr(target, "pk", "") or "")
            if not target_repr:
                target_repr = str(target)[:255]

        ip = _client_ip(request) if request is not None else None
        ua = _user_agent(request) if request is not None else ""

        return AuditEvent.objects.create(
            action=str(action),
            actor=actor,
            actor_label=actor_label[:255],
            target_type=target_type[:64],
            target_id=target_id[:64],
            target_repr=target_repr[:255],
            metadata=metadata or {},
            ip_address=ip,
            user_agent=ua,
        )
    except Exception:  # noqa: BLE001 — auditing must never break the audited action
        logger.warning("record_audit_event failed for action=%s", action, exc_info=True)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_record_audit_event.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/core/audit.py tests/core/test_record_audit_event.py
uv run mypy apps/core/audit.py
git add apps/core/audit.py tests/core/test_record_audit_event.py
git commit -m "feat(core): record_audit_event fail-safe helper (P7 audit baseline)"
```

---

### Task 3: read-only admin viewer

**Files:**
- Create: `apps/core/admin.py`
- Test: `tests/core/test_audit_admin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_audit_admin.py
"""AuditEventAdmin is read-only and registered."""

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite

from apps.core.admin import AuditEventAdmin
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_registered():
    assert AuditEvent in admin.site._registry


def test_read_only_permissions():
    a = AuditEventAdmin(AuditEvent, AdminSite())
    assert a.has_add_permission(request=None) is False
    assert a.has_change_permission(request=None) is False
    assert a.has_delete_permission(request=None) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_audit_admin.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.core.admin'`.

- [ ] **Step 3: Implement the admin**

```python
# apps/core/admin.py
"""Read-only admin viewer for the AuditEvent log."""

from django.contrib import admin

from apps.core.models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor_label", "target_type", "target_repr", "ip_address")
    list_filter = ("action", "target_type", "created_at")
    search_fields = ("actor_label", "target_repr", "target_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_audit_admin.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/core/admin.py tests/core/test_audit_admin.py
git commit -m "feat(core): read-only AuditEvent admin viewer (P7 audit baseline)"
```

---

### Task 4: retention settings

**Files:**
- Modify: `fk_cesis_mms/settings.py`, `tests/helpers/print_settings_snapshot.py`
- Test: `tests/test_settings_env.py`

**Context:** Defaults MUST be asserted via the subprocess-isolation pattern (in-process `settings` can be polluted by ambient env — this exact lesson came out of P6 review).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings_env.py`:

```python
class TestAuditRetentionSettingsExposed:
    """AUDIT_RETENTION_DAYS / AUDIT_PRUNE_HOUR exposed as settings, asserted via
    the subprocess-isolation snapshot so defaults aren't polluted by ambient env."""

    def _audit_env(self, tmp_path, extra: str = "") -> dict:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SITE_URL=http://audit-test.example.com\n"
            "DJANGO_SECRET_KEY=test-key\n" + extra
        )
        return _run_helper(tmp_path)

    def test_retention_days_default(self, tmp_path):
        snapshot = self._audit_env(tmp_path)
        assert snapshot["audit_retention_days"] == 730

    def test_retention_days_from_env(self, tmp_path):
        snapshot = self._audit_env(tmp_path, "AUDIT_RETENTION_DAYS=365\n")
        assert snapshot["audit_retention_days"] == 365

    def test_prune_hour_default(self, tmp_path):
        snapshot = self._audit_env(tmp_path)
        assert snapshot["audit_prune_hour"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settings_env.py -k "AuditRetention" -v`
Expected: FAIL — `KeyError: 'audit_retention_days'` (snapshot helper doesn't expose it yet).

- [ ] **Step 3: Add the settings + snapshot keys**

In `fk_cesis_mms/settings.py`, near the billing settings block:

```python
# Audit log retention (P7). Nightly prune deletes events older than this many days.
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "730"))
# Local-time hour for the nightly audit prune (offset from billing 3/4).
AUDIT_PRUNE_HOUR = int(os.environ.get("AUDIT_PRUNE_HOUR", "2"))
```

In `tests/helpers/print_settings_snapshot.py`: add `"AUDIT_RETENTION_DAYS"` and `"AUDIT_PRUNE_HOUR"` to `_ENV_ISOLATION_KEYS`, and add to the snapshot dict:

```python
        "audit_retention_days": getattr(settings, "AUDIT_RETENTION_DAYS", "__MISSING__"),
        "audit_prune_hour": getattr(settings, "AUDIT_PRUNE_HOUR", "__MISSING__"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_settings_env.py -k "AuditRetention" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add fk_cesis_mms/settings.py tests/helpers/print_settings_snapshot.py tests/test_settings_env.py
git commit -m "feat(config): AUDIT_RETENTION_DAYS + AUDIT_PRUNE_HOUR (P7 audit baseline)"
```

---

### Task 5: `prune_audit_events` task

**Files:**
- Create: `apps/core/tasks.py`
- Test: `tests/core/test_prune_audit_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_prune_audit_events.py
"""prune_audit_events deletes events older than AUDIT_RETENTION_DAYS."""

import datetime

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.core.models import AuditEvent
from apps.core.tasks import prune_audit_events

pytestmark = pytest.mark.django_db


def _event_aged(days: int) -> AuditEvent:
    e = AuditEvent.objects.create(action=AuditEvent.Action.DOCUMENT_DOWNLOADED)
    # created_at is auto_now_add; rewrite it directly for the test.
    AuditEvent.objects.filter(pk=e.pk).update(
        created_at=timezone.now() - datetime.timedelta(days=days)
    )
    return e


@override_settings(AUDIT_RETENTION_DAYS=30)
def test_deletes_old_keeps_recent():
    old = _event_aged(31)
    recent = _event_aged(5)
    deleted = prune_audit_events()
    assert deleted == 1
    assert not AuditEvent.objects.filter(pk=old.pk).exists()
    assert AuditEvent.objects.filter(pk=recent.pk).exists()


@override_settings(AUDIT_RETENTION_DAYS=30)
def test_boundary_keeps_exactly_at_cutoff():
    e = _event_aged(30)  # exactly at the edge -> kept (cutoff is strictly older)
    prune_audit_events()
    assert AuditEvent.objects.filter(pk=e.pk).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_prune_audit_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.core.tasks'`.

- [ ] **Step 3: Implement the task**

```python
# apps/core/tasks.py
"""Scheduled background tasks for apps.core."""

import datetime
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


def prune_audit_events() -> int:
    """Delete AuditEvent rows older than AUDIT_RETENTION_DAYS. Returns the count."""
    from apps.core.models import AuditEvent

    days = int(getattr(settings, "AUDIT_RETENTION_DAYS", 730))
    cutoff = timezone.now() - datetime.timedelta(days=days)
    deleted, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
    logger.info("prune_audit_events: deleted %s events older than %s days", deleted, days)
    return deleted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_prune_audit_events.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/core/tasks.py tests/core/test_prune_audit_events.py
uv run mypy apps/core/tasks.py
git add apps/core/tasks.py tests/core/test_prune_audit_events.py
git commit -m "feat(core): prune_audit_events retention task (P7 audit baseline)"
```

---

### Task 6: register the daily prune Schedule

**Files:**
- Create: `apps/core/migrations/0002_audit_retention_schedule.py`
- Test: `tests/core/test_audit_retention_schedule.py`

**Context:** Mirror `apps/billing/migrations/0005_billing_payment_sync_schedule.py` exactly (verify the `django_q` dependency tuple matches 0005). Depends on core `0001_initial`.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_audit_retention_schedule.py
import pytest

pytestmark = pytest.mark.django_db


def test_audit_prune_schedule_row_exists():
    from django_q.models import Schedule

    sched = Schedule.objects.filter(name="audit-retention-prune").first()
    assert sched is not None
    assert sched.func == "apps.core.tasks.prune_audit_events"
    assert sched.schedule_type == Schedule.DAILY


def test_audit_prune_schedule_migration_is_idempotent():
    from importlib import import_module
    from django_q.models import Schedule

    migration = import_module("apps.core.migrations.0002_audit_retention_schedule")
    before = Schedule.objects.filter(name="audit-retention-prune").count()
    migration.create_schedule(None, None)
    after = Schedule.objects.filter(name="audit-retention-prune").count()
    assert before == 1
    assert after == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_audit_retention_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError` for the migration / no Schedule row.

- [ ] **Step 3: Create the migration**

First open `apps/billing/migrations/0005_billing_payment_sync_schedule.py` and copy its exact `("django_q", "...")` dependency tuple into the file below (replace if it differs).

```python
# apps/core/migrations/0002_audit_retention_schedule.py
"""Register the nightly audit-retention-prune django-q2 Schedule (P7 audit baseline)."""

import datetime

from django.conf import settings
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "audit-retention-prune"
SCHEDULE_FUNC = "apps.core.tasks.prune_audit_events"


def _next_run():
    hour = getattr(settings, "AUDIT_PRUNE_HOUR", 2)
    now = timezone.localtime()
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def create_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.get_or_create(
        name=SCHEDULE_NAME,
        defaults={
            "func": SCHEDULE_FUNC,
            "schedule_type": Schedule.DAILY,
            "next_run": _next_run(),
        },
    )


def remove_schedule(apps, schema_editor):
    from django_q.models import Schedule

    Schedule.objects.filter(name=SCHEDULE_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_audit_retention_schedule.py -v`
Then: `uv run python manage.py makemigrations --check --dry-run` (expect: no missing migrations).
Expected: PASS (2 passed); no pending model migrations.

- [ ] **Step 5: Commit**

```bash
git add apps/core/migrations/0002_audit_retention_schedule.py tests/core/test_audit_retention_schedule.py
git commit -m "feat(core): register nightly audit-retention-prune Schedule (P7 audit baseline)"
```

---

### Task 7: wire review actions + training-group assignment

**Files:**
- Modify: `apps/registrations/services.py` (`approve_application`, `reject_application`, `request_application_fix`)
- Modify: `apps/members/services.py` (`assign_training_group`)
- Test: `tests/registrations/test_audit_review_actions.py`, `tests/members/test_audit_training_group.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/registrations/test_audit_review_actions.py
"""Review actions emit AuditEvents."""

import pytest
from django.contrib.auth.models import User

from apps.core.models import AuditEvent
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    reject_application,
    request_application_fix,
)

pytestmark = pytest.mark.django_db


def _submitted_app():
    return RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        member_full_name="Bērns",
    )


def test_reject_emits_audit_event():
    reviewer = User.objects.create_user(username="rev", email="rev@example.com")
    app = _submitted_app()
    reject_application(app, reviewer, "trūkst dokumenta")
    e = AuditEvent.objects.get(action=AuditEvent.Action.APPLICATION_REJECTED)
    assert e.actor == reviewer
    assert e.target_type == "registrationapplication"
    assert e.target_id == str(app.pk)


def test_request_fix_emits_audit_event():
    reviewer = User.objects.create_user(username="rev2", email="rev2@example.com")
    app = _submitted_app()
    request_application_fix(app, reviewer, "labo adresi")
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.APPLICATION_FIX_REQUESTED, target_id=str(app.pk)
    ).exists()
```

(Approval also emits `application_approved`; if a ready-to-approve fixture is heavy, assert reject + fix here and cover approve in the existing approval test module by importing `AuditEvent`. The implementer should add an approve assertion if a submitted+documented fixture is readily available.)

```python
# tests/members/test_audit_training_group.py
"""assign_training_group emits AuditEvents."""

import pytest
from django.contrib.auth.models import User

from apps.core.models import AuditEvent
from apps.members.models import Guardian, Member, TrainingGroup
from apps.members.services import assign_training_group

pytestmark = pytest.mark.django_db


def test_assign_and_clear_emit_events():
    actor = User.objects.create_user(username="staff", email="s@example.com")
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    grp = TrainingGroup.objects.create(name="U-12", is_active=True)

    assign_training_group(m, grp, actor)
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.TRAINING_GROUP_ASSIGNED, target_id=str(m.pk)
    ).exists()

    assign_training_group(m, None, actor)
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.TRAINING_GROUP_CLEARED, target_id=str(m.pk)
    ).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/registrations/test_audit_review_actions.py tests/members/test_audit_training_group.py -v`
Expected: FAIL — no matching AuditEvent rows.

- [ ] **Step 3: Wire the calls**

In `apps/registrations/services.py`, add the import `from apps.core.audit import record_audit_event` and `from apps.core.models import AuditEvent` at the top. Then:

- In `approve_application`, immediately after the `application.save(update_fields=[... "approved_member_id" ...])` that persists the approval (before the notification send):

```python
    record_audit_event(
        action=AuditEvent.Action.APPLICATION_APPROVED,
        actor=reviewer,
        target=application,
        metadata={"to_status": application.status, "member_id": application.approved_member_id},
    )
```

- In `reject_application`, after the `application.save(...)` that sets REJECTED:

```python
    record_audit_event(
        action=AuditEvent.Action.APPLICATION_REJECTED,
        actor=reviewer,
        target=application,
        metadata={"to_status": application.status, "has_message": bool(message)},
    )
```

- In `request_application_fix`, after the `application.save(...)` that sets FIX_REQUESTED:

```python
    record_audit_event(
        action=AuditEvent.Action.APPLICATION_FIX_REQUESTED,
        actor=reviewer,
        target=application,
        metadata={"to_status": application.status, "has_message": bool(message)},
    )
```

In `apps/members/services.py`, add the imports and, inside `assign_training_group`, after the `member.save(update_fields=["training_group"])` (the branch that actually changed assignment):

```python
    record_audit_event(
        action=(
            AuditEvent.Action.TRAINING_GROUP_ASSIGNED
            if group is not None
            else AuditEvent.Action.TRAINING_GROUP_CLEARED
        ),
        actor=actor,
        target=member,
        metadata={"group": group.name if group is not None else None},
    )
```

(Note: `assign_training_group` early-returns when the assignment is unchanged — record only on actual change, i.e. after the save.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/registrations/test_audit_review_actions.py tests/members/test_audit_training_group.py -v`
Expected: PASS.

- [ ] **Step 5: Run the broader suites for no regression**

Run: `uv run pytest tests/registrations/ tests/members/ -q`
Expected: PASS.

- [ ] **Step 6: Lint/type + commit**

```bash
uv run ruff check apps/registrations/services.py apps/members/services.py tests/registrations/test_audit_review_actions.py tests/members/test_audit_training_group.py
uv run mypy apps/registrations/services.py apps/members/services.py
git add apps/registrations/services.py apps/members/services.py tests/registrations/test_audit_review_actions.py tests/members/test_audit_training_group.py
git commit -m "feat(audit): record review actions + training-group assignment (P7 audit baseline)"
```

---

### Task 8: wire document events (preview / download / delete)

**Files:**
- Modify: `apps/documents/views.py` (`admin_document_preview`, `admin_document_download`)
- Modify: `apps/registrations/services.py` (`_handle_document_upload` — soft-delete-on-replace)
- Modify: `apps/documents/admin.py` (`DocumentAdmin.delete_model` + `delete_queryset`)
- Test: `tests/documents/test_audit_document_access.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/documents/test_audit_document_access.py
"""Document preview/download/delete emit AuditEvents (with IP on request events)."""

import pytest
from django.contrib.auth.models import User
from django.test import Client

from apps.core.models import AuditEvent
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _doc():
    app = RegistrationApplication.objects.create(member_full_name="B")
    return Document.objects.create(
        application=app, kind=Document.Kind.GUARDIAN_IDENTITY,
        original_filename="id.jpg", content_type="image/jpeg", file_size=10,
        file="private/documents/id.jpg",
    )


def test_download_emits_event_with_ip(client):
    User.objects.create_superuser(username="staff", email="s@example.com", password="pw")
    client.login(username="staff", password="pw")
    doc = _doc()
    client.get(f"/documents/admin/{doc.pk}/download/", HTTP_X_FORWARDED_FOR="203.0.113.5")
    e = AuditEvent.objects.filter(action=AuditEvent.Action.DOCUMENT_DOWNLOADED, target_id=str(doc.pk)).first()
    assert e is not None
    assert e.ip_address == "203.0.113.5"


def test_preview_emits_event(client):
    User.objects.create_superuser(username="staff2", email="s2@example.com", password="pw")
    client.login(username="staff2", password="pw")
    doc = _doc()
    client.get(f"/documents/admin/{doc.pk}/preview/")
    assert AuditEvent.objects.filter(action=AuditEvent.Action.DOCUMENT_PREVIEWED, target_id=str(doc.pk)).exists()
```

IMPORTANT (implementer): verify the actual document URLs with `uv run python manage.py show_urls 2>/dev/null | grep document` or by reading `apps/documents/urls.py`, and fix the test paths to match (`reverse("documents:admin-document-download", ...)` is the robust form — prefer it over hardcoded paths). Also confirm `build_document_response` can serve the test file or stub storage so the view returns 200 before asserting; if storage access fails in tests, patch `apps.documents.services.build_document_response` to return a plain `HttpResponse` so the audit call (which runs before/after the response is built) still fires.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/documents/test_audit_document_access.py -v`
Expected: FAIL — no AuditEvent rows.

- [ ] **Step 3: Wire the calls**

In `apps/documents/views.py`, import `from apps.core.audit import record_audit_event` and `from apps.core.models import AuditEvent`. In each view, after `document = get_admin_accessible_document(...)` and before building the response:

```python
    record_audit_event(
        action=AuditEvent.Action.DOCUMENT_PREVIEWED,  # DOWNLOADED in the download view
        target=document,
        request=request,
        metadata={"kind": document.kind},
    )
```

In `apps/registrations/services.py::_handle_document_upload`, after the existing soft-delete save (`existing.save(update_fields=["deleted_at", "updated_at"])`):

```python
        record_audit_event(
            action=AuditEvent.Action.DOCUMENT_DELETED,
            actor_label=f"parent: {application.guardian_contact_email or application.claimed_email}",
            target=existing,
            metadata={"kind": kind, "reason": "replaced"},
        )
```

In `apps/documents/admin.py`, add to `DocumentAdmin` (staff hard-delete via admin):

```python
    def delete_model(self, request, obj):
        record_audit_event(
            action=AuditEvent.Action.DOCUMENT_DELETED,
            actor=request.user, target=obj, request=request,
            metadata={"kind": obj.kind, "reason": "admin_delete"},
        )
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            record_audit_event(
                action=AuditEvent.Action.DOCUMENT_DELETED,
                actor=request.user, target=obj, request=request,
                metadata={"kind": obj.kind, "reason": "admin_delete"},
            )
        super().delete_queryset(request, queryset)
```

with the imports added at the top of `apps/documents/admin.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/documents/test_audit_document_access.py -v`
Expected: PASS.

- [ ] **Step 5: Run broader suite + commit**

```bash
uv run pytest tests/documents/ tests/registrations/ -q
uv run ruff check apps/documents/views.py apps/documents/admin.py apps/registrations/services.py tests/documents/test_audit_document_access.py
uv run mypy apps/documents/views.py apps/documents/admin.py
git add apps/documents/views.py apps/documents/admin.py apps/registrations/services.py tests/documents/test_audit_document_access.py
git commit -m "feat(audit): record document preview/download/delete (P7 audit baseline)"
```

---

### Task 9: wire agreement events

**Files:**
- Modify: `apps/agreements/services.py` (`mark_agreement_sent`, `mark_agreement_signed`, `void_agreement`)
- Modify: `apps/integrations/tasks.py` (agreement-sync failure branch)
- Test: `tests/agreements/test_audit_agreement_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agreements/test_audit_agreement_events.py
"""Agreement transitions emit AuditEvents; webhook-signed = system actor."""

import pytest
from django.contrib.auth.models import User

from apps.core.models import AuditEvent
from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_sent, mark_agreement_signed, void_agreement
from apps.members.models import Guardian, Member

pytestmark = pytest.mark.django_db


def _agreement():
    g = Guardian.objects.create(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    return Agreement.objects.create(member=m, is_current=True)


def test_sent_and_signed_and_void_emit_events():
    staff = User.objects.create_user(username="s", email="s@example.com")
    a = _agreement()
    mark_agreement_sent(a, actor=staff)
    assert AuditEvent.objects.filter(action=AuditEvent.Action.AGREEMENT_SENT, target_id=str(a.pk)).exists()

    mark_agreement_signed(a, actor=None)  # webhook path -> system actor
    signed = AuditEvent.objects.get(action=AuditEvent.Action.AGREEMENT_SIGNED, target_id=str(a.pk))
    assert signed.actor is None

    void_agreement(a, actor=staff)
    assert AuditEvent.objects.filter(action=AuditEvent.Action.AGREEMENT_VOIDED, target_id=str(a.pk)).exists()
```

(Implementer: adapt `_agreement()` / transition preconditions to the real `Agreement` state machine — e.g. an agreement may need to be in `generated` before `sent`. Read `apps/agreements/services.py` and set the starting state the transitions require.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agreements/test_audit_agreement_events.py -v`
Expected: FAIL — no AuditEvent rows.

- [ ] **Step 3: Wire the calls**

In `apps/agreements/services.py` (imports at top), after each successful transition save:

```python
    # in mark_agreement_sent:
    record_audit_event(action=AuditEvent.Action.AGREEMENT_SENT, actor=actor, target=agreement,
                       metadata={"signing_path": agreement.signing_path})
    # in mark_agreement_signed:
    record_audit_event(action=AuditEvent.Action.AGREEMENT_SIGNED, actor=actor, target=agreement,
                       actor_label="" if actor else "system: docuseal_webhook")
    # in void_agreement:
    record_audit_event(action=AuditEvent.Action.AGREEMENT_VOIDED, actor=actor, target=agreement)
```

In `apps/integrations/tasks.py`, in the agreement DocuSeal create/sync failure branch (where `external_state="failed"` / `external_error_code` is set), add:

```python
    record_audit_event(
        action=AuditEvent.Action.AGREEMENT_SYNC_FAILED,
        actor_label="system: docuseal_sync",
        target=agreement,
        metadata={"error_code": code},
    )
```

(Implementer: match `code`/variable names to the surrounding failure-handling code.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agreements/test_audit_agreement_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run broader suite + commit**

```bash
uv run pytest tests/agreements/ tests/integrations/ -q
uv run ruff check apps/agreements/services.py apps/integrations/tasks.py tests/agreements/test_audit_agreement_events.py
uv run mypy apps/agreements/services.py apps/integrations/tasks.py
git add apps/agreements/services.py apps/integrations/tasks.py tests/agreements/test_audit_agreement_events.py
git commit -m "feat(audit): record agreement state changes + sync failures (P7 audit baseline)"
```

---

### Task 10: wire billing events

**Files:**
- Modify: `apps/billing/admin.py` (`push_to_invoice_ninja`, `sync_payments` actions)
- Modify: `apps/integrations/tasks.py` (push / send / payment-sync failure branches)
- Test: `tests/billing/test_audit_billing_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/billing/test_audit_billing_events.py
"""Billing staff actions + failures emit AuditEvents."""

import pytest
from django.contrib.auth.models import User
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.core.models import AuditEvent
from apps.billing.admin import BillingRecordAdmin
from apps.billing.models import BillingRecord

pytestmark = pytest.mark.django_db


def test_push_action_emits_triggered_event(active_plan, guardian):
    from decimal import Decimal
    from apps.members.models import Member
    m = Member.objects.create(full_name="B", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300"), final_amount=Decimal("300"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT, status=BillingRecord.Status.CONFIRMED,
    )
    admin_obj = BillingRecordAdmin(BillingRecord, AdminSite())
    req = RequestFactory().post("/admin/")
    req.user = User.objects.create_user(username="staff", email="s@example.com")
    # message_user needs the messages framework; attach a no-op if needed.
    from django.contrib.messages.storage.fallback import FallbackStorage
    req.session = {}
    req._messages = FallbackStorage(req)
    admin_obj.push_to_invoice_ninja(req, BillingRecord.objects.filter(pk=rec.pk))
    assert AuditEvent.objects.filter(
        action=AuditEvent.Action.BILLING_PUSH_TRIGGERED, target_id=str(rec.pk)
    ).exists()
```

(`active_plan` + `guardian` fixtures live in `tests/billing/conftest.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_audit_billing_events.py -v`
Expected: FAIL — no AuditEvent row.

- [ ] **Step 3: Wire the calls**

In `apps/billing/admin.py` (imports at top), inside `push_to_invoice_ninja`, for each confirmed record actually enqueued:

```python
            record_audit_event(
                action=AuditEvent.Action.BILLING_PUSH_TRIGGERED,
                actor=request.user, target=record, request=request,
            )
```

and analogously in `sync_payments` with `AuditEvent.Action.PAYMENT_SYNC_TRIGGERED`.

In `apps/integrations/tasks.py`, in the three failure branches (push invoice create, invoice send, payment sync) where `external_error_code` / `payment_error_code` is set, add the matching event:

```python
    record_audit_event(
        action=AuditEvent.Action.INVOICE_PUSH_FAILED,   # / INVOICE_SEND_FAILED / PAYMENT_SYNC_FAILED
        actor_label="system: <task_name>",
        target=record,                                   # or billing_invoice
        metadata={"error_code": code},
    )
```

(Implementer: place each at the right failure branch; use the record/invoice in scope and the local error `code`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_audit_billing_events.py -v`
Expected: PASS.

- [ ] **Step 5: Run broader suite + commit**

```bash
uv run pytest tests/billing/ tests/integrations/ -q
uv run ruff check apps/billing/admin.py apps/integrations/tasks.py tests/billing/test_audit_billing_events.py
uv run mypy apps/billing/admin.py apps/integrations/tasks.py
git add apps/billing/admin.py apps/integrations/tasks.py tests/billing/test_audit_billing_events.py
git commit -m "feat(audit): record billing staff actions + push/send/sync failures (P7 audit baseline)"
```

---

### Task 11: full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`, `.env.example`

- [ ] **Step 1: Full gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```
Expected: all green. Fail loud on any failure — fix before proceeding. (`ruff format` is NOT an enforced gate — do not reformat unrelated files.)

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "P7 Slice A — audit baseline delivered" entry — `AuditEvent` model + `record_audit_event` helper (fail-safe), event catalog + wiring sites, read-only admin viewer, `AUDIT_RETENTION_DAYS` (730) prune via `audit-retention-prune` daily Schedule, IP/UA on request events, redaction rule. Note P7 Slices B (export) + C (admin polish) remain.
- `docs/milestones.md`: under "P7 acceptance" / the audit-debt note, mark the audit baseline delivered (items 4, 8, 9 audit-portion).
- `.env.example`: add `AUDIT_RETENTION_DAYS=730` and `AUDIT_PRUNE_HOUR=2` with a comment.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md .env.example
git commit -m "docs: record P7 Slice A audit baseline delivery"
```

---

## Self-Review Notes

- **Spec coverage:** §4 model → T1; §6 helper (incl. fail-safe) → T2; §7 admin → T3; §8 retention (settings/task/schedule) → T4/T5/T6; §5 catalog wiring → T7 (review+training), T8 (documents), T9 (agreements), T10 (billing); §9 redaction → enforced in each wiring task's `metadata` (status/error/kind/group only); §10 testing → each task's tests; §11 acceptance → covered; gate/docs → T11.
- **Fail-safe (spec §6, acceptance #1):** T2 wraps everything in try/except and is tested by `test_never_raises_on_write_error`.
- **Routine-success exclusion (spec §3, acceptance #3):** billing/agreement wiring records only `*_triggered` (staff) and `*_failed` (system) — no per-row sync-success events.
- **Name/type consistency:** `record_audit_event(*, action, actor, actor_label, target, metadata, request, ...)` and `AuditEvent.Action.<X>` enum values are used identically across T2 and every wiring task; `prune_audit_events` (T5) ↔ schedule func string (T6) ↔ `apps.core.tasks` path match.
- **Migrations:** core `0001_initial` (model, T1) then `0002_audit_retention_schedule` (T6, depends on 0001). No other model migrations.
- **Known implementer caveats flagged inline:** real document URL names (T8), `Agreement` state-machine preconditions (T9), exact failure-branch variable names (T9/T10), and admin `message_user`/messages setup in tests (T10).

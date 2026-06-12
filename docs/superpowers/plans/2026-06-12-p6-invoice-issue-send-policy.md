# Invoice Issue/Send Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-issue + email each installment invoice to the parent on/after the 1st of its due month, via a nightly job, gated by a safety flag — while the push action keeps creating invoices as Draft.

**Architecture:** Separate *create* (unchanged: push creates all installment invoices in Invoice Ninja as Draft) from *issue+send* (a new nightly `django-q` sweep that emails each Draft invoice when its due month arrives; emailing a Draft in IN flips it to Sent). A pure predicate decides eligibility; the IN bulk-email call is added behind the existing `invoice_platform` seam; a settings flag (`BILLING_AUTOSEND_ENABLED`, default off) gates the whole job for a safe rollout.

**Tech Stack:** Django 5.x, django-q2 (scheduled tasks), pytest-django, `uv run` for everything (pytest/ruff/mypy/manage.py). SQLite for tests.

Spec: `docs/superpowers/specs/2026-06-12-p6-invoice-issue-send-policy-design.md`.

---

## File Structure

- `apps/integrations/invoice_ninja.py` — add `email_invoice(external_invoice_id)` (IN bulk-email call).
- `apps/integrations/invoice_platform.py` — add `email_invoice(...)` to the stub/invoiceninja dispatch seam.
- `apps/billing/models.py` — add `BillingInvoice.sent_at` field.
- `apps/billing/migrations/0008_billinginvoice_sent_at.py` — schema migration (auto-generated).
- `apps/billing/services.py` — add `is_invoice_due_to_send(invoice, today)` pure predicate.
- `fk_cesis_mms/settings.py` — add `BILLING_AUTOSEND_ENABLED` + `BILLING_SEND_DUE_HOUR`.
- `apps/integrations/tasks.py` — add `send_due_invoices()` nightly task.
- `apps/billing/migrations/0009_billing_send_due_schedule.py` — register the daily `Schedule`.
- Tests (new):
  - `tests/billing/test_invoice_ninja_email.py`
  - `tests/billing/test_invoice_platform_email.py`
  - `tests/billing/test_billing_invoice_sent_at.py`
  - `tests/billing/test_send_eligibility.py`
  - `tests/billing/test_send_due_invoices.py`
  - `tests/billing/test_send_due_schedule.py`
  - `tests/test_settings_env.py` (extend — settings flag default)

**Conventions discovered (use these, don't reinvent):**
- The push test pattern + fixtures live in `tests/billing/test_push_billing_record.py` and `tests/billing/conftest.py`: fixtures `active_plan` (installment_count=10, first_installment_month=9), `guardian` (email `anna@example.com`), `member`.
- The nightly-sweep pattern is `sync_billing_payments()` in `apps/integrations/tasks.py` (per-row try/except, `logger.warning`, continue).
- The schedule-migration pattern + its test are `apps/billing/migrations/0005_billing_payment_sync_schedule.py` and `tests/billing/test_payment_sync_schedule.py`.
- Error classification: `_classify_invoice_error(exc) -> (code, retryable)` in `tasks.py`, keyed off `invoice_platform.InvoicePlatform*Error`.
- Env-flag style in settings: `os.environ.get("NAME", "false").lower() in {"1", "true", "yes"}`.

---

### Task 1: `email_invoice` — IN call + platform seam

**Files:**
- Modify: `apps/integrations/invoice_ninja.py`
- Modify: `apps/integrations/invoice_platform.py`
- Test: `tests/billing/test_invoice_ninja_email.py`, `tests/billing/test_invoice_platform_email.py`

- [ ] **Step 1: Write the failing tests**

`tests/billing/test_invoice_ninja_email.py`:

```python
"""IN provider: email_invoice issues the v5 bulk-email action."""

import pytest


def test_email_invoice_posts_bulk_email_action(monkeypatch):
    from apps.integrations import invoice_ninja

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

    def fake_request(method, url, api_key, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _Resp()

    monkeypatch.setattr(invoice_ninja, "_require_config", lambda: ("https://in.example/api/v1", "key"))
    monkeypatch.setattr(invoice_ninja, "_request", fake_request)

    invoice_ninja.email_invoice("HASHED123")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://in.example/api/v1/invoices/bulk"
    assert captured["json"] == {"action": "email", "ids": ["HASHED123"]}


def test_email_invoice_raises_on_error_status(monkeypatch):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformConfigError

    class _Resp:
        status_code = 422
        text = "bad"

    monkeypatch.setattr(invoice_ninja, "_require_config", lambda: ("https://in.example/api/v1", "key"))
    monkeypatch.setattr(invoice_ninja, "_request", lambda *a, **k: _Resp())

    with pytest.raises(InvoicePlatformConfigError):
        invoice_ninja.email_invoice("HASHED123")
```

`tests/billing/test_invoice_platform_email.py`:

```python
"""Platform seam: email_invoice dispatches stub vs invoiceninja."""

import pytest
from django.test import override_settings


@override_settings(INVOICE_PROVIDER_MODE="stub")
def test_email_invoice_stub_is_noop():
    from apps.integrations import invoice_platform

    assert invoice_platform.email_invoice("anything") is None


@override_settings(INVOICE_PROVIDER_MODE="invoiceninja")
def test_email_invoice_invoiceninja_delegates(monkeypatch):
    from apps.integrations import invoice_platform, invoice_ninja

    called = {}
    monkeypatch.setattr(invoice_ninja, "email_invoice", lambda eid: called.setdefault("id", eid))

    invoice_platform.email_invoice("HASHED123")
    assert called["id"] == "HASHED123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_invoice_ninja_email.py tests/billing/test_invoice_platform_email.py -v`
Expected: FAIL — `AttributeError: module 'apps.integrations.invoice_ninja' has no attribute 'email_invoice'` (and same for invoice_platform).

- [ ] **Step 3: Implement the IN call**

In `apps/integrations/invoice_ninja.py`, add after `create_invoice` (mirror its error handling — `_request` already raises typed errors for 401/403/404/5xx/timeouts; a generic `>=400` becomes a config error like `create_invoice` does):

```python
def email_invoice(external_invoice_id: str) -> None:
    """Issue + email an invoice via the v5 bulk action. Emailing a Draft in
    Invoice Ninja transitions it to Sent and sends the templated invoice email
    (PDF + payment link). Idempotent at the IN side (re-emailing a sent invoice
    just re-sends)."""
    api_url, api_key = _require_config()
    resp = _request(
        "POST",
        f"{api_url}/invoices/bulk",
        api_key,
        json={"action": "email", "ids": [external_invoice_id]},
    )
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(
            f"invoice email rejected: {resp.status_code} {resp.text}"
        )
```

- [ ] **Step 4: Implement the seam**

In `apps/integrations/invoice_platform.py`, add after `fetch_invoice_payment`:

```python
def email_invoice(external_invoice_id: str) -> None:
    mode = _mode()
    if mode == "stub":
        return None
    if mode == "invoiceninja":
        from apps.integrations import invoice_ninja

        return invoice_ninja.email_invoice(external_invoice_id)
    raise InvoicePlatformConfigError(f"unknown invoice provider mode: {mode}")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_invoice_ninja_email.py tests/billing/test_invoice_platform_email.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Lint/type + commit**

```bash
uv run ruff check apps/integrations/invoice_ninja.py apps/integrations/invoice_platform.py tests/billing/test_invoice_ninja_email.py tests/billing/test_invoice_platform_email.py
uv run mypy apps/integrations/invoice_ninja.py apps/integrations/invoice_platform.py
git add apps/integrations/invoice_ninja.py apps/integrations/invoice_platform.py tests/billing/test_invoice_ninja_email.py tests/billing/test_invoice_platform_email.py
git commit -m "feat(integrations): email_invoice (IN bulk-email action) behind the platform seam (P6 invoice send)"
```

---

### Task 2: `BillingInvoice.sent_at` field

**Files:**
- Modify: `apps/billing/models.py` (the `BillingInvoice` model)
- Create: `apps/billing/migrations/0008_billinginvoice_sent_at.py` (auto-generated)
- Test: `tests/billing/test_billing_invoice_sent_at.py`

- [ ] **Step 1: Write the failing test**

```python
"""BillingInvoice.sent_at field (set when the issue+email succeeds)."""

import pytest

pytestmark = pytest.mark.django_db


def test_sent_at_defaults_to_none(active_plan, guardian):
    from decimal import Decimal
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.CONFIRMED,
    )
    inv = BillingInvoice.objects.create(
        billing_record=rec, sequence=0, due_date=rec.created_at.date(),
        amount=Decimal("300.00"),
    )
    inv.refresh_from_db()
    assert inv.sent_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_billing_invoice_sent_at.py -v`
Expected: FAIL — the model has no `sent_at` (the test attribute access errors, or the migration to create the column is missing).

- [ ] **Step 3: Add the field**

In `apps/billing/models.py`, in the `BillingInvoice` model, add alongside `last_synced_at`:

```python
    sent_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 4: Generate the migration**

Run: `uv run python manage.py makemigrations billing`
Expected: creates `apps/billing/migrations/0008_billinginvoice_sent_at.py` adding the `sent_at` field.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_billing_invoice_sent_at.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/billing/models.py apps/billing/migrations/0008_billinginvoice_sent_at.py tests/billing/test_billing_invoice_sent_at.py
git commit -m "feat(billing): BillingInvoice.sent_at field (P6 invoice send)"
```

---

### Task 3: `is_invoice_due_to_send` predicate

**Files:**
- Modify: `apps/billing/services.py`
- Test: `tests/billing/test_send_eligibility.py`

**Context:** Pure date+state predicate. Eligible iff the invoice exists in IN (`external_invoice_id` set), is still Draft (`external_status == "created"`), and `today >= due_date.replace(day=1)` (on/after the 1st of its due month). The guardian-email check and the autosend flag are the *job's* concern (Task 5), not this predicate — keep it pure for easy testing. Uses lightweight stand-in objects so no DB is needed.

- [ ] **Step 1: Write the failing test**

```python
"""is_invoice_due_to_send — pure eligibility predicate (date + draft state)."""

import datetime
from types import SimpleNamespace

from apps.billing.services import is_invoice_due_to_send


def _inv(due_date, external_status="created", external_invoice_id="inv-1"):
    return SimpleNamespace(
        due_date=due_date,
        external_status=external_status,
        external_invoice_id=external_invoice_id,
    )


def test_eligible_on_first_of_due_month():
    today = datetime.date(2026, 9, 1)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is True


def test_not_eligible_last_day_of_prior_month():
    today = datetime.date(2026, 8, 31)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is False


def test_eligible_mid_month_current_month_signup():
    today = datetime.date(2026, 9, 10)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is True


def test_eligible_overdue_catch_up():
    today = datetime.date(2026, 11, 5)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is True


def test_not_eligible_when_already_sent():
    today = datetime.date(2026, 9, 1)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20), external_status="sent"), today) is False


def test_not_eligible_without_external_id():
    today = datetime.date(2026, 9, 1)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20), external_invoice_id=""), today) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_send_eligibility.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_invoice_due_to_send'`.

- [ ] **Step 3: Implement the predicate**

In `apps/billing/services.py`, add (use `import datetime` if the module doesn't already; it does — `derive_installment_schedule` uses it):

```python
def is_invoice_due_to_send(invoice, today: "datetime.date") -> bool:
    """True when a Draft installment invoice should be issued + emailed: it
    exists in Invoice Ninja, is still Draft, and today is on/after the first
    day of its due month. Sending from the 1st gives the parent the whole month
    until the due day; using >= also covers mid-season signups and overdue
    catch-up. (Guardian-email presence + the autosend flag are checked by the
    caller — see apps.integrations.tasks.send_due_invoices.)"""
    if not invoice.external_invoice_id:
        return False
    if invoice.external_status != "created":
        return False
    return today >= invoice.due_date.replace(day=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_send_eligibility.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/billing/services.py tests/billing/test_send_eligibility.py
git commit -m "feat(billing): is_invoice_due_to_send eligibility predicate (P6 invoice send)"
```

---

### Task 4: `BILLING_AUTOSEND_ENABLED` + `BILLING_SEND_DUE_HOUR` settings

**Files:**
- Modify: `fk_cesis_mms/settings.py` (near the `INVOICE_PROVIDER_MODE` block, ~line 179)
- Test: `tests/test_settings_env.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_settings_env.py`:

```python
def test_billing_autosend_defaults_off():
    from django.conf import settings

    assert settings.BILLING_AUTOSEND_ENABLED is False


def test_billing_send_due_hour_default():
    from django.conf import settings

    assert isinstance(settings.BILLING_SEND_DUE_HOUR, int)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_settings_env.py -k "billing_autosend or send_due_hour" -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'BILLING_AUTOSEND_ENABLED'`.

- [ ] **Step 3: Add the settings**

In `fk_cesis_mms/settings.py`, after the `INVOICE_NINJA_API_KEY` line (~181):

```python
# Billing auto-send (P6 invoice issue/send policy). When False, the nightly
# send job is a no-op — deploy the machinery, verify on one parent, then flip on.
BILLING_AUTOSEND_ENABLED = os.environ.get("BILLING_AUTOSEND_ENABLED", "false").lower() in {"1", "true", "yes"}
# Hour (local time) for the nightly send sweep; offset from payment-sync (3).
BILLING_SEND_DUE_HOUR = int(os.environ.get("BILLING_SEND_DUE_HOUR", "4"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_settings_env.py -k "billing_autosend or send_due_hour" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add fk_cesis_mms/settings.py tests/test_settings_env.py
git commit -m "feat(config): BILLING_AUTOSEND_ENABLED (default off) + BILLING_SEND_DUE_HOUR (P6 invoice send)"
```

---

### Task 5: `send_due_invoices()` nightly task

**Files:**
- Modify: `apps/integrations/tasks.py`
- Test: `tests/billing/test_send_due_invoices.py`

**Context:** The sweep. Gated by `BILLING_AUTOSEND_ENABLED`. Selects Draft invoices (`external_status="created"`, non-empty `external_invoice_id`), filters by `is_invoice_due_to_send`, skips+logs guardians with no email, calls `invoice_platform.email_invoice`, and on success flips the row to `"sent"` + stamps `sent_at`. Per-row isolation like `sync_billing_payments` — failures record `external_error_code`, log, and leave the row `"created"` for the next nightly run (the nightly cadence is the retry loop; do NOT re-raise). `invoice_platform` and `_classify_invoice_error` are already imported/defined at the top of `tasks.py`.

- [ ] **Step 1: Write the failing tests**

```python
"""send_due_invoices — nightly issue+email sweep."""

import datetime
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _months_ahead(d: datetime.date, n: int) -> datetime.date:
    m = d.month - 1 + n
    y = d.year + m // 12
    return datetime.date(y, m % 12 + 1, 20)


def _draft_invoice(active_plan, guardian, *, due_date, external_id="inv-1", status="created"):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.INSTALLMENTS,
        status=BillingRecord.Status.CONFIRMED, external_status="synced",
    )
    return BillingInvoice.objects.create(
        billing_record=rec, sequence=0, due_date=due_date, amount=Decimal("30.00"),
        external_invoice_id=external_id, external_status=status,
    )


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_sends_due_invoice_and_marks_sent(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-A")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == ["inv-A"]
    assert inv.external_status == "sent"
    assert inv.sent_at is not None


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_skips_future_installment(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=_months_ahead(timezone.localdate(), 2), external_id="inv-F")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == []
    assert inv.external_status == "created"


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_skips_guardian_without_email(active_plan, monkeypatch):
    from apps.members.models import Guardian
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    no_email_guardian = Guardian.objects.create(full_name="Bez Pasta", email="")
    inv = _draft_invoice(active_plan, no_email_guardian, due_date=timezone.localdate(), external_id="inv-N")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == []
    assert inv.external_status == "created"


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_records_error_and_continues_on_failure(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    def boom(eid):
        raise invoice_platform.InvoicePlatformTransientError("down")

    monkeypatch.setattr(invoice_platform, "email_invoice", boom)
    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-E")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert inv.external_status == "created"  # stays draft -> retried next run
    assert inv.external_error_code == "unavailable"


@override_settings(BILLING_AUTOSEND_ENABLED=True)
def test_idempotent_does_not_resend_sent(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    calls = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: calls.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-I")
    tasks.send_due_invoices()
    tasks.send_due_invoices()  # second run

    assert calls == ["inv-I"]  # emailed once


@override_settings(BILLING_AUTOSEND_ENABLED=False)
def test_noop_when_autosend_disabled(active_plan, guardian, monkeypatch):
    from apps.integrations import invoice_platform, tasks

    sent = []
    monkeypatch.setattr(invoice_platform, "email_invoice", lambda eid: sent.append(eid))

    inv = _draft_invoice(active_plan, guardian, due_date=timezone.localdate(), external_id="inv-D")
    tasks.send_due_invoices()

    inv.refresh_from_db()
    assert sent == []
    assert inv.external_status == "created"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/billing/test_send_due_invoices.py -v`
Expected: FAIL — `AttributeError: module 'apps.integrations.tasks' has no attribute 'send_due_invoices'`.

- [ ] **Step 3: Implement the task**

In `apps/integrations/tasks.py`, add (after `sync_billing_payments`, in the payment/billing section):

```python
def send_due_invoices() -> None:
    """Scheduled nightly sweep: issue + email each Draft installment invoice
    on/after the 1st of its due month. Gated by BILLING_AUTOSEND_ENABLED.

    Emailing a Draft in Invoice Ninja flips it to Sent and delivers the
    invoice email. Per-row errors are recorded on the invoice and logged so one
    bad row never aborts the run; the row stays 'created' and is retried on the
    next nightly run (the cadence is the retry loop)."""
    from django.conf import settings

    if not getattr(settings, "BILLING_AUTOSEND_ENABLED", False):
        logger.info("send_due_invoices: BILLING_AUTOSEND_ENABLED is off; skipping")
        return

    from apps.billing.models import BillingInvoice
    from apps.billing.services import is_invoice_due_to_send

    today = timezone.localdate()
    invoices = (
        BillingInvoice.objects.filter(external_status="created")
        .exclude(external_invoice_id="")
        .select_related("billing_record__member__guardian")
    )
    for billing_invoice in invoices:
        if not is_invoice_due_to_send(billing_invoice, today):
            continue
        guardian = billing_invoice.billing_record.member.guardian
        if not guardian.email:
            logger.warning(
                "send_due_invoices: invoice %s skipped — guardian %s has no email",
                billing_invoice.pk,
                guardian.pk,
            )
            continue
        try:
            invoice_platform.email_invoice(billing_invoice.external_invoice_id)
        except Exception as exc:  # noqa: BLE001 - batch sweep isolates per-row failures
            code, _retry = _classify_invoice_error(exc)
            billing_invoice.external_error_code = code
            billing_invoice.save(update_fields=["external_error_code", "updated_at"])
            logger.warning(
                "send_due_invoices: email failed for invoice %s: %s",
                billing_invoice.pk,
                exc,
            )
            continue
        billing_invoice.external_status = "sent"
        billing_invoice.sent_at = timezone.now()
        billing_invoice.external_error_code = ""
        billing_invoice.save(
            update_fields=["external_status", "sent_at", "external_error_code", "updated_at"]
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/billing/test_send_due_invoices.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Lint/type + commit**

```bash
uv run ruff check apps/integrations/tasks.py tests/billing/test_send_due_invoices.py
uv run mypy apps/integrations/tasks.py
git add apps/integrations/tasks.py tests/billing/test_send_due_invoices.py
git commit -m "feat(integrations): send_due_invoices nightly issue+email sweep (P6 invoice send)"
```

---

### Task 6: Register the daily `Schedule`

**Files:**
- Create: `apps/billing/migrations/0009_billing_send_due_schedule.py`
- Test: `tests/billing/test_send_due_schedule.py`

**Context:** Mirror `apps/billing/migrations/0005_billing_payment_sync_schedule.py` exactly, with a distinct name/func and the send hour. Its test mirrors `tests/billing/test_payment_sync_schedule.py`.

- [ ] **Step 1: Write the failing test**

`tests/billing/test_send_due_schedule.py`:

```python
import pytest

pytestmark = pytest.mark.django_db


def test_send_due_schedule_row_exists():
    from django_q.models import Schedule

    sched = Schedule.objects.filter(name="billing-send-due-invoices").first()
    assert sched is not None
    assert sched.func == "apps.integrations.tasks.send_due_invoices"
    assert sched.schedule_type == Schedule.DAILY


def test_send_due_schedule_migration_is_idempotent():
    from importlib import import_module

    migration = import_module("apps.billing.migrations.0009_billing_send_due_schedule")
    from django_q.models import Schedule

    before = Schedule.objects.filter(name="billing-send-due-invoices").count()
    migration.create_schedule(None, None)
    after = Schedule.objects.filter(name="billing-send-due-invoices").count()
    assert before == 1
    assert after == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/billing/test_send_due_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apps.billing.migrations.0009_billing_send_due_schedule'` (and no Schedule row).

- [ ] **Step 3: Create the migration**

`apps/billing/migrations/0009_billing_send_due_schedule.py`:

```python
"""Register the nightly billing send-due-invoices django-q2 Schedule (P6 invoice send)."""

import datetime

from django.conf import settings
from django.db import migrations
from django.utils import timezone

SCHEDULE_NAME = "billing-send-due-invoices"
SCHEDULE_FUNC = "apps.integrations.tasks.send_due_invoices"


def _next_run():
    hour = getattr(settings, "BILLING_SEND_DUE_HOUR", 4)
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
        ("billing", "0008_billinginvoice_sent_at"),
        ("django_q", "0019_alter_task_options_alter_ormq_key_alter_ormq_lock_and_more"),
    ]

    operations = [
        migrations.RunPython(create_schedule, remove_schedule),
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/billing/test_send_due_schedule.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/billing/migrations/0009_billing_send_due_schedule.py tests/billing/test_send_due_schedule.py
git commit -m "feat(billing): register nightly send-due-invoices Schedule (P6 invoice send)"
```

---

### Task 7: Full gate + docs

**Files:**
- Modify: `AGENTS.md`, `docs/milestones.md`, `.env.example` (if present — else note in AGENTS.md)

- [ ] **Step 1: Full gate**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
```
Expected: all green. Fail loud on any failure — fix before proceeding. (`ruff format` is NOT an enforced gate in this repo — do not reformat unrelated files.)

- [ ] **Step 2: Update docs**

- `AGENTS.md`: add a "P6 invoice issue/send policy delivered" entry — push still creates Draft; nightly `send_due_invoices` issues+emails each installment on/after the 1st of its due month (IN bulk `email` action → flips Draft→Sent); gated by `BILLING_AUTOSEND_ENABLED` (default off); `BillingInvoice.sent_at` added; daily `billing-send-due-invoices` Schedule; per-row error isolation, no-email guardians skipped+logged. Note **LAN/sandbox acceptance pending** and that prod must set `BILLING_AUTOSEND_ENABLED=true` to activate.
- `docs/milestones.md`: mark the "Invoice issue/send policy" billing-gap item delivered (flag default off; pending sandbox verification).
- If `.env.example` exists, add `BILLING_AUTOSEND_ENABLED=false` and `BILLING_SEND_DUE_HOUR=4` with a comment; otherwise document the two env vars in the AGENTS.md entry.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md docs/milestones.md .env.example
git commit -m "docs: record P6 invoice issue/send policy delivery"
```

---

## LAN / Sandbox Acceptance (after implementation, before sign-off)

Against a local instance + qcluster with a **real Invoice Ninja sandbox/test company** (`INVOICE_PROVIDER_MODE=invoiceninja`, valid `INVOICE_NINJA_API_*`), console email backend not relevant (IN sends the email itself):

- **S1 (no burst):** Confirm + push an installment record (e.g. 10 installments). All land as Draft in IN; no emails sent.
- **S2 (autosend off):** With `BILLING_AUTOSEND_ENABLED=false`, run `send_due_invoices` (or trigger the schedule) → nothing sent.
- **S3 (current installment sends):** With the flag on, run `send_due_invoices` → the current-month installment flips Draft→Sent in IN, the test parent receives exactly one invoice email; future installments stay Draft.
- **S4 (idempotent):** Run again → no second email for the already-sent invoice.
- **S5 (no-email guardian):** A record whose guardian has no email → that invoice is skipped, logged, left Draft.

Record results in `docs/acceptance/2026-06-12-p6-invoice-issue-send-policy-lan-acceptance.md` and add the sign-off line to the AGENTS.md entry.

---

## Self-Review Notes

- **Spec coverage:** §2 create/send split → Tasks 1+5 (create unchanged). §3 predicate → Task 3. §4 IN mechanism → Task 1. §5 state (`sent_at`, failed-send stays `created`) → Tasks 2+5. §6 job → Task 5. §6 schedule → Task 6. §7 safety flag → Tasks 4+5. §9 error handling (per-row, no-email skip) → Task 5. §11 testing → each task's tests + LAN section. §12 acceptance → covered.
- **Failed-send semantics:** Task 5 leaves the row `"created"` + records `external_error_code` (never re-raises, never sets `"failed"`) — matches spec §5/§9 so the nightly cadence retries.
- **Type/name consistency:** `email_invoice(external_invoice_id)` (Tasks 1, 5), `is_invoice_due_to_send(invoice, today)` (Tasks 3, 5), `send_due_invoices()` (Tasks 5, 6), `BILLING_AUTOSEND_ENABLED` (Tasks 4, 5), `external_status` values `"created"`/`"sent"` (Tasks 2, 3, 5) — consistent across tasks.
- **No new migrations beyond two:** `0008` (sent_at schema) + `0009` (schedule data). Confirmed `0007` is the current latest billing migration.

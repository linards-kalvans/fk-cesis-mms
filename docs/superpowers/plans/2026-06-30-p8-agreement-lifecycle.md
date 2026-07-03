# P8 Agreement Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe agreement amendment/discontinuation lifecycle, member discontinued status, parent-visible history, and Invoice Ninja credit notes for selected unpaid future invoices.

**Architecture:** Keep lifecycle rules in service functions, not admin views. Store parent-facing business history in `AgreementLifecycleEvent`; keep forensic/operator records in `AuditEvent`. Use existing Invoice Ninja adapter + django-q task patterns for credit-note creation/apply, with a live sandbox spike before freezing provider payloads.

**Tech Stack:** Django 5, PostgreSQL/SQLite migrations, pytest + pytest-django, django-q2, existing Invoice Ninja adapter, Django admin/templates, server-rendered parent templates.

---

## 1. Design decisions

### 1.1 Agreement lifecycle states

Add `superseded` and `discontinued` to `Agreement.State`.

Why:
- `void` already means cancelled agreement; replacement needs distinct state.
- `superseded` preserves signed original while allowing a new current agreement.
- `discontinued` keeps current terminal status visible to staff and parents.

State rules:

```text
signed --minor amendment--> signed + AgreementLifecycleEvent(minor_amendment)
signed --material amendment--> old agreement superseded/is_current=False + new generated/is_current=True
signed --discontinue--> agreement discontinued/is_current=True + member discontinued
```

### 1.2 Separate lifecycle history from audit

Add `AgreementLifecycleEvent`.

Why:
- `AuditEvent` is operator/forensic trail and redacted.
- Parent portal needs business history: amendment note, replacement, discontinuation date/reason.
- History survives as domain state and can be queried without parsing audit metadata.

### 1.3 Billing adjustment as new model

Add `BillingAdjustment` for real credit notes.

Why:
- Credit notes are not invoices; negative invoices are poor accounting.
- Current `BillingInvoice` represents payable invoices only.
- Adjustment row tracks external credit id/status/failure/retry independently.

### 1.4 Background job for credit integration

Create local adjustment rows in the discontinuation transaction, then enqueue credit jobs.

Why:
- Existing integration pattern keeps external calls out of request/transaction.
- Discontinuation remains committed even if IN is down.
- Failed credit notes become admin-visible retry work.

### 1.5 Live Invoice Ninja spike first

Run sandbox API experiments before implementing provider tests.

Why:
- Prior tiny-IDP/DocuSeal/Invoice Ninja work showed docs/stubs hid response-shape bugs.
- Context7 did not expose concrete credit endpoint/payload details.
- The sandbox is available and safe to mutate.

---

## 2. File-by-file plan

### Agreements

- Modify `apps/agreements/models.py`
  - Add `Agreement.State.SUPERSEDED` and `Agreement.State.DISCONTINUED`.
  - Add `AgreementLifecycleEvent` model and `EventType` choices.
- Create migration `apps/agreements/migrations/0004_agreement_lifecycle.py`.
- Modify `apps/agreements/services.py`
  - Add `record_minor_amendment(agreement, actor, note)`.
  - Add `start_material_amendment(agreement, actor, note, signing_path=None)`.
  - Add `discontinue_agreement(agreement, actor, effective_date, reason, selected_invoice_ids)`.
  - Add helper `_actor_label(actor)`.
  - Add discontinuation email rendering.
- Create `templates/emails/agreements/discontinued.txt`.
- Modify `apps/agreements/presentation.py`
  - Add parent/status copy helpers for lifecycle/history.
- Modify `apps/agreements/admin.py`
  - Show lifecycle events readonly on Agreement admin.

### Members

- Modify `apps/members/models.py`
  - Add `Member.Status` choices: `active`, `discontinued`.
  - Add `status`, `discontinued_effective_date`, `discontinuation_reason`, `discontinued_at`.
- Create migration `apps/members/migrations/0009_member_lifecycle.py`.
- Modify `apps/members/admin.py`
  - Add status badge/list filter.
  - Add discontinuation action endpoint or link to member-focused discontinue view.
  - Include lifecycle fields as readonly unless set by service.

### Billing

- Modify `apps/billing/models.py`
  - Add `BillingInvoice.cancelled_at`, `BillingInvoice.cancellation_reason`.
  - Add `BillingAdjustment` model with `Kind.CREDIT_NOTE` and status fields.
- Create migration `apps/billing/migrations/0010_billing_adjustments.py`.
- Modify `apps/billing/services.py`
  - Add `class DiscontinuationInvoiceError(ValueError)`.
  - Add `class PaidInvoiceSelected(DiscontinuationInvoiceError)`.
  - Add `select_discontinuation_invoice_actions(member, invoice_ids)`.
  - Add `create_discontinuation_adjustments(member, event, invoice_ids, reason)`.
  - Update `is_invoice_due_to_send` to return `False` when invoice is locally cancelled.
  - Update `materialize_installments` / push candidates to skip cancelled invoices.
- Modify `apps/billing/messages.py`
  - Add Latvian credit/adjustment status/error copy.
- Modify `apps/billing/admin.py`
  - Register `BillingAdjustmentAdmin`.
  - Add inline/links from `BillingRecordAdmin`.
  - Add retry action for failed credit notes.

### Integrations

- Modify `apps/integrations/invoice_platform.py`
  - Add `CreditResult` and `CreditApplyResult` dataclasses.
  - Add `create_credit_note(adjustment)`.
  - Add `apply_credit_to_invoice(credit_id, invoice_id, amount)`.
- Modify `apps/integrations/invoice_ninja.py`
  - Add provider payload builders after live spike.
  - Add active/idempotent lookup for credit notes.
  - Reuse `_request`, `_unwrap`, `_require_config`, `_is_deleted`.
- Modify `apps/integrations/tasks.py`
  - Add `enqueue_create_credit_note(adjustment_id)`.
  - Add `create_credit_note_job(adjustment_id)`.
  - Add `enqueue_retry_credit_note(adjustment_id)` wrapper if needed.
  - Record audit events for credit created/failed/applied.

### Core audit

- Modify `apps/core/models.py`
  - Add `AuditEvent.Action` values:
    - `AGREEMENT_MINOR_AMENDED`
    - `AGREEMENT_MATERIAL_AMENDMENT_STARTED`
    - `AGREEMENT_SUPERSEDED`
    - `MEMBER_DISCONTINUED`
    - `BILLING_CREDIT_CREATED`
    - `BILLING_CREDIT_FAILED`
    - `BILLING_CREDIT_APPLIED`
- Create migration `apps/core/migrations/0005_p8_lifecycle_actions.py`.

### Registration admin and parent portal

- Modify `apps/registrations/admin.py`
  - Add review actions: `minor_amendment`, `material_amendment`, `discontinue_member`.
  - Map service `ValueError`s to Latvian admin messages.
- Modify `apps/registrations/admin_panels.py`
  - Include lifecycle history and proposed discontinuation invoices.
  - Include billing adjustment error messages.
- Modify `templates/registrations/admin/_agreement_module.html`
  - Add lifecycle history list.
  - Add minor/material amendment forms when state is `signed`.
  - Add discontinuation form/link when member is active and agreement signed.
- Modify `templates/admin/registrations/registrationapplication/change_form.html`
  - Include new panel context; keep Django admin shell.
- Modify `apps/registrations/views.py`
  - Annotate parent portal applications with lifecycle status/history.
- Modify `templates/registrations/parent_portal.html`
  - Render agreement/member lifecycle history.

### Documentation and validation

- Create `scripts/validate_invoice_ninja_credit.py`
  - Live sandbox validation harness.
- Create `docs/p8_invoice_ninja_credit_validation.md`
  - Record endpoint/payload/response findings and final PASS evidence.
- Update `docs/milestones.md` after implementation acceptance.
- Update `AGENTS.md` current status after implementation acceptance.

---

## 3. Test strategy

Use TDD per task. Tests go first and must fail before implementation.

### Unit/service tests

- `tests/agreements/test_lifecycle_services.py`
- `tests/members/test_member_lifecycle.py`
- `tests/billing/test_discontinuation_adjustments.py`

Cover:
- minor amendment no state change/no email/history/audit;
- material amendment signed-only guard;
- old agreement superseded/new current generated;
- discontinuation signed-only guard;
- member status and agreement status set atomically;
- paid selected invoice blocks before state change;
- local unsent invoice cancellation;
- sent unpaid invoice creates `BillingAdjustment`.

### Integration adapter/task tests

- `tests/integrations/test_invoice_credit_adapter.py`
- `tests/integrations/test_credit_note_tasks.py`

Cover:
- stub credit creation/apply;
- real provider payload shape from live spike;
- duplicate recovery/idempotent lookup;
- terminal/transient error mapping;
- task records failed adjustment and audit;
- task marks applied when API apply succeeds;
- task marks `requires_staff_apply=True` if apply unsupported/terminal after credit creation.

### Admin tests

- `tests/registrations/test_admin_agreement_lifecycle.py`
- `tests/members/test_member_discontinuation_admin.py`
- `tests/billing/test_billing_adjustment_admin.py`

Cover:
- forms visible only for staff and valid states;
- CSRF/staff permission inherited from admin views;
- Latvian errors for invalid invoice selection;
- retry action enqueues job;
- status badges/filter render.

### Parent tests

- `tests/registrations/test_parent_lifecycle_history.py`

Cover:
- portal shows current lifecycle status and history;
- discontinued child status appears;
- unrelated guardian cannot see history;
- discontinuation email contains effective date, reason, credit summary.

### Verification commands

Run after each task's focused tests. Full gate before claiming done:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

---

## 4. Acceptance criteria per unit

### Agreement lifecycle

- Minor amendment creates parent-visible history and audit; agreement remains signed.
- Material amendment requires signed agreement.
- Material amendment sets old agreement `superseded/is_current=False` and creates new current `generated` agreement.
- Discontinuation sets agreement `discontinued` and member `discontinued`.

### Billing adjustments

- Paid selected invoice blocks before state change.
- Local unsent invoice gets `cancelled_at` and is skipped by autosend/push.
- Sent unpaid/partial invoice creates adjustment row and enqueues credit job.
- Failed credit job is visible/retryable and does not revert discontinuation.

### Invoice Ninja credit integration

- Sandbox validation proves create-credit endpoint/payload.
- Sandbox validation proves auto-apply path, or documents unsupported path and verifies `requires_staff_apply=True`.
- Provider uses existing auth/JSON headers and error taxonomy.

### Admin/parent surfaces

- Staff can perform valid lifecycle actions from admin only.
- Parent portal shows current status/history.
- Discontinuation email sends every time discontinuation succeeds.

### Audit/docs

- All new lifecycle/credit actions are audited with redacted metadata.
- Validation evidence and milestone docs are updated.

---

## 5. Implementation tasks

### Task 1: Live Invoice Ninja credit-note spike

**Files:**
- Create: `scripts/validate_invoice_ninja_credit.py`
- Create: `docs/p8_invoice_ninja_credit_validation.md`
- Read only: `apps/integrations/invoice_ninja.py`

- [ ] **Step 1: Create a sandbox spike script shell**

Create `scripts/validate_invoice_ninja_credit.py` with this starting shape:

```python
"""Live sandbox probe for Invoice Ninja credit-note API.

Run manually with real sandbox env:
uv run python -m scripts.validate_invoice_ninja_credit
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

import requests

TIMEOUT = 15


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}")
    return value


def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    headers = {
        "X-Api-Token": api_key,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        **kwargs.pop("headers", {}),
    }
    response = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    print(method, url, response.status_code)
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False)[:4000])
    except ValueError:
        print(response.text[:1000])
    return response


def main() -> None:
    api_url = _env("INVOICE_NINJA_API_URL").rstrip("/")
    api_key = _env("INVOICE_NINJA_API_KEY")
    print("Probe starts. Create test client/invoice manually or extend this script during spike.")
    _request("GET", f"{api_url}/credits?per_page=1", api_key)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the spike against sandbox**

Run:

```bash
uv run python -m scripts.validate_invoice_ninja_credit
```

Expected first result: either a JSON list from `/credits` or a concrete status/error proving endpoint shape.

- [ ] **Step 3: Extend script with observed create/apply calls**

After seeing live API, extend the script with concrete payloads. Keep secrets out of output and docs. Record only endpoint paths, status codes, redacted payload shape, and response fields.

- [ ] **Step 4: Write validation evidence**

Write `docs/p8_invoice_ninja_credit_validation.md` with:

```markdown
# P8 Invoice Ninja credit-note validation

Date: 2026-06-30
Environment: Invoice Ninja sandbox

## Findings

- Credit create endpoint: record the exact path returned by the live probe, for example `/api/v1/credits` if that endpoint accepts the create payload.
- Apply credit endpoint/mechanism: record the exact path/action returned by the live probe; if the API has no safe apply endpoint, write `unsupported; app uses requires_staff_apply=True`.
- Required fields: record only field names and sample non-PII values used by the sandbox probe.
- Response id field: record the exact JSON field that contains the credit id.
- Duplicate/idempotency behaviour: record whether duplicate credit numbers are rejected and whether lookup by number/custom field works.

## Result

- Create credit note: PASS after a sandbox credit id is returned and visible in Invoice Ninja.
- Auto-apply to unpaid invoice: PASS after target invoice balance changes; if unsupported, PASS only after a `BillingAdjustment` can be marked `requires_staff_apply=True`.
- Paid invoice block: app-side design, no API call required.
```

- [ ] **Step 5: Commit only spike artifacts if requested**

Do not commit unless user explicitly asks.

### Task 2: Data models and migrations

**Files:**
- Modify: `apps/agreements/models.py`
- Modify: `apps/members/models.py`
- Modify: `apps/billing/models.py`
- Modify: `apps/core/models.py`
- Create migrations in `apps/agreements/migrations/`, `apps/members/migrations/`, `apps/billing/migrations/`, `apps/core/migrations/`
- Test: `tests/agreements/test_lifecycle_models.py`
- Test: `tests/billing/test_billing_adjustment_model.py`
- Test: `tests/members/test_member_lifecycle.py`

- [ ] **Step 1: Write failing model tests**

Add tests asserting:

```python
def test_agreement_has_superseded_and_discontinued_states():
    from apps.agreements.models import Agreement

    assert Agreement.State.SUPERSEDED == "superseded"
    assert Agreement.State.DISCONTINUED == "discontinued"


def test_member_defaults_active(make_guardian):
    from apps.members.models import Member

    member = Member.objects.create(full_name="Bērns", guardian=make_guardian())

    assert member.status == Member.Status.ACTIVE
    assert member.discontinued_effective_date is None
```

Add a billing adjustment model test:

```python
def test_billing_adjustment_defaults(billing_record):
    from apps.billing.models import BillingAdjustment

    adjustment = BillingAdjustment.objects.create(
        billing_record=billing_record,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount="10.00",
        reason="Pārtraukta dalība",
    )

    assert adjustment.external_status == "pending"
    assert adjustment.requires_staff_apply is False
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_models.py tests/members/test_member_lifecycle.py tests/billing/test_billing_adjustment_model.py -q
```

Expected: fail because fields/classes do not exist.

- [ ] **Step 3: Implement minimal models**

Add exact fields from spec. Use `TextChoices`; default member status active; default adjustment status pending.

- [ ] **Step 4: Make migrations**

Run:

```bash
uv run python manage.py makemigrations agreements members billing core
```

Expected: four migration files or fewer if Django groups no-op choice changes differently.

- [ ] **Step 5: Run model tests**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_models.py tests/members/test_member_lifecycle.py tests/billing/test_billing_adjustment_model.py -q
```

Expected: pass.

### Task 3: Agreement lifecycle services

**Files:**
- Modify: `apps/agreements/services.py`
- Create: `templates/emails/agreements/discontinued.txt`
- Test: `tests/agreements/test_lifecycle_services.py`

- [ ] **Step 1: Write failing service tests**

Cover these service signatures:

```python
record_minor_amendment(agreement, actor, note: str)
start_material_amendment(agreement, actor, note: str, signing_path: str | None = None)
discontinue_agreement(agreement, actor, effective_date, reason: str, selected_invoice_ids: list[int])
```

Write tests for no-email minor amendment, material amendment old/new rows, and signed-only guards.

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_services.py -q
```

Expected: import errors for new service functions.

- [ ] **Step 3: Implement minor/material services**

Use `transaction.atomic()` for material amendment. Save old agreement with `state="superseded"`, `is_current=False`; create new generated current agreement.

- [ ] **Step 4: Add discontinued email template**

Template content:

```django
Labdien, {{ guardian_full_name }}!

FK Cēsis dalība bērnam {{ member_full_name }} ir pārtraukta no {{ effective_date }}.

Iemesls: {{ reason }}

{% if credit_summary %}Rēķinu korekcijas: {{ credit_summary }}{% else %}Rēķinu korekcijas nav piemērotas.{% endif %}

Pieteikumu portāls: {{ portal_url }}
```

- [ ] **Step 5: Run service tests**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_services.py -q
```

Expected: pass for agreement-only cases; discontinuation billing-specific cases may still be pending in Task 4 tests.

### Task 4: Billing discontinuation selection and local cancellation

**Files:**
- Modify: `apps/billing/services.py`
- Modify: `apps/integrations/tasks.py` (skip cancelled invoices in send/push loops)
- Test: `tests/billing/test_discontinuation_adjustments.py`
- Test: existing invoice send tests under `tests/integrations/`

- [ ] **Step 1: Write failing billing tests**

Write tests:

```python
def test_paid_selected_invoice_blocks(discontinued_candidate_invoice):
    from apps.billing.models import PaymentStatus
    from apps.billing.services import PaidInvoiceSelected, create_discontinuation_adjustments

    invoice = discontinued_candidate_invoice
    invoice.payment_status = PaymentStatus.PAID
    invoice.save(update_fields=["payment_status", "updated_at"])

    with pytest.raises(PaidInvoiceSelected):
        create_discontinuation_adjustments(
            member=invoice.billing_record.member,
            event=None,
            invoice_ids=[invoice.pk],
            reason="Pārtraukta dalība",
        )


def test_unsent_local_invoice_marked_cancelled(discontinued_candidate_invoice):
    from apps.billing.services import create_discontinuation_adjustments

    invoice = discontinued_candidate_invoice
    invoice.external_invoice_id = ""
    invoice.sent_at = None
    invoice.save(update_fields=["external_invoice_id", "sent_at", "updated_at"])

    create_discontinuation_adjustments(
        member=invoice.billing_record.member,
        event=None,
        invoice_ids=[invoice.pk],
        reason="Pārtraukta dalība",
    )

    invoice.refresh_from_db()
    assert invoice.cancelled_at is not None
```

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run pytest tests/billing/test_discontinuation_adjustments.py -q
```

Expected: import/field failures.

- [ ] **Step 3: Implement selection/cancellation**

Implement `PaidInvoiceSelected`, `select_discontinuation_invoice_actions`, and `create_discontinuation_adjustments`. Query only invoices belonging to the member; reject foreign ids.

- [ ] **Step 4: Skip cancelled invoices in existing tasks**

Update:

```python
BillingInvoice.objects.filter(external_status="created", cancelled_at__isnull=True)
```

and skip cancelled rows in `push_billing_record` loop.

- [ ] **Step 5: Run billing tests**

Run:

```bash
uv run pytest tests/billing/test_discontinuation_adjustments.py tests/integrations/test_invoice_issue_send_policy.py -q
```

Expected: pass.

### Task 5: Invoice Ninja credit adapter and tasks

**Files:**
- Modify: `apps/integrations/invoice_platform.py`
- Modify: `apps/integrations/invoice_ninja.py`
- Modify: `apps/integrations/tasks.py`
- Modify: `apps/billing/messages.py`
- Test: `tests/integrations/test_invoice_credit_adapter.py`
- Test: `tests/integrations/test_credit_note_tasks.py`

- [ ] **Step 1: Write failing adapter boundary tests**

Test stub mode:

```python
def test_stub_create_credit_note_returns_deterministic_id(settings, billing_adjustment):
    from apps.integrations import invoice_platform

    settings.INVOICE_PROVIDER_MODE = "stub"

    result = invoice_platform.create_credit_note(billing_adjustment)

    assert result.external_id == f"stub-credit-{billing_adjustment.pk}"
```

- [ ] **Step 2: Write failing task tests**

Test task success and terminal failure with monkeypatch:

```python
def test_create_credit_note_job_marks_created(monkeypatch, billing_adjustment):
    from apps.integrations import tasks
    from apps.integrations.invoice_platform import CreditResult, CreditApplyResult

    monkeypatch.setattr(tasks.invoice_platform, "create_credit_note", lambda adj: CreditResult("credit-1", "created"))
    monkeypatch.setattr(tasks.invoice_platform, "apply_credit_to_invoice", lambda credit_id, invoice_id, amount: CreditApplyResult(True, "applied"))

    tasks.create_credit_note_job(billing_adjustment.pk)

    billing_adjustment.refresh_from_db()
    assert billing_adjustment.external_credit_id == "credit-1"
    assert billing_adjustment.external_status == "applied"
```

- [ ] **Step 3: Run tests and verify red**

Run:

```bash
uv run pytest tests/integrations/test_invoice_credit_adapter.py tests/integrations/test_credit_note_tasks.py -q
```

Expected: missing dataclasses/functions.

- [ ] **Step 4: Implement boundary and stub**

Add dataclasses:

```python
@dataclass(frozen=True)
class CreditResult:
    external_id: str
    external_status: str

@dataclass(frozen=True)
class CreditApplyResult:
    applied: bool
    external_status: str
```

- [ ] **Step 5: Implement real provider from spike evidence**

Use exact endpoints/payloads from `docs/p8_invoice_ninja_credit_validation.md`. Keep helper names private and small.

- [ ] **Step 6: Implement django-q job**

`create_credit_note_job`:
- loads `BillingAdjustment` with invoice/record/member/guardian;
- calls `create_credit_note`;
- stores external id/status;
- calls `apply_credit_to_invoice` when target invoice has external id;
- sets `requires_staff_apply=True` when apply returns unsupported/not applied;
- records audit on created/applied/failed;
- raises `RetryableInvoiceError` for transient errors.

- [ ] **Step 7: Run integration tests**

Run:

```bash
uv run pytest tests/integrations/test_invoice_credit_adapter.py tests/integrations/test_credit_note_tasks.py -q
```

Expected: pass.

### Task 6: Wire discontinuation service to billing adjustments and credit jobs

**Files:**
- Modify: `apps/agreements/services.py`
- Modify: `apps/billing/services.py`
- Test: `tests/agreements/test_lifecycle_services.py`
- Test: `tests/billing/test_discontinuation_adjustments.py`

- [ ] **Step 1: Write failing end-to-end service test**

```python
def test_discontinue_agreement_sets_member_and_creates_adjustment(monkeypatch, signed_agreement, sent_unpaid_invoice, staff_user):
    from apps.agreements.models import Agreement
    from apps.agreements.services import discontinue_agreement
    from apps.billing.models import BillingAdjustment

    enqueued = []
    monkeypatch.setattr("apps.integrations.tasks.enqueue_create_credit_note", lambda pk: enqueued.append(pk))

    discontinue_agreement(
        signed_agreement,
        actor=staff_user,
        effective_date=sent_unpaid_invoice.due_date,
        reason="Pārcelšanās",
        selected_invoice_ids=[sent_unpaid_invoice.pk],
    )

    signed_agreement.refresh_from_db()
    member = signed_agreement.member
    member.refresh_from_db()
    assert signed_agreement.state == Agreement.State.DISCONTINUED
    assert member.status == member.Status.DISCONTINUED
    adjustment = BillingAdjustment.objects.get(invoice=sent_unpaid_invoice)
    assert enqueued == [adjustment.pk]
```

- [ ] **Step 2: Run test and verify red**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_services.py::test_discontinue_agreement_sets_member_and_creates_adjustment -q
```

Expected: service incomplete/failing.

- [ ] **Step 3: Implement atomic discontinuation**

Inside `transaction.atomic()`:
- validate signed current agreement;
- call billing selection to block paid/invalid ids first;
- set agreement/member fields;
- create lifecycle event;
- create local cancellations/adjustments.

After commit: enqueue credit jobs using `transaction.on_commit`.

- [ ] **Step 4: Run lifecycle/billing tests**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_services.py tests/billing/test_discontinuation_adjustments.py -q
```

Expected: pass.

### Task 7: Admin UX and actions

**Files:**
- Modify: `apps/registrations/admin.py`
- Modify: `apps/registrations/admin_panels.py`
- Modify: `templates/registrations/admin/_agreement_module.html`
- Modify: `templates/admin/registrations/registrationapplication/change_form.html`
- Modify: `apps/members/admin.py`
- Modify: `apps/billing/admin.py`
- Test: `tests/registrations/test_admin_agreement_lifecycle.py`
- Test: `tests/members/test_member_discontinuation_admin.py`
- Test: `tests/billing/test_billing_adjustment_admin.py`

- [ ] **Step 1: Write failing admin tests**

Test signed agreement page includes:

```python
assert "Neliels labojums" in response.content.decode()
assert "Sagatavot aizvietojošu līgumu" in response.content.decode()
assert "Pārtraukt dalību" in response.content.decode()
```

Test POST minor amendment creates event and redirects.

Test paid invoice discontinuation POST shows Latvian warning and does not change state.

- [ ] **Step 2: Run admin tests and verify red**

Run:

```bash
uv run pytest tests/registrations/test_admin_agreement_lifecycle.py tests/members/test_member_discontinuation_admin.py tests/billing/test_billing_adjustment_admin.py -q
```

Expected: missing forms/actions.

- [ ] **Step 3: Add panel context**

In `build_review_context`, add:
- `agreement_lifecycle_events`;
- `discontinuation_invoice_candidates`;
- `billing_adjustments`;
- localized error/status messages.

- [ ] **Step 4: Add review action branches**

In `RegistrationApplicationAdmin.review_action_view`, add actions:
- `minor_amendment`;
- `material_amendment`;
- `discontinue_member`.

Map known exceptions to Latvian messages.

- [ ] **Step 5: Add templates/forms**

Add small forms in `_agreement_module.html` using existing `mms-review-actions__form` class and CSRF. Keep forms visible only when `agreement.state == "signed"` and member active.

- [ ] **Step 6: Register BillingAdjustment admin**

Add list display: member/guardian, amount, external status badge, requires staff apply, created_at. Add retry action.

- [ ] **Step 7: Run admin tests**

Run:

```bash
uv run pytest tests/registrations/test_admin_agreement_lifecycle.py tests/members/test_member_discontinuation_admin.py tests/billing/test_billing_adjustment_admin.py -q
```

Expected: pass.

### Task 8: Parent portal lifecycle history

**Files:**
- Modify: `apps/agreements/presentation.py`
- Modify: `apps/registrations/views.py`
- Modify: `templates/registrations/parent_portal.html`
- Test: `tests/registrations/test_parent_lifecycle_history.py`

- [ ] **Step 1: Write failing parent tests**

Test owner sees discontinued status/history; unrelated parent does not see it.

- [ ] **Step 2: Run tests and verify red**

Run:

```bash
uv run pytest tests/registrations/test_parent_lifecycle_history.py -q
```

Expected: missing context/template output.

- [ ] **Step 3: Add presentation helper**

Implement:

```python
def lifecycle_status_copy(agreement, member) -> str:
    if member.status == member.Status.DISCONTINUED:
        return "Dalība pārtraukta."
    if agreement is None:
        return "Līgums vēl nav sagatavots."
    if agreement.state == agreement.State.SUPERSEDED:
        return "Līgums aizvietots ar jaunu versiju."
    if agreement.state == agreement.State.DISCONTINUED:
        return "Līgums pārtraukts."
    return agreement.get_state_display()


def lifecycle_history_items(agreement) -> list[dict[str, str]]:
    if agreement is None:
        return []
    return [
        {
            "date": event.created_at.strftime("%d.%m.%Y"),
            "label": event.get_event_type_display(),
            "note": event.note,
        }
        for event in agreement.lifecycle_events.order_by("created_at")
    ]
```

Use this as starting implementation; adjust only if tests need exact wording changes. Return Latvian strings only.

- [ ] **Step 4: Annotate portal apps**

In `parent_portal`, when app has approved member/current agreement, attach:
- `app.lifecycle_status`;
- `app.lifecycle_history_items`.

Use select/prefetch where needed to avoid obvious N+1.

- [ ] **Step 5: Render template**

Add under existing `fk-app-agreement-status`; use simple `<ul>` history list.

- [ ] **Step 6: Run parent tests**

Run:

```bash
uv run pytest tests/registrations/test_parent_lifecycle_history.py -q
```

Expected: pass.

### Task 9: Audit coverage and docs

**Files:**
- Modify: `apps/core/models.py`
- Modify: `apps/agreements/services.py`
- Modify: `apps/integrations/tasks.py`
- Modify: `docs/audit-log.md`
- Test: relevant service/task tests

- [ ] **Step 1: Write audit assertions**

Add assertions to lifecycle/task tests that `AuditEvent` exists with correct action and redacted metadata.

- [ ] **Step 2: Run tests and verify red**

Run focused lifecycle/task tests.

- [ ] **Step 3: Add action choices and recording calls**

Record:
- minor amendment;
- material amendment started;
- superseded;
- member discontinued;
- credit created/failed/applied.

- [ ] **Step 4: Update audit docs**

Add P8 events to `docs/audit-log.md` event catalog.

- [ ] **Step 5: Run audit-related tests**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_services.py tests/integrations/test_credit_note_tasks.py -q
```

Expected: pass.

### Task 10: Live validation, milestone docs, full verification

**Files:**
- Modify: `docs/p8_invoice_ninja_credit_validation.md`
- Modify: `docs/milestones.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Run full focused P8 test group**

Run:

```bash
uv run pytest tests/agreements/test_lifecycle_models.py tests/agreements/test_lifecycle_services.py tests/billing/test_billing_adjustment_model.py tests/billing/test_discontinuation_adjustments.py tests/integrations/test_invoice_credit_adapter.py tests/integrations/test_credit_note_tasks.py tests/registrations/test_admin_agreement_lifecycle.py tests/registrations/test_parent_lifecycle_history.py -q
```

Expected: pass.

- [ ] **Step 2: Run live sandbox validation**

Run local app/qcluster as needed with sandbox IN env, then:

```bash
uv run python -m scripts.validate_invoice_ninja_credit
```

Expected: validation doc can truthfully say create/apply path passed or fallback path verified.

- [ ] **Step 3: Update milestone/status docs**

Update `docs/milestones.md` and `AGENTS.md` with concise delivered P8 summary and validation evidence.

- [ ] **Step 4: Run full repo gate**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: all pass.

- [ ] **Step 5: Generate critique diff URL**

Run:

```bash
bunx critique --web "P8 agreement lifecycle implementation"
```

Share URL with user.

---

## 6. Execution order and review gates

1. Task 1 is research/validation spike and must finish before real provider tests are finalized.
2. Tasks 2-4 establish data/services before admin UI.
3. Task 5 adds external credit integration after live endpoint is known.
4. Task 6 wires lifecycle to billing/credit jobs.
5. Tasks 7-8 add admin/parent surfaces.
6. Task 9 completes audit/docs.
7. Task 10 validates everything.

Implementation must follow repository TDD flow:

```text
test-engineer writes failing tests -> review tests -> software-engineer implements -> review -> docs-writer updates docs
```

No implementation begins before tests for that task are accepted.

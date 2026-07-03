# P9 Billing Plan Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make billing-plan intent explicit before agreement signing, add selected-member renewal, and keep draft reassignment safe.

**Architecture:** Persist billing intent on `Agreement`, snapshot it onto `BillingRecord`, and keep all mutations behind service helpers. Reuse existing Django admin action patterns; do not add a batch model or parent-facing UI.

**Tech Stack:** Django 5, Python 3.12, PostgreSQL/SQLite tests, pytest + pytest-django, ruff, mypy, uv.

---

## Design decisions

1. **Agreement owns first billing intent.**
   - Why: agreement signing is the trigger that creates billing draft records, so the selected `MembershipPlan` must live next to that state.
   - Data flow: `MembershipPlan(default)` → `Agreement.billing_plan/first_billing_month` → `BillingRecord.plan/first_billing_month` → `BillingInvoice.due_date`.

2. **Default plan is explicit, not inferred from latest active plan.**
   - Why: staff can stage next-season active plans; latest-active is silent and order-dependent.
   - Contract: one default plan, and it must be active.

3. **Renewal is billing-only.**
   - Why: P8 already handles material agreement replacement. P9 renewal should not create new DocuSeal work.
   - Contract: selected members only; create missing target-season drafts; skip existing target-season records.

4. **Draft reassignment is explicit and draft-only.**
   - Why: once confirmed/pushed/sent, Invoice Ninja/accounting state must not change silently.
   - Contract: block confirmed records and any record with external/sent invoices.

5. **Parent UI stays unchanged.**
   - Why: P11 owns parent invoice visibility; P9 is staff billing lifecycle hardening.

---

## File-by-file plan

### Create

- `tests/billing/test_plan_lifecycle_services.py`
  - Unit/service tests for default plan lookup, cutoff month, agreement billing draft creation, renewal, reassignment.
- `tests/agreements/test_billing_plan_assignment.py`
  - Agreement creation/signing integration tests.
- `tests/members/test_member_renewal_admin.py`
  - Member admin selected renewal action tests.
- `templates/admin/members/member/renew_billing_confirm.html`
  - Confirmation form for selected-member billing renewal.
- `templates/admin/billing/billingrecord/reassign_confirm.html`
  - Confirmation form for draft billing-record reassignment.

### Modify

- `apps/billing/models.py`
  - `MembershipPlan.is_default`, `MembershipPlan.billing_start_cutoff_day`.
  - DB constraints for single default and default-is-active.
  - `MembershipPlan.clean()` with Latvian validation.
  - `BillingRecord.first_billing_month`.
- `apps/billing/services.py`
  - `get_default_billing_plan()`.
  - `derive_first_billing_month()`.
  - `parse_first_billing_month()` for `YYYY-MM` validation and schedule overrides.
  - `derive_installment_schedule(..., first_billing_month="")`.
  - `create_draft_billing_for_member()` uses `agreement.billing_plan`.
  - `renew_member_billing()`.
  - `reassign_draft_billing_record()`.
  - `materialize_installments()` passes record month override.
- `apps/agreements/models.py`
  - `Agreement.billing_plan` FK.
  - `Agreement.first_billing_month` char field.
- `apps/agreements/services.py`
  - `create_agreement_for_member()` preselects default plan and month.
  - `mark_agreement_signed()` blocks missing billing plan before state change/signal.
  - `start_material_amendment()` copies billing setup to replacement agreement.
  - `regenerate_agreement()` path inherits the updated create helper.
  - `set_billing_setup()` helper for admin module.
- `apps/registrations/admin_panels.py`
  - Add `membership_plans` and billing setup context for `_agreement_module.html`.
- `templates/registrations/admin/_agreement_module.html`
  - Add billing setup form and missing-plan warning.
- `apps/registrations/admin.py`
  - Add `set_billing_setup` POST action branch.
  - Catch missing-plan signing error with Latvian message.
- `apps/members/admin.py`
  - Add `renew_billing` action + confirmation flow on `MemberAdmin`.
- `apps/billing/admin.py`
  - Add draft-only reassignment admin action/view on `BillingRecordAdmin`.
  - Include `first_billing_month` in readonly fields/list detail as useful.
- `apps/core/models.py`
  - Add audit action choices: `BILLING_PLAN_ASSIGNED`, `BILLING_RECORD_RENEWED`, `BILLING_RECORD_REASSIGNED`.
- `docs/milestones.md`, `AGENTS.md`
  - Update P9 status after implementation only.

---

## Test strategy

Framework: pytest + pytest-django. Use existing fixtures from `tests/conftest.py`, `tests/members/conftest.py`, and current admin tests.

Test:

- model validation and DB constraints;
- pure month derivation;
- agreement billing setup preselection;
- signing block before mutation;
- billing draft creation uses selected agreement plan/month;
- materialized invoice dates respect month override + due day + skip months;
- selected-member renewal creates/skips safely;
- draft reassignment works and blocks unsafe states;
- audit events emitted only on real mutations;
- parent portal unchanged smoke assertion.

Do not test:

- Invoice Ninja provider payloads again unless date materialization changes expected payload tests.
- Parent invoice UI; belongs to P11.
- DocuSeal API; P9 only blocks/signals around existing agreement services.

---

## Acceptance criteria per unit

1. `MembershipPlan`
   - One default plan max.
   - Default plan must be active.
   - Cutoff day is 1–31.
2. `Agreement`
   - New agreements prefill default billing plan/month when available.
   - Missing plan blocks signed transition.
3. Billing services
   - No latest-active fallback for new agreement draft creation.
   - Draft records snapshot plan/month and materialize invoice dates from the snapshot.
4. Renewal
   - Selected members only.
   - Existing target-season records skipped.
   - Discontinued members skipped.
5. Reassignment
   - Draft-only.
   - Blocks external/sent invoices.
   - Regenerates local invoices only when safe.
6. Audit
   - Successful plan assignment, renewal creation, reassignment emit audit events.
   - Skips/no-ops do not emit audit rows.
7. Docs
   - Milestone and AGENTS status reflect P9 delivered only after verification.

---

## Task 1: Billing plan model and pure helpers

**Files:**
- Modify: `apps/billing/models.py`
- Modify: `apps/billing/services.py`
- Test: `tests/billing/test_plan_lifecycle_services.py`

- [ ] **Step 1: Write failing tests for default plan validation and cutoff month**

Add `tests/billing/test_plan_lifecycle_services.py`:

```python
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.billing.models import MembershipPlan
from apps.billing.services import derive_first_billing_month, get_default_billing_plan

pytestmark = pytest.mark.django_db


def make_plan(**kwargs):
    defaults = {
        "name": "Biedra maksa 2026/2027",
        "season": "2026/2027",
        "annual_amount": Decimal("300.00"),
        "sibling_discount_percent": Decimal("50.00"),
        "installment_count": 10,
        "first_installment_month": 9,
        "payment_due_day": 20,
        "skip_months": "7,12",
        "is_active": True,
    }
    defaults.update(kwargs)
    return MembershipPlan.objects.create(**defaults)


def test_default_plan_must_be_active():
    plan = MembershipPlan(
        name="Inactive default",
        season="2026/2027",
        is_active=False,
        is_default=True,
    )

    with pytest.raises(ValidationError, match="Noklusējuma plānam jābūt aktīvam"):
        plan.full_clean()


def test_only_one_default_plan_allowed():
    make_plan(name="Default A", is_default=True)

    with pytest.raises(IntegrityError):
        make_plan(name="Default B", season="2027/2028", is_default=True)


def test_get_default_billing_plan_returns_active_default():
    make_plan(name="Other", season="2025/2026", is_active=True, is_default=False)
    default = make_plan(name="Default", season="2026/2027", is_active=True, is_default=True)

    assert get_default_billing_plan() == default


def test_derive_first_billing_month_uses_cutoff_current_month():
    plan = make_plan(billing_start_cutoff_day=15)

    result = derive_first_billing_month(plan, today=datetime.date(2026, 7, 15))

    assert result == "2026-07"


def test_derive_first_billing_month_uses_cutoff_next_month():
    plan = make_plan(billing_start_cutoff_day=15)

    result = derive_first_billing_month(plan, today=datetime.date(2026, 7, 16))

    assert result == "2026-08"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/billing/test_plan_lifecycle_services.py -q
```

Expected: failures for missing `is_default`, `billing_start_cutoff_day`, and helper imports.

- [ ] **Step 3: Implement minimal model fields and helpers**

In `apps/billing/models.py`, update imports and `MembershipPlan`:

```python
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
```

Add fields after `is_active`:

```python
    is_default = models.BooleanField(default=False)
    billing_start_cutoff_day = models.PositiveSmallIntegerField(
        default=15,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Diena, līdz kurai pirmais rēķina mēnesis ir tekošais mēnesis.",
    )
```

Add constraints to `MembershipPlan.Meta`:

```python
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="one_default_membership_plan",
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(is_active=True),
                name="default_membership_plan_must_be_active",
            ),
        ]
```

Add `clean()`:

```python
    def clean(self):
        super().clean()
        if self.is_default and not self.is_active:
            raise ValidationError({"is_default": "Noklusējuma plānam jābūt aktīvam."})
        if self.is_default:
            qs = MembershipPlan.objects.filter(is_default=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({"is_default": "Noklusējuma plāns jau ir izvēlēts."})
```

In `apps/billing/services.py`, add:

```python
def get_default_billing_plan():
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.filter(is_default=True, is_active=True).first()


def derive_first_billing_month(plan, today: datetime.date | None = None) -> str:
    today = today or timezone.localdate()
    year = today.year
    month = today.month
    if today.day > int(plan.billing_start_cutoff_day):
        month += 1
        if month > 12:
            month = 1
            year += 1
    return f"{year:04d}-{month:02d}"
```

- [ ] **Step 4: Create migrations**

Run:

```bash
uv run python manage.py makemigrations billing
```

Expected: migration adds `MembershipPlan.is_default`, `billing_start_cutoff_day`, and constraints.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/billing/test_plan_lifecycle_services.py -q
```

Expected: pass.

---

## Task 2: Agreement billing intent fields and signing guard

**Files:**
- Modify: `apps/agreements/models.py`
- Modify: `apps/agreements/services.py`
- Modify: `apps/billing/services.py`
- Test: `tests/agreements/test_billing_plan_assignment.py`
- Test: `tests/billing/test_plan_lifecycle_services.py`

- [ ] **Step 1: Write failing agreement tests**

Create `tests/agreements/test_billing_plan_assignment.py`:

```python
from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member, mark_agreement_signed
from apps.billing.models import BillingRecord, MembershipPlan

pytestmark = pytest.mark.django_db


def make_plan(**kwargs):
    defaults = {
        "name": "Biedra maksa 2026/2027",
        "season": "2026/2027",
        "annual_amount": Decimal("300.00"),
        "sibling_discount_percent": Decimal("50.00"),
        "installment_count": 10,
        "first_installment_month": 9,
        "payment_due_day": 20,
        "skip_months": "7,12",
        "is_active": True,
        "is_default": True,
        "billing_start_cutoff_day": 15,
    }
    defaults.update(kwargs)
    return MembershipPlan.objects.create(**defaults)


def test_create_agreement_preselects_default_billing_plan(member):
    plan = make_plan()

    with patch("apps.billing.services.timezone.localdate", return_value=datetime.date(2026, 7, 10)):
        agreement = create_agreement_for_member(member, signing_path=Agreement.SigningPath.PAPER)

    assert agreement.billing_plan == plan
    assert agreement.first_billing_month == "2026-07"


def test_create_agreement_without_default_leaves_billing_setup_empty(member):
    agreement = create_agreement_for_member(member, signing_path=Agreement.SigningPath.PAPER)

    assert agreement.billing_plan is None
    assert agreement.first_billing_month == ""


def test_signing_without_billing_plan_is_blocked(member):
    agreement = Agreement.objects.create(
        member=member,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
    )

    with pytest.raises(ValueError, match="billing plan required"):
        mark_agreement_signed(agreement, actor=None)

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.GENERATED
    assert not BillingRecord.objects.filter(member=member).exists()
```

Append to `tests/billing/test_plan_lifecycle_services.py`:

```python
from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord
from apps.billing.services import create_draft_billing_for_member


def test_create_draft_billing_uses_agreement_plan_and_month(member):
    selected = make_plan(name="Selected", season="2026/2027", is_default=True)
    other = make_plan(name="Other", season="2027/2028", is_default=False)
    agreement = Agreement.objects.create(
        member=member,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        billing_plan=selected,
        first_billing_month="2026-08",
    )

    record = create_draft_billing_for_member(member, agreement)

    assert record is not None
    assert record.plan == selected
    assert record.plan != other
    assert record.season == "2026/2027"
    assert record.first_billing_month == "2026-08"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/agreements/test_billing_plan_assignment.py tests/billing/test_plan_lifecycle_services.py -q
```

Expected: fail on missing agreement fields and old active-plan lookup.

- [ ] **Step 3: Add Agreement fields**

In `apps/agreements/models.py`, add after `signing_path`:

```python
    billing_plan = models.ForeignKey(
        "billing.MembershipPlan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agreements",
    )
    first_billing_month = models.CharField(max_length=7, blank=True, default="")
```

- [ ] **Step 4: Update agreement services**

In `apps/agreements/services.py`, import lazily inside `create_agreement_for_member`:

```python
    from apps.billing.services import derive_first_billing_month, get_default_billing_plan

    billing_plan = get_default_billing_plan()
    first_billing_month = (
        derive_first_billing_month(billing_plan) if billing_plan is not None else ""
    )
```

Pass these fields into both fresh `Agreement.objects.create(...)` calls in `create_agreement_for_member()` and `start_material_amendment()`:

```python
            billing_plan=billing_plan,
            first_billing_month=first_billing_month,
```

For `start_material_amendment()`, copy the old agreement values instead of recalculating:

```python
            billing_plan=agreement.billing_plan,
            first_billing_month=agreement.first_billing_month,
```

At the start of `mark_agreement_signed()` after state validation and before mutation:

```python
    if agreement.billing_plan_id is None:
        raise ValueError("billing plan required")
```

- [ ] **Step 5: Update billing draft creation**

In `apps/billing/models.py`, add to `BillingRecord` after `season`:

```python
    first_billing_month = models.CharField(max_length=7, blank=True, default="")
```

In `apps/billing/services.py`, update `create_draft_billing_for_member()`:

```python
    from apps.billing.models import BillingRecord

    plan = getattr(agreement, "billing_plan", None)
    if plan is None:
        raise ValueError("billing plan required")
```

Remove the old active-plan query and missing-active-plan warning from this path.

Add default field in `get_or_create`:

```python
            "first_billing_month": agreement.first_billing_month,
```

- [ ] **Step 6: Create migrations**

Run:

```bash
uv run python manage.py makemigrations agreements billing
```

Expected: migrations add `Agreement.billing_plan`, `Agreement.first_billing_month`, and `BillingRecord.first_billing_month`.

- [ ] **Step 7: Run tests**

Run:

```bash
uv run pytest tests/agreements/test_billing_plan_assignment.py tests/billing/test_plan_lifecycle_services.py -q
```

Expected: pass.

---

## Task 3: Month override materializes invoice dates

**Files:**
- Modify: `apps/billing/services.py`
- Test: `tests/billing/test_plan_lifecycle_services.py`
- Existing tests to check: `tests/billing/test_discount_engine.py`, `tests/billing/test_push_billing_record.py`

- [ ] **Step 1: Write failing tests for first billing month schedule**

Append to `tests/billing/test_plan_lifecycle_services.py`:

```python
from apps.billing.services import materialize_installments


def test_materialize_installments_uses_record_first_billing_month(member):
    plan = make_plan(
        first_installment_month=1,
        payment_due_day=20,
        installment_count=3,
        skip_months="7,12",
    )
    agreement = Agreement.objects.create(
        member=member,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        billing_plan=plan,
        first_billing_month="2026-08",
    )
    record = BillingRecord.objects.create(
        member=member,
        plan=plan,
        agreement=agreement,
        season=plan.season,
        first_billing_month="2026-08",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.INSTALLMENTS,
    )

    invoices = materialize_installments(record)

    assert [invoice.due_date.isoformat() for invoice in invoices] == [
        "2026-08-20",
        "2026-09-20",
        "2026-10-20",
    ]


def test_materialize_installments_falls_back_to_plan_month_when_record_month_blank(member):
    plan = make_plan(first_installment_month=9, payment_due_day=20, installment_count=1)
    agreement = Agreement.objects.create(
        member=member,
        signing_path=Agreement.SigningPath.PAPER,
        generated_at=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
        billing_plan=plan,
    )
    record = BillingRecord.objects.create(
        member=member,
        plan=plan,
        agreement=agreement,
        season=plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.INSTALLMENTS,
    )

    invoices = materialize_installments(record)

    assert [invoice.due_date.isoformat() for invoice in invoices] == ["2026-09-20"]
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/billing/test_plan_lifecycle_services.py -q
```

Expected: first test fails because schedule ignores `record.first_billing_month`.

- [ ] **Step 3: Implement month parsing and schedule override**

In `apps/billing/services.py`, add:

```python
def parse_first_billing_month(value: str) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        year_str, month_str = value.split("-", 1)
        year = int(year_str)
        month = int(month_str)
    except ValueError:
        raise ValueError("first billing month must use YYYY-MM") from None
    if len(year_str) != 4 or len(month_str) != 2 or not 1 <= month <= 12:
        raise ValueError("first billing month must use YYYY-MM")
    return year, month
```

Change `derive_installment_schedule` signature:

```python
def derive_installment_schedule(
    plan,
    total: Decimal,
    *,
    first_billing_month: str = "",
) -> list[tuple[datetime.date, Decimal]]:
```

Replace start year/month lines with:

```python
    parsed_month = parse_first_billing_month(first_billing_month)
    if parsed_month is None:
        start_year = int(plan.season.split("/")[0])
        month = int(plan.first_installment_month)
        year = start_year
    else:
        year, month = parsed_month
```

Update `materialize_installments()`:

```python
    schedule = derive_installment_schedule(
        record.plan,
        record.final_amount,
        first_billing_month=record.first_billing_month,
    )
```

- [ ] **Step 4: Run focused billing tests**

Run:

```bash
uv run pytest tests/billing/test_plan_lifecycle_services.py tests/billing/test_discount_engine.py -q
```

Expected: pass.

---

## Task 4: Agreement admin billing setup UI

**Files:**
- Modify: `apps/agreements/services.py`
- Modify: `apps/registrations/admin_panels.py`
- Modify: `templates/registrations/admin/_agreement_module.html`
- Modify: `apps/registrations/admin.py`
- Test: `tests/registrations/test_admin_agreement_lifecycle.py` or new `tests/registrations/test_admin_agreement_billing_setup.py`

- [ ] **Step 1: Write failing admin tests**

Create `tests/registrations/test_admin_agreement_billing_setup.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.billing.models import MembershipPlan
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def make_plan(**kwargs):
    defaults = {
        "name": "Biedra maksa 2026/2027",
        "season": "2026/2027",
        "annual_amount": Decimal("300.00"),
        "installment_count": 10,
        "first_installment_month": 9,
        "payment_due_day": 20,
        "is_active": True,
        "is_default": False,
        "billing_start_cutoff_day": 15,
    }
    defaults.update(kwargs)
    return MembershipPlan.objects.create(**defaults)


def review_action_url(application):
    return reverse("admin:registrations_registrationapplication_review_action", args=[application.pk])


def test_agreement_module_shows_billing_plan_picker(staff_client, approved_application):
    plan = make_plan(name="Plan A")
    agreement = Agreement.objects.get(member=approved_application.approved_member)
    agreement.billing_plan = plan
    agreement.first_billing_month = "2026-09"
    agreement.save(update_fields=["billing_plan", "first_billing_month"])
    url = reverse("admin:registrations_registrationapplication_change", args=[approved_application.pk])

    response = staff_client.get(url)

    assert response.status_code == 200
    assert "Norēķinu plāns" in response.content.decode()
    assert "2026-09" in response.content.decode()


def test_staff_can_update_agreement_billing_setup(staff_client, approved_application):
    plan = make_plan(name="Plan B", season="2027/2028")
    agreement = Agreement.objects.get(member=approved_application.approved_member)

    response = staff_client.post(
        review_action_url(approved_application),
        {"action": "set_billing_setup", "billing_plan": str(plan.pk), "first_billing_month": "2027-09"},
    )

    assert response.status_code == 302
    agreement.refresh_from_db()
    assert agreement.billing_plan == plan
    assert agreement.first_billing_month == "2027-09"
    assert AuditEvent.objects.filter(action=AuditEvent.Action.BILLING_PLAN_ASSIGNED).exists()


def test_signing_missing_billing_plan_renders_admin_error(staff_client, approved_application):
    agreement = Agreement.objects.get(member=approved_application.approved_member)
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    response = staff_client.post(review_action_url(approved_application), {"action": "mark_agreement_signed"})

    assert response.status_code == 302
    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.GENERATED
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/registrations/test_admin_agreement_billing_setup.py -q
```

Expected: fail on missing action/context/template output.

- [ ] **Step 3: Add billing setup service**

In `apps/agreements/services.py`, add:

```python
def set_billing_setup(
    agreement: Agreement,
    billing_plan,
    first_billing_month: str,
    actor,
) -> Agreement:
    if agreement.state == Agreement.State.SIGNED:
        raise ValueError("cannot change billing setup after signing")
    if first_billing_month:
        from apps.billing.services import parse_first_billing_month

        parse_first_billing_month(first_billing_month)
    old_plan_id = agreement.billing_plan_id
    old_month = agreement.first_billing_month
    if old_plan_id == billing_plan.pk and old_month == first_billing_month:
        return agreement
    agreement.billing_plan = billing_plan
    agreement.first_billing_month = first_billing_month
    agreement.save(update_fields=["billing_plan", "first_billing_month", "updated_at"])
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_PLAN_ASSIGNED),
        actor=actor,
        target=agreement,
        metadata={
            "old_plan_id": old_plan_id,
            "new_plan_id": billing_plan.pk,
            "old_first_billing_month": old_month,
            "new_first_billing_month": first_billing_month,
        },
    )
    return agreement
```

- [ ] **Step 4: Add admin panel context**

In `apps/registrations/admin_panels.py`, import `MembershipPlan` and add to return dict:

```python
        "membership_plans": list(MembershipPlan.objects.filter(is_active=True).order_by("season", "name")),
```

- [ ] **Step 5: Add template block**

In `templates/registrations/admin/_agreement_module.html`, after state paragraph add:

```django
  <h3>Norēķinu plāns</h3>
  {% if not agreement.billing_plan %}
  <p class="errornote">Pirms parakstīšanas jāizvēlas norēķinu plāns.</p>
  {% endif %}
  <form method="post" action="{{ review_action_url }}" class="mms-review-actions__form">
    {% csrf_token %}
    <div class="form-row">
      <label for="billing_plan">Norēķinu plāns:</label>
      <select name="billing_plan" id="billing_plan" required>
        <option value="">— Izvēlieties —</option>
        {% for plan in membership_plans %}
        <option value="{{ plan.pk }}"{% if agreement.billing_plan_id == plan.pk %} selected{% endif %}>{{ plan.name }} — {{ plan.season }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="form-row">
      <label for="first_billing_month">Pirmais rēķina mēnesis:</label>
      <input type="month" name="first_billing_month" id="first_billing_month" value="{{ agreement.first_billing_month }}">
    </div>
    <button type="submit" name="action" value="set_billing_setup" class="default">Saglabāt norēķinu plānu</button>
  </form>
```

- [ ] **Step 6: Wire admin action**

In `apps/registrations/admin.py`, in review action dispatcher, add branch:

```python
        if action == "set_billing_setup":
            from apps.agreements.services import set_billing_setup
            from apps.billing.models import MembershipPlan

            plan = get_object_or_404(MembershipPlan, pk=request.POST.get("billing_plan"), is_active=True)
            try:
                set_billing_setup(agreement, plan, request.POST.get("first_billing_month", ""), request.user)
                self.message_user(request, "Norēķinu plāns saglabāts.")
            except ValueError:
                self.message_user(request, "Pārbaudiet norēķinu plāna mēnesi.", level=messages.ERROR)
            return self._after_review_redirect(request, application)
```

In existing `mark_agreement_signed` branch, catch `ValueError("billing plan required")` and show:

```python
"Pirms parakstīšanas jāizvēlas norēķinu plāns."
```

- [ ] **Step 7: Add audit enum migration**

In `apps/core/models.py`, add choices:

```python
        BILLING_PLAN_ASSIGNED = "billing_plan_assigned", "Billing plan assigned"
        BILLING_RECORD_RENEWED = "billing_record_renewed", "Billing record renewed"
        BILLING_RECORD_REASSIGNED = "billing_record_reassigned", "Billing record reassigned"
```

Run:

```bash
uv run python manage.py makemigrations core
```

Expected: choices-only migration.

- [ ] **Step 8: Run admin tests**

Run:

```bash
uv run pytest tests/registrations/test_admin_agreement_billing_setup.py -q
```

Expected: pass.

---

## Task 5: Selected-member renewal admin action

**Files:**
- Modify: `apps/billing/services.py`
- Modify: `apps/members/admin.py`
- Create: `templates/admin/members/member/renew_billing_confirm.html`
- Test: `tests/members/test_member_renewal_admin.py`

- [ ] **Step 1: Write failing renewal service/admin tests**

Create `tests/members/test_member_renewal_admin.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord, MembershipPlan
from apps.core.models import AuditEvent
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def make_plan(**kwargs):
    defaults = {
        "name": "Biedra maksa 2027/2028",
        "season": "2027/2028",
        "annual_amount": Decimal("300.00"),
        "installment_count": 10,
        "first_installment_month": 9,
        "payment_due_day": 20,
        "is_active": True,
        "billing_start_cutoff_day": 15,
    }
    defaults.update(kwargs)
    return MembershipPlan.objects.create(**defaults)


def test_member_admin_renewal_confirmation_page(staff_client, member):
    make_plan()
    url = reverse("admin:members_member_changelist")

    response = staff_client.post(url, {"action": "renew_billing", "_selected_action": [str(member.pk)]})

    assert response.status_code == 200
    assert "Atjaunot norēķinus" in response.content.decode()


def test_member_admin_renewal_creates_missing_draft(staff_client, member):
    plan = make_plan()
    Agreement.objects.create(
        member=member,
        signing_path=Agreement.SigningPath.PAPER,
        state=Agreement.State.SIGNED,
        generated_at="2026-07-01T00:00:00Z",
        signed_at="2026-07-01T00:00:00Z",
        billing_plan=plan,
        first_billing_month="2027-09",
    )
    url = reverse("admin:members_member_changelist")

    response = staff_client.post(
        url,
        {
            "action": "renew_billing",
            "apply": "1",
            "billing_plan": str(plan.pk),
            "first_billing_month": "2027-09",
            "_selected_action": [str(member.pk)],
        },
    )

    assert response.status_code == 302
    record = BillingRecord.objects.get(member=member, season="2027/2028")
    assert record.plan == plan
    assert record.first_billing_month == "2027-09"
    assert record.status == BillingRecord.Status.DRAFT
    assert AuditEvent.objects.filter(action=AuditEvent.Action.BILLING_RECORD_RENEWED, target_id=str(record.pk)).exists()


def test_member_admin_renewal_skips_existing_record(staff_client, member):
    plan = make_plan()
    BillingRecord.objects.create(
        member=member,
        plan=plan,
        season=plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    url = reverse("admin:members_member_changelist")

    response = staff_client.post(
        url,
        {
            "action": "renew_billing",
            "apply": "1",
            "billing_plan": str(plan.pk),
            "_selected_action": [str(member.pk)],
        },
    )

    assert response.status_code == 302
    assert BillingRecord.objects.filter(member=member, season=plan.season).count() == 1
    assert not AuditEvent.objects.filter(action=AuditEvent.Action.BILLING_RECORD_RENEWED).exists()


def test_member_admin_renewal_skips_discontinued_member(staff_client, member):
    plan = make_plan()
    member.status = Member.Status.DISCONTINUED
    member.save(update_fields=["status", "updated_at"])
    url = reverse("admin:members_member_changelist")

    staff_client.post(
        url,
        {
            "action": "renew_billing",
            "apply": "1",
            "billing_plan": str(plan.pk),
            "_selected_action": [str(member.pk)],
        },
    )

    assert not BillingRecord.objects.filter(member=member, season=plan.season).exists()
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/members/test_member_renewal_admin.py -q
```

Expected: fail on missing action/service/template.

- [ ] **Step 3: Implement renewal service**

In `apps/billing/services.py`, add:

```python
def renew_member_billing(member, plan, *, first_billing_month: str = "", actor=None):
    from apps.agreements.services import get_current_agreement
    from apps.billing.models import BillingRecord
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent

    if first_billing_month:
        parse_first_billing_month(first_billing_month)
    if BillingRecord.objects.filter(member=member, season=plan.season).exists():
        return None
    agreement = get_current_agreement(member)
    amounts = compute_billing_amounts(member, plan)
    application = getattr(member, "source_application", None)
    payment_mode = BillingRecord.PaymentMode.INSTALLMENTS
    opt_out = False
    if application is not None:
        if application.preferred_payment_mode:
            payment_mode = application.preferred_payment_mode
        opt_out = application.support_club_instead_of_multi_child_discount is True
    record = BillingRecord.objects.create(
        member=member,
        plan=plan,
        agreement=agreement,
        season=plan.season,
        first_billing_month=first_billing_month,
        base_amount=amounts.base_amount,
        is_full_price=amounts.is_full_price,
        sibling_discount_percent_applied=amounts.discount_percent_applied,
        discount_amount=amounts.discount_amount,
        final_amount=amounts.final_amount,
        payment_mode=payment_mode,
        full_price_opt_out=opt_out,
    )
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_RENEWED),
        actor=actor,
        target=record,
        metadata={"plan_id": plan.pk, "season": plan.season, "first_billing_month": first_billing_month},
    )
    return record
```

- [ ] **Step 4: Implement MemberAdmin action**

In `apps/members/admin.py`, import `MembershipPlan` and `renew_member_billing` lazily or at top. Add action to `MemberAdmin.actions`:

```python
    actions = ["export_csv", "export_csv_with_sensitive", "renew_billing"]
```

Add method:

```python
    @admin.action(description="Atjaunot norēķinus atlasītajiem biedriem")
    def renew_billing(self, request, queryset):
        from apps.billing.models import BillingRecord, MembershipPlan
        from apps.billing.services import parse_first_billing_month, renew_member_billing

        members = list(queryset.select_related("guardian", "source_application"))
        if request.POST.get("apply") == "1":
            plan = get_object_or_404(MembershipPlan, pk=request.POST.get("billing_plan"), is_active=True)
            first_billing_month = request.POST.get("first_billing_month", "")
            try:
                if first_billing_month:
                    parse_first_billing_month(first_billing_month)
            except ValueError:
                self.message_user(request, "Pirmajam mēnesim jābūt formātā GGGG-MM.", level=messages.ERROR)
                return None
            created = skipped_existing = skipped_discontinued = 0
            for member in members:
                if member.status == Member.Status.DISCONTINUED:
                    skipped_discontinued += 1
                    continue
                if BillingRecord.objects.filter(member=member, season=plan.season).exists():
                    skipped_existing += 1
                    continue
                if renew_member_billing(member, plan, first_billing_month=first_billing_month, actor=request.user) is not None:
                    created += 1
            self.message_user(
                request,
                f"Izveidoti {created} norēķinu ieraksti. Esoši: {skipped_existing}. Pārtraukti: {skipped_discontinued}.",
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": "Atjaunot norēķinus",
            "members": members,
            "plans": MembershipPlan.objects.filter(is_active=True).order_by("season", "name"),
            "opts": self.model._meta,
            "action_name": "renew_billing",
        }
        return TemplateResponse(request, "admin/members/member/renew_billing_confirm.html", context)
```

- [ ] **Step 5: Add confirmation template**

Create `templates/admin/members/member/renew_billing_confirm.html`:

```django
{% extends "admin/base_site.html" %}

{% block content %}
<h1>{{ title }}</h1>
<form method="post">
  {% csrf_token %}
  <input type="hidden" name="action" value="{{ action_name }}">
  <input type="hidden" name="apply" value="1">
  {% for member in members %}
  <input type="hidden" name="_selected_action" value="{{ member.pk }}">
  {% endfor %}

  <div class="form-row">
    <label for="billing_plan">Norēķinu plāns:</label>
    <select id="billing_plan" name="billing_plan" required>
      {% for plan in plans %}
      <option value="{{ plan.pk }}">{{ plan.name }} — {{ plan.season }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="form-row">
    <label for="first_billing_month">Pirmais rēķina mēnesis:</label>
    <input type="month" id="first_billing_month" name="first_billing_month">
  </div>

  <p>Atlasīti biedri: {{ members|length }}</p>
  <button type="submit" class="default">Izveidot norēķinu melnrakstus</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/members/test_member_renewal_admin.py -q
```

Expected: pass.

---

## Task 6: Draft billing-record reassignment/regeneration

**Files:**
- Modify: `apps/billing/services.py`
- Modify: `apps/billing/admin.py`
- Create: `templates/admin/billing/billingrecord/reassign_confirm.html`
- Test: `tests/billing/test_billing_record_reassignment.py`

- [ ] **Step 1: Write failing reassignment tests**

Create `tests/billing/test_billing_record_reassignment.py`:

```python
from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.billing.models import BillingInvoice, BillingRecord, MembershipPlan
from apps.billing.services import reassign_draft_billing_record
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def make_plan(**kwargs):
    defaults = {
        "name": "Biedra maksa 2027/2028",
        "season": "2027/2028",
        "annual_amount": Decimal("400.00"),
        "installment_count": 10,
        "first_installment_month": 9,
        "payment_due_day": 20,
        "is_active": True,
        "billing_start_cutoff_day": 15,
    }
    defaults.update(kwargs)
    return MembershipPlan.objects.create(**defaults)


def make_record(member, plan, **kwargs):
    defaults = {
        "member": member,
        "plan": plan,
        "season": plan.season,
        "base_amount": Decimal("300.00"),
        "final_amount": Decimal("300.00"),
        "status": BillingRecord.Status.DRAFT,
    }
    defaults.update(kwargs)
    return BillingRecord.objects.create(**defaults)


def test_reassign_draft_billing_record_updates_plan_month_and_amount(member):
    old_plan = make_plan(name="Old", season="2026/2027", annual_amount=Decimal("300.00"))
    new_plan = make_plan(name="New", season="2027/2028", annual_amount=Decimal("400.00"))
    record = make_record(member, old_plan)

    reassign_draft_billing_record(record, new_plan, first_billing_month="2027-09", actor=None)

    record.refresh_from_db()
    assert record.plan == new_plan
    assert record.season == "2027/2028"
    assert record.first_billing_month == "2027-09"
    assert record.base_amount == Decimal("400.00")
    assert record.final_amount == Decimal("400.00")
    assert AuditEvent.objects.filter(action=AuditEvent.Action.BILLING_RECORD_REASSIGNED, target_id=str(record.pk)).exists()


def test_reassign_blocks_confirmed_record(member):
    old_plan = make_plan(name="Old", season="2026/2027")
    new_plan = make_plan(name="New", season="2027/2028")
    record = make_record(member, old_plan, status=BillingRecord.Status.CONFIRMED)

    with pytest.raises(ValueError, match="only draft billing records can be reassigned"):
        reassign_draft_billing_record(record, new_plan, first_billing_month="2027-09", actor=None)


def test_reassign_blocks_external_invoice(member):
    old_plan = make_plan(name="Old", season="2026/2027")
    new_plan = make_plan(name="New", season="2027/2028")
    record = make_record(member, old_plan)
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date="2026-09-20",
        amount=Decimal("300.00"),
        external_invoice_id="123",
    )

    with pytest.raises(ValueError, match="cannot reassign pushed billing record"):
        reassign_draft_billing_record(record, new_plan, first_billing_month="2027-09", actor=None)


def test_admin_reassign_confirmation_page(staff_client, member):
    old_plan = make_plan(name="Old", season="2026/2027")
    make_plan(name="New", season="2027/2028")
    record = make_record(member, old_plan)
    url = reverse("admin:billing_billingrecord_reassign", args=[record.pk])

    response = staff_client.get(url)

    assert response.status_code == 200
    assert "Pārpiešķirt norēķinu ierakstu" in response.content.decode()


def test_admin_reassign_posts_to_service(staff_client, member):
    old_plan = make_plan(name="Old", season="2026/2027")
    new_plan = make_plan(name="New", season="2027/2028")
    record = make_record(member, old_plan)
    url = reverse("admin:billing_billingrecord_reassign", args=[record.pk])

    response = staff_client.post(url, {"billing_plan": str(new_plan.pk), "first_billing_month": "2027-09"})

    assert response.status_code == 302
    record.refresh_from_db()
    assert record.plan == new_plan
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/billing/test_billing_record_reassignment.py -q
```

Expected: fail on missing service/admin URL.

- [ ] **Step 3: Implement reassignment service**

In `apps/billing/services.py`, add:

```python
def reassign_draft_billing_record(record, plan, *, first_billing_month: str = "", actor=None) -> None:
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent

    if record.status != BillingRecord.Status.DRAFT:
        raise ValueError("only draft billing records can be reassigned")
    if first_billing_month:
        parse_first_billing_month(first_billing_month)
    unsafe_invoice_exists = record.invoices.filter(external_invoice_id__gt="").exists() or record.invoices.filter(sent_at__isnull=False).exists()
    if unsafe_invoice_exists:
        raise ValueError("cannot reassign pushed billing record")
    old_plan_id = record.plan_id
    old_month = record.first_billing_month
    record.invoices.all().delete()
    amounts = compute_billing_amounts(record.member, plan)
    record.plan = plan
    record.season = plan.season
    record.first_billing_month = first_billing_month
    record.base_amount = amounts.base_amount
    record.is_full_price = amounts.is_full_price
    record.sibling_discount_percent_applied = amounts.discount_percent_applied
    record.discount_amount = amounts.discount_amount
    record.final_amount = record.manual_amount_override if record.manual_amount_override is not None else amounts.final_amount
    record.save(update_fields=[
        "plan", "season", "first_billing_month", "base_amount", "is_full_price",
        "sibling_discount_percent_applied", "discount_amount", "final_amount", "updated_at",
    ])
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_REASSIGNED),
        actor=actor,
        target=record,
        metadata={
            "old_plan_id": old_plan_id,
            "new_plan_id": plan.pk,
            "old_first_billing_month": old_month,
            "new_first_billing_month": first_billing_month,
        },
    )
```

- [ ] **Step 4: Add BillingRecordAdmin URL and button**

In `apps/billing/admin.py`, add URL:

```python
            path(
                "<int:object_id>/reassign/",
                self.admin_site.admin_view(self.reassign_view),
                name="billing_billingrecord_reassign",
            ),
```

Add readonly display in `fields` for `first_billing_month`.

Add method:

```python
    def reassign_view(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        from apps.billing.services import parse_first_billing_month, reassign_draft_billing_record

        record = get_object_or_404(BillingRecord, pk=object_id)
        plans = MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
        if request.method == "POST":
            plan = get_object_or_404(MembershipPlan, pk=request.POST.get("billing_plan"), is_active=True)
            first_billing_month = request.POST.get("first_billing_month", "")
            try:
                if first_billing_month:
                    parse_first_billing_month(first_billing_month)
                reassign_draft_billing_record(record, plan, first_billing_month=first_billing_month, actor=request.user)
                self.message_user(request, "Norēķinu ieraksts pārpiešķirts.")
                return redirect("admin:billing_billingrecord_change", object_id)
            except ValueError as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
        context = {
            **self.admin_site.each_context(request),
            "title": "Pārpiešķirt norēķinu ierakstu",
            "record": record,
            "plans": plans,
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/billing/billingrecord/reassign_confirm.html", context)
```

Add a readonly link/button method or include in `change_form_template`. Lazy path: add a readonly field `reassign_link` near `related_records`:

```python
    @admin.display(description="Pārpiešķiršana")
    def reassign_link(self, obj):
        if obj.status != BillingRecord.Status.DRAFT:
            return "—"
        if obj.invoices.filter(external_invoice_id__gt="").exists() or obj.invoices.filter(sent_at__isnull=False).exists():
            return "—"
        url = reverse("admin:billing_billingrecord_reassign", args=[obj.pk])
        return format_html('<a class="button" href="{}">Pārpiešķirt melnrakstu</a>', url)
```

Add `reassign_link` to `readonly_fields` and `fields`.

- [ ] **Step 5: Add reassignment template**

Create `templates/admin/billing/billingrecord/reassign_confirm.html`:

```django
{% extends "admin/base_site.html" %}

{% block content %}
<h1>{{ title }}</h1>
<p>{{ record }}</p>
<form method="post">
  {% csrf_token %}
  <div class="form-row">
    <label for="billing_plan">Jaunais norēķinu plāns:</label>
    <select id="billing_plan" name="billing_plan" required>
      {% for plan in plans %}
      <option value="{{ plan.pk }}"{% if record.plan_id == plan.pk %} selected{% endif %}>{{ plan.name }} — {{ plan.season }}</option>
      {% endfor %}
    </select>
  </div>
  <div class="form-row">
    <label for="first_billing_month">Pirmais rēķina mēnesis:</label>
    <input type="month" id="first_billing_month" name="first_billing_month" value="{{ record.first_billing_month }}">
  </div>
  <button type="submit" class="default">Pārpiešķirt</button>
</form>
{% endblock %}
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/billing/test_billing_record_reassignment.py -q
```

Expected: pass.

---

## Task 7: Admin polish, docs, and full verification

**Files:**
- Modify: `apps/billing/admin.py`
- Modify: `apps/agreements/admin.py`
- Modify: `docs/milestones.md`
- Modify: `AGENTS.md`
- Test: existing admin/search tests as needed

- [ ] **Step 1: Update admin list displays**

In `MembershipPlanAdmin.list_display`, include:

```python
"is_default", "billing_start_cutoff_day"
```

In `AgreementAdmin.list_display`, include:

```python
"billing_plan", "first_billing_month"
```

In `AgreementAdmin.readonly_fields`, include:

```python
"billing_plan", "first_billing_month"
```

In `BillingRecordAdmin.readonly_fields`, include:

```python
"first_billing_month"
```

- [ ] **Step 2: Run focused admin tests**

Run:

```bash
uv run pytest tests/agreements/test_admin_cross_links.py tests/billing/test_admin_confirm_action.py tests/members/test_member_renewal_admin.py tests/registrations/test_admin_agreement_billing_setup.py -q
```

Expected: pass.

- [ ] **Step 3: Update docs after code passes**

Update `docs/milestones.md` P9 section to `Status: complete` only after focused tests pass.

Add AGENTS current-status entry:

```markdown
- **P9 delivered — Billing plan lifecycle (2026-07-02)**: default billing plan + cutoff day, agreement-level billing-plan/month setup before signing, signing block without plan, selected-member billing-only renewal, draft-only BillingRecord reassignment/regeneration, and audit events for real mutations. Parent invoice UI remains P11.
```

- [ ] **Step 4: Run full verification**

Run:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected:

- pytest passes;
- ruff passes;
- mypy passes;
- makemigrations reports no changes.

---

## Implementation notes

- Use `uv run` for all Python commands.
- Do not touch unrelated dirty files in the working tree.
- Do not commit unless the user explicitly asks.
- If existing tests already cover part of this plan, extend those files instead of duplicating setup.
- Keep Latvian admin copy consistent with existing style.
- No new dependencies.

## Plan self-review

Spec coverage:

- Default plan and cutoff day: Task 1.
- Agreement billing setup and signing block: Tasks 2 and 4.
- Billing draft uses agreement plan/month: Tasks 2 and 3.
- Renewal selected members only: Task 5.
- Draft reassignment/regeneration: Task 6.
- Confirmed/synced no-silent-mutation: Task 6.
- Audit events: Tasks 4, 5, 6.
- Parent UI unchanged: Task 7 smoke via existing parent tests if touched; no parent template changes planned.

Placeholder scan: no placeholder work remains; every task names files, tests, commands, and expected outcomes.

Type consistency: `billing_plan`, `first_billing_month`, `is_default`, `billing_start_cutoff_day`, `derive_first_billing_month`, `parse_first_billing_month`, `renew_member_billing`, and `reassign_draft_billing_record` are used consistently across tasks.

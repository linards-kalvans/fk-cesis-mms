# P6 — Installment calendar (skip months) + per-plan payment due day

> **For agentic workers:** TDD, one behavior per commit. Steps use `- [ ]`.

**Goal:** Complete P6 acceptance item 6 ("agreed installment calendar … billing start month respected") by (1) skipping configured break months (default July + December) so the N installments land only on billing months, and (2) making the payment due day configurable per membership plan (default 20th).

**Context:** `apps/billing/services.py::derive_installment_schedule` currently places `installment_count` entries on consecutive months from `first_installment_month`, hardcoded to the 1st. Slice A note in its docstring already flagged day-of-month/calendar anchoring as revisitable. This is go-forward only — already-materialized `BillingInvoice` rows are not retroactively rescheduled (`materialize_installments` is idempotent).

**Decisions (locked 2026-06-09):**
- Skip → N **real** installments (no €0 invoices). €300 ÷ 10 = €30 across the non-skipped months.
- `skip_months` is a **per-plan** CSV field, default `"7,12"` (July, December).
- `payment_due_day` is **per-plan**, default **20**, clamped to the month length.

---

## Task 1: MembershipPlan fields + parsing helper

**Files:**
- Modify: `apps/billing/models.py`
- Create: `apps/billing/migrations/0007_membershipplan_schedule_fields.py` (via makemigrations)
- Test: `tests/billing/test_membership_plan.py` (append)

- [ ] **Step 1: Failing test** — append to `tests/billing/test_membership_plan.py`:

```python
def test_schedule_fields_defaults_and_skip_months_list(db):
    from apps.billing.models import MembershipPlan

    p = MembershipPlan.objects.create(name="P", season="2027")
    assert p.payment_due_day == 20
    assert p.skip_months == "7,12"
    assert p.skip_months_list == [7, 12]


def test_skip_months_list_parsing_is_tolerant(db):
    from apps.billing.models import MembershipPlan

    p = MembershipPlan.objects.create(name="P", season="2027", skip_months=" 7 , 12 ,, 13, x ")
    # whitespace tolerated; out-of-range / non-numeric dropped; sorted-unique
    assert p.skip_months_list == [7, 12]
    p2 = MembershipPlan.objects.create(name="P2", season="2027", skip_months="")
    assert p2.skip_months_list == []
```

- [ ] **Step 2: Run — expect FAIL** (`payment_due_day`/`skip_months`/`skip_months_list` missing).
Run: `uv run pytest tests/billing/test_membership_plan.py -k schedule_fields_defaults_or_skip_months -v` (and the parsing test).

- [ ] **Step 3: Add fields + property.** In `apps/billing/models.py`, add to `MembershipPlan` (after `first_installment_month`):

```python
    payment_due_day = models.PositiveSmallIntegerField(
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Mēneša diena, kad iestājas maksājuma termiņš (1–31).",
    )
    skip_months = models.CharField(
        max_length=32,
        default="7,12",
        blank=True,
        help_text='Mēneši (1–12) bez rēķina, ar komatu, piem. "7,12" (jūlijs, decembris).',
    )
```

Add a property on the model:

```python
    @property
    def skip_months_list(self) -> list[int]:
        months: set[int] = set()
        for part in self.skip_months.split(","):
            part = part.strip()
            if part.isdigit() and 1 <= int(part) <= 12:
                months.add(int(part))
        return sorted(months)
```

Add the validator import at the top of the file:

```python
from django.core.validators import MaxValueValidator, MinValueValidator
```

- [ ] **Step 4: Migration.** Run `uv run python manage.py makemigrations billing --name membershipplan_schedule_fields`. Confirm it adds exactly the two fields, depends on `0006_billingrecord_payment_error_code`.

- [ ] **Step 5: Run tests — expect PASS.**

- [ ] **Step 6: Commit.**
```bash
git add apps/billing/models.py apps/billing/migrations/0007_membershipplan_schedule_fields.py tests/billing/test_membership_plan.py
git commit -m "feat(billing): per-plan payment_due_day + skip_months on MembershipPlan (P6)"
```

---

## Task 2: derive_installment_schedule — skip months + due day

**Files:**
- Modify: `apps/billing/services.py`
- Test: `tests/billing/test_installment_schedule.py` (append; read existing tests first to match fixture style)

- [ ] **Step 1: Failing tests** — append to `tests/billing/test_installment_schedule.py`:

```python
def test_schedule_skips_july_and_december(db):
    from decimal import Decimal
    from datetime import date
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=10,
        first_installment_month=1, skip_months="7,12", payment_due_day=20,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    assert [d.month for d, _ in sched] == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11]
    assert all(d.day == 20 for d, _ in sched)
    assert all(d.year == 2027 for d, _ in sched)
    assert [a for _, a in sched] == [Decimal("30.00")] * 10
    assert sum(a for _, a in sched) == Decimal("300.00")


def test_schedule_due_day_clamped_to_month_length(db):
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=3,
        first_installment_month=1, skip_months="", payment_due_day=31,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    # Jan 31, Feb 28 (2027 not leap), Mar 31
    assert [(d.month, d.day) for d, _ in sched] == [(1, 31), (2, 28), (3, 31)]


def test_schedule_wraps_year_skipping_december(db):
    from decimal import Decimal
    from apps.billing.models import MembershipPlan
    from apps.billing.services import derive_installment_schedule

    plan = MembershipPlan.objects.create(
        name="P", season="2027", installment_count=3,
        first_installment_month=11, skip_months="12", payment_due_day=20,
    )
    sched = derive_installment_schedule(plan, Decimal("300.00"))
    # Nov 2027, (skip Dec), Jan 2028, Feb 2028
    assert [(d.year, d.month) for d, _ in sched] == [(2027, 11), (2028, 1), (2028, 2)]
```

Also read the existing tests in this file; if any assert the old "day == 1" behavior with the default plan, update them to the new default (`payment_due_day=20`) or pass an explicit `payment_due_day=1`/`skip_months=""` to preserve their intent. Report which you changed.

- [ ] **Step 2: Run — expect FAIL** on the new skip/clamp/wrap tests.

- [ ] **Step 3: Implement.** Replace the body of `derive_installment_schedule` in `apps/billing/services.py`. Keep the amount-split logic; change month placement to skip + clamp. Add `import calendar` at the top if not present (`datetime` already imported).

```python
def derive_installment_schedule(plan, total: Decimal) -> list[tuple[datetime.date, Decimal]]:
    """Split `total` into `plan.installment_count` equal monthly entries, placed on
    successive billing months starting at `plan.first_installment_month` and SKIPPING
    any month in `plan.skip_months_list` (default July + December). Equal cents; the
    last entry absorbs the rounding remainder. Each due date is `plan.payment_due_day`
    (clamped to the month length). The year is anchored to the first year in
    `plan.season` ("2026/2027" -> 2026) and rolls forward when the month wraps past
    December."""
    count = max(int(plan.installment_count), 1)
    per = _money(total / Decimal(count))
    amounts = [per] * (count - 1)
    amounts.append(_money(total - per * (count - 1)))

    skip = set(plan.skip_months_list)
    due_day = int(plan.payment_due_day)
    start_year = int(plan.season.split("/")[0])

    schedule: list[tuple[datetime.date, Decimal]] = []
    month = int(plan.first_installment_month)
    year = start_year
    guard = 0
    for amount in amounts:
        # Advance past any skipped months before placing this installment.
        while month in skip:
            month += 1
            if month > 12:
                month = 1
                year += 1
            guard += 1
            if guard > 240:  # safety: skip_months must never cover all 12
                raise ValueError("derive_installment_schedule: no billing months available")
        day = min(due_day, calendar.monthrange(year, month)[1])
        schedule.append((datetime.date(year, month, day), amount))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return schedule
```

(Confirm `_money` and the `import datetime` / `from decimal import Decimal` imports already exist at module top — they do; add `import calendar`.)

- [ ] **Step 4: Run tests — expect PASS** (new + any you updated).
Run: `uv run pytest tests/billing/test_installment_schedule.py tests/billing/test_materialize_installments.py -v`

- [ ] **Step 5: Commit.**
```bash
git add apps/billing/services.py tests/billing/test_installment_schedule.py
git commit -m "feat(billing): installment schedule skips break months + per-plan due day (P6)"
```

---

## Task 3: Admin surfacing

**Files:**
- Modify: `apps/billing/admin.py`
- Test: `tests/billing/test_billing_admin.py` (append a light assertion)

- [ ] **Step 1: Failing test** — append to `tests/billing/test_billing_admin.py`:

```python
def test_membership_plan_admin_shows_schedule_fields(active_plan, staff_client):
    from django.urls import reverse

    url = reverse("admin:billing_membershipplan_change", args=[active_plan.pk])
    resp = staff_client.get(url)
    assert resp.status_code == 200
    assert b"payment_due_day" in resp.content
    assert b"skip_months" in resp.content
```

- [ ] **Step 2: Run — expect FAIL** (fields not on the form yet — they ARE editable by default since ModelAdmin shows all fields unless `fields`/`exclude` set; check `MembershipPlanAdmin`. If it has no `fields`/`fieldsets`, the new model fields appear automatically and the test may PASS already — in that case just extend `list_display` per Step 3 and keep the test as a regression guard).

- [ ] **Step 3: Surface the fields.** In `apps/billing/admin.py`, extend `MembershipPlanAdmin.list_display` to include `"payment_due_day"` after `"first_installment_month"`:

```python
    list_display = (
        "name", "season", "annual_amount", "sibling_discount_percent",
        "installment_count", "first_installment_month", "payment_due_day", "is_active",
    )
```

`MembershipPlanAdmin` defines no `fields`/`fieldsets`, so `payment_due_day` and `skip_months` already render on the change form. No further change needed for editability.

- [ ] **Step 4: Run tests — expect PASS.**

- [ ] **Step 5: Commit.**
```bash
git add apps/billing/admin.py tests/billing/test_billing_admin.py
git commit -m "feat(billing): surface payment_due_day in plan admin list (P6)"
```

---

## Task 4: Gate + docs

- [ ] **Step 1: Full gate.** `uv run pytest -q` (all green), `uv run ruff check .`, `uv run mypy .`. Record the passed count. Fail loud if anything is red.
- [ ] **Step 2: Docs.** In `AGENTS.md` P6 section, note the installment-calendar + per-plan due-day completion (skip_months default Jul+Dec, payment_due_day default 20, migration `billing/0007`, go-forward only). In `docs/milestones.md`, mark P6 acceptance item 6 (installment calendar) as fully implemented.
- [ ] **Step 3: Commit docs.**

---

## Self-review notes
- Spec coverage: skip months → Task 2; per-plan config → Task 1; due day + clamp → Tasks 1+2; admin → Task 3.
- The amount split is unchanged: `installment_count` is the number of real (non-skipped) invoices, so €300 ÷ 10 = €30 with the last absorbing any remainder.
- Out of scope: retroactively rescheduling already-materialized invoices; the €0-invoice alternative (explicitly rejected); changing `installment_count`/`first_installment_month` defaults (data config, set per plan).

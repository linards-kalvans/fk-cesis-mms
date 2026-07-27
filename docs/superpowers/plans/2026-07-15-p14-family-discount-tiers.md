# Family Discount Tiers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat per-plan sibling discount with fixed family tiers of 0 %, 50 %, 75 %, and 100 %, snapshotting each new billing record under a guardian-row lock.

**Architecture:** Normal signed-agreement creation ranks a guardian's current, signed, season-matching agreements by `signed_at, member_id`; P9 billing-only renewal ranks the guardian's current signed family across plan seasons. A small billing-service helper turns that rank into a snapshotted `BillingAmounts`; both creation paths call it while holding `Guardian.select_for_update()`. Existing records keep their stored values. A zero-total record remains local and is marked synced without Invoice Ninja activity.

**Tech Stack:** Python 3.12, Django 5/6 project runtime, PostgreSQL production lock semantics, pytest + pytest-django, uv, ruff, mypy.

---

## 1. Scope and locked decisions

### In scope

- Fixed map: rank 0 → 0 %, rank 1 → 50 %, rank 2 → 75 %, rank 3+ → 100 %.
- New records from both `create_draft_billing_for_member()` and `renew_member_billing()`.
- Agreement-time ordering, guardian/season isolation, discontinuation filtering, opt-out rank preservation, snapshot preservation, local zero-total handling, and draft-only staff overrides.
- Drop `MembershipPlan.sibling_discount_percent`.

### Out of scope

- P15 partial calendar-year totals, new parent UI, configurable tier policies, changing old records/invoices, or credit/refund work.

### Data flow

```text
signed agreement / staff billing-only renewal
            |
            v
lock Guardian row ──> ordered current signed agreements
            |              (plan-season scoped only for signing path)
            |                         |
            |                         v
            |                    rank -> tier percent
            v
BillingRecord snapshot (base, actual applied %, discount, final)
            |
            +-- 100 % tier: final = 0 -> local record only
            +-- non-zero: existing confirm -> Invoice Ninja flow
```

### Why each decision

- **Guardian lock:** two sibling signings must not claim the same tier. PostgreSQL enforces `SELECT ... FOR UPDATE`; SQLite test DB cannot, so tests assert the lock call.
- **Agreement-rooted ranking:** member creation order is not billing intent. Signing time is club policy and a stable `member_id` tie-break prevents nondeterminism.
- **Applied-percent snapshot:** future family, plan, or sign-order changes must not reprice a record. Opt-out stores actual applied `0`, not declined tier.
- **Zero rows, zero provider calls:** Invoice Ninja should never receive a €0 invoice. `external_status="synced"` is the local terminal state.
- **No tier configuration:** club policy is fixed. A model field would create unsupported plan-level policy forks.

## 2. Contracts and component boundaries

### Service contracts

```python
TIER_DISCOUNT_PERCENT: dict[int, Decimal] = {
    0: Decimal("0.00"),
    1: Decimal("50.00"),
    2: Decimal("75.00"),
    3: Decimal("100.00"),
}

def compute_family_tier(
    member, plan, first_due_date: datetime.date, *, season_scoped: bool = True
) -> int:
    """Return rank clamped to 3 for billable siblings.

    Legacy callers whose member is not in the signed cohort receive rank 0,
    preserving the current no-agreement fallback as full price. The P9 renewal
    path passes ``season_scoped=False`` to use current signed family across
    target-plan seasons.
    """

def create_draft_billing_for_member(member, agreement) -> BillingRecord | None:
    """Idempotently create one season record under guardian lock."""

def renew_member_billing(member, plan, *, first_billing_month: str = "", actor=None) -> BillingRecord | None:
    """Create one renewal record under guardian lock and audit real creation."""
```

### Eligibility query

`compute_family_tier()` must root in `Agreement`, not `Member`, and use this exact semantic filter before optionally applying season scoping:

```python
candidates = (
    Agreement.objects.filter(
        is_current=True,
        state=Agreement.State.SIGNED,
        member__guardian_id=member.guardian_id,
    )
    .exclude(
        Q(
            member__discontinued_effective_date__isnull=False,
            member__discontinued_effective_date__lte=first_due_date,
        )
        | Q(
            member__status=Member.Status.DISCONTINUED,
            member__discontinued_effective_date__isnull=True,
        )
    )
    .select_related("member")
    .order_by("signed_at", "member_id")
)

if season_scoped:
    candidates = candidates.filter(billing_plan__season=plan.season)
```

An effective date strictly after `first_due_date` remains eligible. Different plans in the same season intentionally share a tier because normal signing-path policy is season-scoped. P9 renewal deliberately uses the current signed family across seasons; it creates no new agreement.

### Files

| File | Change |
|---|---|
| `apps/billing/services.py` | Fixed tier map, signed-agreement rank query, locked record creation, snapshot-safe recompute/reassign, zero materialization guard. |
| `apps/integrations/tasks.py` | Short-circuit confirmed zero-total push before pending/product/client work. |
| `apps/billing/models.py` | Remove `MembershipPlan.sibling_discount_percent`; retain all `BillingRecord` snapshots. |
| `apps/billing/admin.py` | Draft-only override ModelForm plus safe override audit merged into existing status audit. |
| `apps/core/models.py` | Add `BILLING_RECORD_AMOUNT_OVERRIDDEN`. |
| `apps/core/migrations/0007_alter_auditevent_action.py` | Generated audit-choice migration. |
| `apps/billing/migrations/0014_remove_membershipplan_sibling_discount_percent.py` | Generated schema-only field removal. |
| `tests/billing/test_discount_engine.py` | Main tier/rank/discontinuation/snapshot/renewal/lock tests. |
| `tests/billing/test_materialize_installments.py` | Zero-total materialization regression. |
| `tests/billing/test_push_billing_record.py` | Zero-total no-provider-call regression. |
| `tests/billing/test_billing_admin.py` | Override validation, final-total persistence, and safe audit metadata. |
| `tests/billing/{conftest.py,test_membership_plan.py}` | Remove obsolete plan-field fixture and assertion. |
| `tests/integrations/conftest.py` | Remove obsolete plan-field fixture argument. |
| `tests/registrations/test_guardian_dedup.py` | Replace flat-engine assertion with signed-agreement record snapshots. |
| `docs/milestones.md`, `AGENTS.md` | Mark P14 delivered only after full green verification; no P15 implementation note beyond its existing planned status. |

## 3. Test strategy

**Framework:** existing `pytest` + `pytest-django`; test DB uses SQLite.

**Test before implementation:** test engineer writes all new/changed tests and proves red before software engineer edits business code.

**Test:** tier map, signed-time and pk ordering, guardian and signing-season isolation, P9 renewal's cross-season current-family exception, opt-out ranking, effective-date and malformed-discontinuation exclusion, future-date inclusion, snapshot/recompute/reassign stability, guardian lock invocation, zero materialization/push, override validation/audit, field removal, and legacy no-agreement full-price fallback.

**Do not test:** browser layout, real Invoice Ninja HTTP, a true cross-connection database lock race on SQLite, or P15 proration.

---

## 4. TDD tasks

**Test-first gate:** Before any production-file edit in Tasks 2–6, test engineer completes every test-writing step in Tasks 1, 4, 5, and 6. Run their combined targeted set once and record red failures for missing tier behavior, zero guards, override form/audit, and removed field. Software engineer starts only after this red suite is reviewed for full acceptance coverage.

### Task 1: Write complete red tier and record-creation tests

**Files:**
- Modify: `tests/billing/test_discount_engine.py`
- Modify: `tests/billing/test_create_draft.py`
- Modify: `tests/billing/test_billing_admin.py`
- Modify: `tests/registrations/test_guardian_dedup.py`

- [ ] **Step 1: Replace old creation-order helper with signed-agreement helper**

Use one local helper in `test_discount_engine.py`; it deliberately creates the source application so opt-out is read through `member.source_application`.

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _signed_member(guardian, plan, name, *, signed_at, opt_out=False):
    from apps.agreements.models import Agreement
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        approved_member=member,
        support_club_instead_of_multi_child_discount=opt_out,
    )
    agreement = Agreement.objects.create(
        member=member,
        billing_plan=plan,
        first_billing_month="2026-09",
        state=Agreement.State.SIGNED,
        is_current=True,
        generated_at=signed_at - timedelta(days=1),
        signed_at=signed_at,
    )
    return member, agreement
```

- [ ] **Step 2: Add four parameterized tier snapshot tests**

```python
@pytest.mark.parametrize(
    ("child_count", "expected_percent", "expected_final"),
    [
        (1, Decimal("0.00"), Decimal("300.00")),
        (2, Decimal("50.00"), Decimal("150.00")),
        (3, Decimal("75.00"), Decimal("75.00")),
        (4, Decimal("100.00"), Decimal("0.00")),
        (5, Decimal("100.00"), Decimal("0.00")),
    ],
)
def test_signed_child_receives_fixed_family_tier(
    active_plan, guardian, child_count, expected_percent, expected_final
):
    from apps.billing.services import create_draft_billing_for_member

    start = timezone.now() - timedelta(days=10)
    created = [
        _signed_member(
            guardian, active_plan, f"Bērns {number}",
            signed_at=start + timedelta(minutes=number),
        )
        for number in range(child_count)
    ]
    member, agreement = created[-1]

    record = create_draft_billing_for_member(member, agreement)

    assert record.sibling_discount_percent_applied == expected_percent
    assert record.final_amount == expected_final
    assert record.discount_amount == Decimal("300.00") - expected_final
    assert record.is_full_price is (child_count == 1)
```

- [ ] **Step 3: Add rank-definition tests**

```python
def test_rank_uses_signed_time_then_member_pk(active_plan, guardian):
    from apps.billing.services import compute_family_tier

    signed_at = timezone.now()
    later_member, _ = _signed_member(
        guardian, active_plan, "Vēlāk", signed_at=signed_at + timedelta(days=1)
    )
    earlier_member, _ = _signed_member(
        guardian, active_plan, "Agrāk", signed_at=signed_at
    )
    tied_first, _ = _signed_member(
        guardian, active_plan, "Pirmais vienlaikus", signed_at=signed_at + timedelta(days=2)
    )
    tied_second, _ = _signed_member(
        guardian, active_plan, "Otrais vienlaikus", signed_at=signed_at + timedelta(days=2)
    )

    due = date(2026, 9, 20)
    assert compute_family_tier(earlier_member, active_plan, due) == 0
    assert compute_family_tier(later_member, active_plan, due) == 1
    assert compute_family_tier(tied_first, active_plan, due) == 2
    assert compute_family_tier(tied_second, active_plan, due) == 3


def test_other_guardian_and_season_do_not_occupy_rank(active_plan, guardian):
    from apps.billing.models import MembershipPlan
    from apps.billing.services import compute_family_tier
    from tests.support import make_guardian

    other_guardian = make_guardian(full_name="Cits Vecāks", email="other@example.test")
    other_plan = MembershipPlan.objects.create(
        name="Cita sezona", season="2027/2028", annual_amount=Decimal("300.00"),
        installment_count=10, first_installment_month=9, is_active=True,
    )
    now = timezone.now()
    _signed_member(other_guardian, active_plan, "Svešs", signed_at=now)
    _signed_member(guardian, other_plan, "Cita sezona", signed_at=now)
    target, _ = _signed_member(guardian, active_plan, "Mērķis", signed_at=now)

    assert compute_family_tier(target, active_plan, date(2026, 9, 20)) == 0


def test_billing_only_renewal_uses_current_signed_family(active_plan, guardian):
    from apps.billing.models import MembershipPlan
    from apps.billing.services import renew_member_billing

    renewal_plan = MembershipPlan.objects.create(
        name="Nākamā sezona", season="2027/2028", annual_amount=Decimal("300.00"),
        installment_count=10, first_installment_month=9, is_active=True,
    )
    now = timezone.now()
    first, _ = _signed_member(guardian, active_plan, "Pirmais", signed_at=now)
    second, _ = _signed_member(
        guardian, active_plan, "Otrais", signed_at=now + timedelta(minutes=1)
    )

    first_record = renew_member_billing(first, renewal_plan, first_billing_month="2027-09")
    second_record = renew_member_billing(second, renewal_plan, first_billing_month="2027-09")

    assert first_record.sibling_discount_percent_applied == Decimal("0.00")
    assert second_record.sibling_discount_percent_applied == Decimal("50.00")
```

- [ ] **Step 4: Add opt-out and discontinuation tests**

```python
def test_opt_out_stays_full_price_and_preserves_rank(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member

    now = timezone.now()
    _first, _ = _signed_member(guardian, active_plan, "Pirmais", signed_at=now)
    opted_out, opted_out_agreement = _signed_member(
        guardian, active_plan, "Otrais", signed_at=now + timedelta(minutes=1), opt_out=True
    )
    third, third_agreement = _signed_member(
        guardian, active_plan, "Trešais", signed_at=now + timedelta(minutes=2)
    )

    opted_out_record = create_draft_billing_for_member(opted_out, opted_out_agreement)
    third_record = create_draft_billing_for_member(third, third_agreement)

    assert opted_out_record.sibling_discount_percent_applied == Decimal("0.00")
    assert opted_out_record.discount_amount == Decimal("0.00")
    assert opted_out_record.final_amount == Decimal("300.00")
    assert opted_out_record.is_full_price is True
    assert opted_out_record.full_price_opt_out is True
    assert third_record.sibling_discount_percent_applied == Decimal("75.00")
    assert third_record.final_amount == Decimal("75.00")


@pytest.mark.parametrize(
    ("effective_date", "status", "expected_rank"),
    [
        (date(2026, 9, 20), "active", 1),
        (date(2026, 9, 19), "active", 1),
        (date(2026, 9, 21), "active", 2),
        (None, "discontinued", 1),
    ],
)
def test_discontinuation_rules_filter_family_rank(
    active_plan, guardian, effective_date, status, expected_rank
):
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    now = timezone.now()
    _signed_member(guardian, active_plan, "Pirmais", signed_at=now)
    excluded, _ = _signed_member(
        guardian, active_plan, "Pārtrauktais", signed_at=now + timedelta(minutes=1)
    )
    excluded.status = status
    excluded.discontinued_effective_date = effective_date
    excluded.save(update_fields=["status", "discontinued_effective_date"])
    target, _ = _signed_member(
        guardian, active_plan, "Mērķis", signed_at=now + timedelta(minutes=2)
    )

    assert compute_family_tier(target, active_plan, date(2026, 9, 20)) == expected_rank
```

- [ ] **Step 5: Add fallback, snapshot, recompute, reassign, and lock tests**

```python
def test_legacy_no_agreement_fallback_is_full_price(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member
    from apps.members.models import Member

    member = Member.objects.create(full_name="Vēsturiskais", guardian=guardian)
    record = create_draft_billing_for_member(member, agreement=None)
    assert record.sibling_discount_percent_applied == Decimal("0.00")
    assert record.final_amount == Decimal("300.00")


def test_recompute_and_reassign_keep_stored_percent(active_plan, guardian):
    from apps.billing.models import MembershipPlan
    from apps.billing.services import (
        create_draft_billing_for_member,
        recompute_billing_record,
        reassign_draft_billing_record,
    )

    now = timezone.now()
    _signed_member(guardian, active_plan, "Pirmais", signed_at=now)
    member, agreement = _signed_member(
        guardian, active_plan, "Otrais", signed_at=now + timedelta(minutes=1)
    )
    record = create_draft_billing_for_member(member, agreement)
    replacement = MembershipPlan.objects.create(
        name="Nākamais", season="2027/2028", annual_amount=Decimal("400.00"),
        installment_count=10, first_installment_month=9, is_active=True,
    )

    active_plan.annual_amount = Decimal("400.00")
    active_plan.save(update_fields=["annual_amount", "updated_at"])
    recompute_billing_record(record)
    record.refresh_from_db()
    assert (record.sibling_discount_percent_applied, record.discount_amount, record.final_amount) == (
        Decimal("50.00"), Decimal("200.00"), Decimal("200.00")
    )

    reassign_draft_billing_record(record, replacement, first_billing_month="2027-09")
    record.refresh_from_db()
    assert (record.sibling_discount_percent_applied, record.discount_amount, record.final_amount) == (
        Decimal("50.00"), Decimal("200.00"), Decimal("200.00")
    )


def test_creation_locks_guardian_row(active_plan, guardian, monkeypatch):
    from apps.billing.services import create_draft_billing_for_member
    from apps.members.models import Guardian

    member, agreement = _signed_member(
        guardian, active_plan, "Slēgts", signed_at=timezone.now()
    )
    calls = []
    original = Guardian.objects.select_for_update

    def tracking_select_for_update(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(Guardian.objects, "select_for_update", tracking_select_for_update)
    create_draft_billing_for_member(member, agreement)
    assert calls
```

- [ ] **Step 6: Make existing generic tests use signed helper where they test new policy**

Replace `tests/registrations/test_guardian_dedup.py::test_sibling_discount_applies_after_approving_two_children` with a record-snapshot test using two signed agreements, and remove imports/assertions for `compute_billing_amounts`. Keep generic `agreement=None` tests in `test_create_draft.py`, `test_billing_admin.py`, and `test_billing_presentation.py`: Task 2 explicitly preserves this legacy full-price fallback.

- [ ] **Step 7: Prove tests are red before implementation**

Run:

```bash
uv run pytest tests/billing/test_discount_engine.py tests/registrations/test_guardian_dedup.py -q
```

Expected: failures/import errors because fixed tier service and signed-agreement implementation do not exist; old flat-discount assertions must no longer remain.

### Task 2: Implement rank calculation and locked record creation

**Files:**
- Modify: `apps/billing/services.py`

- [ ] **Step 1: Replace creation-order flat engine with rank engine**

Delete `_is_first_child()` and old `compute_billing_amounts(member, plan)`. Add imports and helpers:

```python
from django.db import transaction
from django.db.models import Q


TIER_DISCOUNT_PERCENT = {
    0: Decimal("0.00"),
    1: Decimal("50.00"),
    2: Decimal("75.00"),
    3: Decimal("100.00"),
}


def compute_family_tier(
    member, plan, first_due_date: datetime.date, *, season_scoped: bool = True
) -> int:
    from apps.agreements.models import Agreement
    from apps.members.models import Member

    candidates = (
        Agreement.objects.filter(
            is_current=True,
            state=Agreement.State.SIGNED,
            member__guardian_id=member.guardian_id,
        )
        .exclude(
            Q(
                member__discontinued_effective_date__isnull=False,
                member__discontinued_effective_date__lte=first_due_date,
            )
            | Q(
                member__status=Member.Status.DISCONTINUED,
                member__discontinued_effective_date__isnull=True,
            )
        )
        .select_related("member")
        .order_by("signed_at", "member_id")
    )
    if season_scoped:
        candidates = candidates.filter(billing_plan__season=plan.season)
    for rank, candidate in enumerate(candidates):
        if candidate.member_id == member.pk:
            return min(rank, max(TIER_DISCOUNT_PERCENT))
    return 0


def _first_billable_due_date(plan, first_billing_month: str) -> datetime.date:
    return derive_installment_schedule(
        plan, Decimal("0.00"), first_billing_month=first_billing_month
    )[0][0]


def _tiered_billing_amounts(
    member, plan, first_billing_month: str, *, season_scoped: bool
) -> BillingAmounts:
    base = _money(plan.annual_amount)
    tier_percent = TIER_DISCOUNT_PERCENT[
        compute_family_tier(
            member,
            plan,
            _first_billable_due_date(plan, first_billing_month),
            season_scoped=season_scoped,
        )
    ]
    opt_out = _member_opted_out(member)
    percent = Decimal("0.00") if opt_out else tier_percent
    discount = _money(base * percent / Decimal("100"))
    return BillingAmounts(
        base_amount=base,
        is_full_price=percent == Decimal("0.00"),
        discount_percent_applied=percent,
        discount_amount=discount,
        final_amount=_money(base - discount),
    )
```

- [ ] **Step 2: Lock all draft creation before reading rank or creating row**

In `create_draft_billing_for_member`, preserve current plan/payment-mode fallback. Move season-record existence check inside this transaction and replace `get_or_create` defaults with `BillingRecord.objects.create(...)` while locked:

```python
from apps.members.models import Guardian

with transaction.atomic():
    Guardian.objects.select_for_update().get(pk=member.guardian_id)
    existing = BillingRecord.objects.filter(member=member, season=plan.season).first()
    if existing is not None:
        return existing

    amounts = _tiered_billing_amounts(
        member, plan, first_billing_month, season_scoped=True
    )
    return BillingRecord.objects.create(
        member=member,
        plan=plan,
        agreement=agreement,
        season=plan.season,
        base_amount=amounts.base_amount,
        is_full_price=amounts.is_full_price,
        sibling_discount_percent_applied=amounts.discount_percent_applied,
        discount_amount=amounts.discount_amount,
        final_amount=amounts.final_amount,
        payment_mode=payment_mode,
        full_price_opt_out=opt_out,
        first_billing_month=first_billing_month,
    )
```

For `agreement=None`, `compute_family_tier()` cannot find the candidate in the signed cohort and returns rank 0. This preserves current legacy/backfill tests as full price; normal signal and backfill paths supply the signed agreement.

- [ ] **Step 3: Apply exact same snapshot policy to renewals**

In `renew_member_billing`, resolve `agreement = get_current_agreement(member)` once, then acquire the guardian lock before checking the existing `(member, season)` record. Replace the existing unprotected existence/flat-amount block with:

```python
from apps.members.models import Guardian

with transaction.atomic():
    Guardian.objects.select_for_update().get(pk=member.guardian_id)
    if BillingRecord.objects.filter(member=member, season=plan.season).exists():
        return None

    amounts = _tiered_billing_amounts(
        member, plan, first_billing_month, season_scoped=False
    )
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
```

This is P9's explicit billing-only exception: current signed family ranks the new target-season records even though no target-season agreement is created. When this member has no current signed agreement, the helper's candidate-missing fallback is rank 0/full price. Preserve `BILLING_RECORD_RENEWED` audit and its metadata exactly; emit it after the transaction creates the row.

- [ ] **Step 4: Run service tests**

```bash
uv run pytest tests/billing/test_discount_engine.py tests/billing/test_create_draft.py tests/registrations/test_guardian_dedup.py -q
```

Expected: pass. Existing no-agreement tests remain full-price; signed tests show four fixed tiers.

### Task 3: Preserve existing snapshots on recompute and reassignment

**Files:**
- Modify: `apps/billing/services.py`
- Modify: `tests/billing/test_billing_admin.py`

- [ ] **Step 1: Use the red snapshot test from Task 1**

`test_recompute_and_reassign_keep_stored_percent` is written before production edits by the test-first gate. It pins the exact result after a €400 plan edit and a plan reassignment: stored percent `50.00`, discount `200.00`, final `200.00`. Extend that same test before Task 2 starts with a non-null `manual_amount_override=Decimal("123.00")`; after recompute and reassignment, `final_amount` must remain `123.00` while the stored percent stays `50.00`.

- [ ] **Step 2: Replace recompute rank call with stored snapshot**

```python
percent = record.sibling_discount_percent_applied
record.base_amount = _money(plan.annual_amount)
record.discount_amount = _money(record.base_amount * percent / Decimal("100"))
record.final_amount = (
    record.manual_amount_override
    if record.manual_amount_override is not None
    else _money(record.base_amount - record.discount_amount)
)
record.save(
    update_fields=[
        "base_amount", "discount_amount", "final_amount", "updated_at",
    ]
)
```

Do not assign `is_full_price`, `full_price_opt_out`, or `sibling_discount_percent_applied` in `recompute_billing_record()`.

- [ ] **Step 3: Apply same rule to reassignment**

After deleting local-only invoices and assigning new plan/season/month, calculate only `base_amount`, `discount_amount`, and `final_amount` from the existing record snapshot. Do not call `compute_family_tier`, `_tiered_billing_amounts`, or alter `is_full_price`, `full_price_opt_out`, or `sibling_discount_percent_applied`.

- [ ] **Step 4: Run snapshot tests**

```bash
uv run pytest tests/billing/test_discount_engine.py tests/billing/test_billing_admin.py -q
```

Expected: pass; adding/signing later siblings never alters old record tiers.

### Task 4: Prevent all zero-total Invoice Ninja work

**Files:**
- Modify: `tests/billing/test_materialize_installments.py`
- Modify: `tests/billing/test_push_billing_record.py`
- Modify: `apps/billing/services.py`
- Modify: `apps/integrations/tasks.py`

- [ ] **Step 1: Add red zero-total regressions**

```python
def test_zero_total_never_materializes_invoices(active_plan, guardian):
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.billing.services import materialize_installments

    record = _record(active_plan, guardian, BillingRecord.PaymentMode.INSTALLMENTS, "0.00")
    assert materialize_installments(record) == []
    assert not BillingInvoice.objects.filter(billing_record=record).exists()
```

Add a confirmed-zero push test that monkeypatches `_ensure_product_id`, `_ensure_client_id`, and `invoice_platform.create_invoice` to raise `AssertionError`. After `push_billing_record(record.pk)`, assert `external_status == "synced"`, error code is blank, and no `BillingInvoice` exists.

- [ ] **Step 2: Short-circuit materialization before existing-row lookup**

At top of `materialize_installments()` after imports:

```python
if record.final_amount == Decimal("0.00"):
    return []
```

- [ ] **Step 3: Short-circuit push before pending/external resources**

Add `from decimal import Decimal` to `apps/integrations/tasks.py`. After confirmed and already-synced guards, before `record.external_status = "pending"`:

```python
if record.final_amount == Decimal("0.00"):
    record.external_status = "synced"
    record.external_error_code = ""
    record.save(update_fields=["external_status", "external_error_code", "updated_at"])
    return
```

- [ ] **Step 4: Run zero path tests**

```bash
uv run pytest tests/billing/test_materialize_installments.py tests/billing/test_push_billing_record.py -q
```

Expected: pass. No product, client, invoice, send, or payment-sync work is possible because no `BillingInvoice` row exists.

### Task 5: Enforce and audit draft-only manual overrides

**Files:**
- Modify: `tests/billing/test_billing_admin.py`
- Modify: `apps/billing/admin.py`
- Modify: `apps/core/models.py`

- [ ] **Step 1: Add red admin-form and audit tests**

Use `BillingRecordAdminForm` directly for validation and `staff_client.post()` to the record change URL for audit:

```python
form = BillingRecordAdminForm(
    instance=record,
    data={
        "manual_amount_override": "0.00",
        "manual_override_reason": "Kluba lēmums",
        "status": BillingRecord.Status.DRAFT,
    },
)
assert form.is_valid(), form.errors
saved = form.save()
assert saved.final_amount == Decimal("0.00")

missing_reason = BillingRecordAdminForm(
    instance=record,
    data={
        "manual_amount_override": "150.00",
        "manual_override_reason": "   ",
        "status": BillingRecord.Status.DRAFT,
    },
)
assert not missing_reason.is_valid()
assert "manual_override_reason" in missing_reason.errors
```

For a confirmed record, attempt to change amount and then reason separately; both must fail. For a successful change-form POST, assert exactly one `AuditEvent` with `BILLING_RECORD_AMOUNT_OVERRIDDEN`, old/new override values, request actor/IP metadata, and no reason value or reason key in `metadata`.

- [ ] **Step 2: Add explicit form with three editable fields**

At module level in `apps/billing/admin.py`:

```python
from django import forms


class BillingRecordAdminForm(forms.ModelForm):
    class Meta:
        model = BillingRecord
        fields = ("manual_amount_override", "manual_override_reason", "status")

    def clean(self):
        cleaned = super().clean()
        override = cleaned.get("manual_amount_override")
        reason = (cleaned.get("manual_override_reason") or "").strip()
        original = (
            BillingRecord.objects.only(
                "status", "manual_amount_override", "manual_override_reason"
            ).get(pk=self.instance.pk)
            if self.instance.pk
            else None
        )

        if override is not None and not reason:
            self.add_error("manual_override_reason", "Ievadiet iemeslu.")
        if original is not None and original.status != BillingRecord.Status.DRAFT:
            if (
                original.manual_amount_override != override
                or original.manual_override_reason != reason
            ):
                self.add_error(
                    "manual_amount_override",
                    "Apstiprinātiem ierakstiem pārrēķins nav pieejams.",
                )

        self.instance.manual_override_reason = reason
        self.instance.final_amount = (
            override
            if override is not None
            else self.instance.base_amount - self.instance.discount_amount
        )
        return cleaned
```

Set `form = BillingRecordAdminForm` on `BillingRecordAdmin`. The clear-override branch restores natural snapshot total; no service recompute is needed.

- [ ] **Step 3: Extend existing `save_model()` without losing status audit**

Fetch one persisted original before `super().save_model()`, then emit existing confirmation audit plus new override audit:

```python
previous = (
    BillingRecord.objects.only(
        "status", "manual_amount_override", "manual_override_reason"
    ).get(pk=obj.pk)
    if change and obj.pk
    else None
)
super().save_model(request, obj, form, change)

if previous is not None and (
    previous.manual_amount_override != obj.manual_amount_override
    or previous.manual_override_reason != obj.manual_override_reason
):
    record_audit_event(
        action=str(AuditEvent.Action.BILLING_RECORD_AMOUNT_OVERRIDDEN),
        actor=request.user,
        request=request,
        target=obj,
        metadata={
            "old_override": (
                str(previous.manual_amount_override)
                if previous.manual_amount_override is not None
                else None
            ),
            "new_override": (
                str(obj.manual_amount_override)
                if obj.manual_amount_override is not None
                else None
            ),
        },
    )
```

Keep the existing `BILLING_RECORD_CONFIRMED` condition, deriving it from `previous.status == DRAFT` and `obj.status == CONFIRMED`.

- [ ] **Step 4: Add audit choice**

```python
BILLING_RECORD_AMOUNT_OVERRIDDEN = (
    "billing_record_amount_overridden",
    "Billing record amount overridden",
)
```

Place it after `BILLING_RECORD_REASSIGNED` in `AuditEvent.Action`.

- [ ] **Step 5: Run override tests**

```bash
uv run pytest tests/billing/test_billing_admin.py tests/core -q
```

Expected: valid €0 override persists €0 total; missing reason and all confirmed-record changes fail; audit never exposes reason text.

### Task 6: Remove obsolete plan configuration and generate migrations

**Files:**
- Modify: `apps/billing/models.py`
- Modify: `apps/billing/admin.py`
- Modify: `tests/billing/conftest.py`
- Modify: `tests/integrations/conftest.py`
- Modify: `tests/billing/test_membership_plan.py`
- Generate: `apps/core/migrations/0007_alter_auditevent_action.py`
- Generate: `apps/billing/migrations/0014_remove_membershipplan_sibling_discount_percent.py`

- [ ] **Step 1: Add red removal assertions and remove test fixture kwargs**

```python
def test_membership_plan_has_no_configurable_sibling_discount():
    from apps.billing.models import BillingRecord, MembershipPlan

    assert not hasattr(MembershipPlan, "sibling_discount_percent")
    assert hasattr(BillingRecord, "sibling_discount_percent_applied")
```

Remove `sibling_discount_percent=Decimal("50.00")` from both `active_plan` fixtures. Remove the former default-field assertion. Do not alter test fixtures that set `BillingRecord.sibling_discount_percent_applied`: that is the retained historical snapshot.

- [ ] **Step 2: Remove model/admin field**

Delete this model field only:

```python
sibling_discount_percent = models.DecimalField(
    max_digits=5, decimal_places=2, default=Decimal("0.00")
)
```

Remove only `"sibling_discount_percent"` from `MembershipPlanAdmin.list_display`. Retain `BillingRecordAdmin.sibling_discount_percent_applied` read-only display.

- [ ] **Step 3: Generate checked migrations**

```bash
uv run python manage.py makemigrations core billing
```

Expected exact files from current baseline:

```text
apps/core/migrations/0007_alter_auditevent_action.py
apps/billing/migrations/0014_remove_membershipplan_sibling_discount_percent.py
```

Both are schema/choice-only. Do not add a data migration: stored `BillingRecord` snapshots already preserve history.

- [ ] **Step 4: Sweep remaining removed-field references**

```bash
rg -n 'sibling_discount_percent' apps tests --glob '*.py'
```

Expected remaining matches only contain `sibling_discount_percent_applied` or historical migration files. Update no Invoice Ninja message test: it intentionally reads record snapshot percent.

- [ ] **Step 5: Run migration and focused suite**

```bash
uv run python manage.py makemigrations --check
uv run pytest tests/billing tests/integrations/test_invoice_ninja_provider.py tests/registrations/test_guardian_dedup.py -q
```

Expected: no pending migration and all focused tests pass.

### Task 7: Documentation and final verification

**Files:**
- Modify: `AGENTS.md`
- Verify: `docs/milestones.md`
- Verify: `docs/superpowers/specs/2026-07-15-p14-family-discount-tiers-design.md`
- Verify: `docs/superpowers/plans/2026-07-15-p14-family-discount-tiers.md`

- [ ] **Step 1: Update delivery status after code acceptance**

Add one concise P14 delivery entry to `AGENTS.md`: fixed 0/50/75/100 tiers, signed-time ordering, opt-out occupies rank, snapshot preservation, local zero-total records, override audit, and migration names. Include real final verification counts only after commands pass. Do not mark P15 delivered.

- [ ] **Step 2: Run full project gate**

```bash
uv run pytest -q
uv run ruff check .
uv run mypy .
uv run python manage.py makemigrations --check
```

Expected: every command passes. Do not commit unless user explicitly requests it.

---

## 5. Acceptance matrix

| Requirement | Proof |
|---|---|
| 1st/2nd/3rd/4th+ tiers | Parameterized signed-agreement record tests. |
| Signed-time then PK order | `compute_family_tier` order test. |
| Guardian and signing-season isolation | Separate guardian/season rank test. |
| P9 billing-only renewal | Current signed family ranks a later target-season record across seasons; no agreement created. |
| Opt-out | 0 applied %, full-price record, third child remains 75 %. |
| Discontinuation | Effective-date boundary, future inclusion, malformed discontinued row tests. |
| Snapshot stability | Recompute/reassign preserve stored percent; no rank rerun. |
| Concurrency design | `Guardian.objects.select_for_update()` spy test; PostgreSQL deploy semantics documented. |
| Zero invoice | No `BillingInvoice`; no provider helper/call; local synced status. |
| Override security | Reason required even €0; confirmed lock; audit omits free text. |
| Model cleanup | Field absent; two generated migrations; snapshot field retained. |
| Scope | No P15 calculations, parent UI, old-record repricing, or provider schema changes. |

## 6. Self-review

- **Spec coverage:** every approved P14 goal has one task and one direct test. P15 remains excluded.
- **Callers:** normal `create_draft_billing_for_member` passes `season_scoped=True`; P9 `renew_member_billing` passes `season_scoped=False`; legacy no-agreement callers remain full price.
- **State safety:** draft recompute/reassign use existing percent; confirmed records never mutate through those services or override form.
- **Concurrency:** existence check, rank calculation, and creation happen under same guardian lock.
- **PII/security:** audit stores amount changes only; no override reason text, personal ID, or provider payload enters metadata.
- **Migration correctness:** current heads are `core.0006` and `billing.0013`; expected P14 migration names are `0007` and `0014`.

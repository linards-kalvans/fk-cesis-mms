"""P14 — fixed family tier engine.

Tier map: 0→0%, 1→50%, 2→75%, 3+→100%.
Ranking: guardian's current signed Agreements (state=signed, is_current=True),
ordered signed_at ASC then member_id ASC. Normal path filters agreements by
billing_plan__season == plan.season. Excludes members with
discontinued_effective_date <= first_due_date; includes future effective dates;
defensively excludes status=DISCONTINUED when effective date is null.
"""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signed_agreement(member, plan, signed_at, *, is_current=True):
    """Create a signed Agreement for a member linked to a billing plan."""
    from apps.agreements.models import Agreement

    return Agreement.objects.create(
        member=member,
        is_current=is_current,
        state=Agreement.State.SIGNED,
        billing_plan=plan,
        signed_at=signed_at,
        generated_at=signed_at - datetime.timedelta(days=1),
    )


def _make_member_with_agreement(guardian, name, plan, signed_at):
    """Create a Member + signed Agreement for the plan. Returns (member, agreement)."""
    from apps.members.models import Member

    member = Member.objects.create(full_name=name, guardian=guardian)
    agreement = _make_signed_agreement(member, plan, signed_at)
    return member, agreement


def _first_due_date(plan):
    """Derive the first due date from a plan (season start + first month + due day)."""
    year = int(plan.season.split("/")[0])
    month = plan.first_installment_month
    day = min(plan.payment_due_day, 28)
    return datetime.date(year, month, day)


# ---------------------------------------------------------------------------
# compute_family_tier API — must exist, returns int (clamped to 3)
# ---------------------------------------------------------------------------


def test_compute_family_tier_exists():
    """P14: compute_family_tier must be importable from billing services."""
    from apps.billing.services import compute_family_tier  # noqa: F401


# ---------------------------------------------------------------------------
# Fixed tier map — tested through create_draft_billing_for_member
# ---------------------------------------------------------------------------


def test_rank_0_full_price(active_plan, guardian):
    """Single child (rank 0) pays full price — 0% discount, €300."""
    from apps.billing.services import create_draft_billing_for_member

    first, agreement = _make_member_with_agreement(
        guardian, "Jānis", active_plan, timezone.now()
    )
    rec = create_draft_billing_for_member(first, agreement)
    assert rec.sibling_discount_percent_applied == Decimal("0.00")
    assert rec.final_amount == Decimal("300.00")


def test_rank_1_fifty_percent(active_plan, guardian):
    """Second child (rank 1) gets 50% discount — €150."""
    from apps.billing.services import create_draft_billing_for_member

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    second, agreement = _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )
    rec = create_draft_billing_for_member(second, agreement)
    assert rec.sibling_discount_percent_applied == Decimal("50.00")
    assert rec.final_amount == Decimal("150.00")


def test_rank_2_seventyfive_percent(active_plan, guardian):
    """Third child (rank 2) gets 75% discount — €75."""
    from apps.billing.services import create_draft_billing_for_member

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )
    third, agreement = _make_member_with_agreement(
        guardian, "Trešais", active_plan, now + datetime.timedelta(hours=2)
    )
    rec = create_draft_billing_for_member(third, agreement)
    assert rec.sibling_discount_percent_applied == Decimal("75.00")
    assert rec.final_amount == Decimal("75.00")


def test_rank_3_hundred_percent(active_plan, guardian):
    """Fourth child (rank 3) gets 100% discount — €0."""
    from apps.billing.services import create_draft_billing_for_member

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )
    _make_member_with_agreement(
        guardian, "Trešais", active_plan, now + datetime.timedelta(hours=2)
    )
    fourth, agreement = _make_member_with_agreement(
        guardian, "Ceturtais", active_plan, now + datetime.timedelta(hours=3)
    )
    rec = create_draft_billing_for_member(fourth, agreement)
    assert rec.sibling_discount_percent_applied == Decimal("100.00")
    assert rec.final_amount == Decimal("0.00")


def test_rank_5_clamped_to_3(active_plan, guardian):
    """Sixth child (rank 5) still gets 100% discount — tier clamped to 3."""
    from apps.billing.services import create_draft_billing_for_member

    now = timezone.now()
    for i in range(5):
        _make_member_with_agreement(
            guardian, f"Bērns {i+1}", active_plan, now + datetime.timedelta(hours=i)
        )
    sixth, agreement = _make_member_with_agreement(
        guardian, "Sestais", active_plan, now + datetime.timedelta(hours=5)
    )
    rec = create_draft_billing_for_member(sixth, agreement)
    assert rec.sibling_discount_percent_applied == Decimal("100.00")
    assert rec.final_amount == Decimal("0.00")

    # P14: Direct tier API assertion — rank 5 clamped to 3.
    from apps.billing.services import compute_family_tier

    first_due = _first_due_date(active_plan)
    assert compute_family_tier(sixth, active_plan, first_due) == 3


# ---------------------------------------------------------------------------
# compute_family_tier returns int, clamped to 3
# ---------------------------------------------------------------------------


def test_compute_family_tier_returns_int_clamped(active_plan, guardian):
    """compute_family_tier returns int rank clamped to max 3."""
    from apps.billing.services import compute_family_tier

    now = timezone.now()
    first, _ = _make_member_with_agreement(guardian, "M1", active_plan, now)
    second, _ = _make_member_with_agreement(
        guardian, "M2", active_plan, now + datetime.timedelta(hours=1)
    )
    third, _ = _make_member_with_agreement(
        guardian, "M3", active_plan, now + datetime.timedelta(hours=2)
    )
    fourth, _ = _make_member_with_agreement(
        guardian, "M4", active_plan, now + datetime.timedelta(hours=3)
    )

    first_due = _first_due_date(active_plan)
    assert compute_family_tier(first, active_plan, first_due) == 0
    assert compute_family_tier(second, active_plan, first_due) == 1
    assert compute_family_tier(third, active_plan, first_due) == 2
    assert compute_family_tier(fourth, active_plan, first_due) == 3


# ---------------------------------------------------------------------------
# Signed ordering + pk tie-break
# ---------------------------------------------------------------------------


def test_signed_at_asc_ordering(active_plan, guardian):
    """Rank is determined by signed_at ASC, not member pk."""
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    # Create members in reverse pk order but sign them in forward order.
    later_member = Member.objects.create(full_name="Vēlākais", guardian=guardian)
    earlier_member = Member.objects.create(full_name="Agrākais", guardian=guardian)

    now = timezone.now()
    # Sign earlier_member FIRST (earlier signed_at).
    _make_signed_agreement(earlier_member, active_plan, now)
    _make_signed_agreement(later_member, active_plan, now + datetime.timedelta(hours=1))

    first_due = _first_due_date(active_plan)
    assert compute_family_tier(earlier_member, active_plan, first_due) == 0
    assert compute_family_tier(later_member, active_plan, first_due) == 1


def test_signed_at_tie_uses_member_id_asc(active_plan, guardian):
    """When signed_at is identical, lower member_id ranks first."""
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    first = Member.objects.create(full_name="Mazāks PK", guardian=guardian)
    second = Member.objects.create(full_name="Lielāks PK", guardian=guardian)

    now = timezone.now()
    _make_signed_agreement(first, active_plan, now)
    _make_signed_agreement(second, active_plan, now)  # same signed_at

    first_due = _first_due_date(active_plan)
    assert compute_family_tier(first, active_plan, first_due) == 0
    assert compute_family_tier(second, active_plan, first_due) == 1


# ---------------------------------------------------------------------------
# Guardian isolation
# ---------------------------------------------------------------------------


def test_guardian_isolation(active_plan, guardian):
    """Members of different guardians rank independently."""
    from apps.billing.services import compute_family_tier
    from tests.support import make_guardian

    other = make_guardian(full_name="Cits Vecāks", email="other@example.test")
    _make_member_with_agreement(other, "Svešais", active_plan, timezone.now())

    only_child, _ = _make_member_with_agreement(
        guardian, "Vienīgais", active_plan, timezone.now()
    )
    first_due = _first_due_date(active_plan)
    assert compute_family_tier(only_child, active_plan, first_due) == 0


# ---------------------------------------------------------------------------
# Season isolation (normal path)
# ---------------------------------------------------------------------------


def test_season_isolation_normal_path(db):
    """Normal path filters agreements by billing_plan__season == plan.season."""
    from apps.billing.models import MembershipPlan
    from apps.billing.services import compute_family_tier
    from tests.support import make_guardian

    plan_a = MembershipPlan.objects.create(
        name="Sezona A",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    plan_b = MembershipPlan.objects.create(
        name="Sezona B",
        season="2027/2028",
        annual_amount=Decimal("350.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    guardian = make_guardian(full_name="Test", email="season@example.test")

    # Member signed agreement in season A.
    _make_member_with_agreement(guardian, "A bērns", plan_a, timezone.now())

    # Create a new member with agreement in season B.
    b_member, _ = _make_member_with_agreement(
        guardian, "B bērns", plan_b, timezone.now()
    )

    first_due_b = _first_due_date(plan_b)
    # Season B only sees season B agreements — this member is rank 0 in B.
    assert compute_family_tier(b_member, plan_b, first_due_b) == 0


# ---------------------------------------------------------------------------
# Discontinuation exclusion
# ---------------------------------------------------------------------------


def test_discontinued_effective_past_excluded(active_plan, guardian):
    """Members with discontinued_effective_date <= first_due are excluded."""
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    now = timezone.now()
    first_due = _first_due_date(active_plan)

    # First member: discontinued in the past (before first_due).
    discontinued = Member.objects.create(
        full_name="Pārtraukts",
        guardian=guardian,
        discontinued_effective_date=first_due - datetime.timedelta(days=1),
    )
    _make_signed_agreement(discontinued, active_plan, now)

    # Second member: active.
    active = Member.objects.create(full_name="Aktīvs", guardian=guardian)
    _make_signed_agreement(active, active_plan, now + datetime.timedelta(hours=1))

    # Discontinued member excluded — active member is rank 0.
    assert compute_family_tier(active, active_plan, first_due) == 0


def test_discontinued_effective_exact_equality_excluded(active_plan, guardian):
    """P14: discontinued_effective_date == first_due is excluded (<=)."""
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    now = timezone.now()
    first_due = _first_due_date(active_plan)

    # First member: discontinued exactly on first_due (boundary case).
    discontinued = Member.objects.create(
        full_name="Precīzs",
        guardian=guardian,
        discontinued_effective_date=first_due,  # EXACT equality
    )
    _make_signed_agreement(discontinued, active_plan, now)

    # Second member: active.
    active = Member.objects.create(full_name="Aktīvs", guardian=guardian)
    _make_signed_agreement(active, active_plan, now + datetime.timedelta(hours=1))

    # Exact-equality boundary: excluded, so active member is rank 0.
    assert compute_family_tier(active, active_plan, first_due) == 0


def test_discontinued_effective_future_included(active_plan, guardian):
    """Members with discontinued_effective_date > first_due are included."""
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    now = timezone.now()
    first_due = _first_due_date(active_plan)

    # First member: discontinued in the future (after first_due).
    future_disc = Member.objects.create(
        full_name="Nākotne",
        guardian=guardian,
        discontinued_effective_date=first_due + datetime.timedelta(days=30),
    )
    _make_signed_agreement(future_disc, active_plan, now)

    # Second member: active.
    second = Member.objects.create(full_name="Otrais", guardian=guardian)
    _make_signed_agreement(second, active_plan, now + datetime.timedelta(hours=1))

    # Future-discontinued member still counted — second member is rank 1.
    assert compute_family_tier(second, active_plan, first_due) == 1


def test_discontinued_status_null_effective_excluded(active_plan, guardian):
    """Members with status=DISCONTINUED and null effective date are excluded."""
    from apps.billing.services import compute_family_tier
    from apps.members.models import Member

    now = timezone.now()
    first_due = _first_due_date(active_plan)

    # First member: status=DISCONTINUED, no effective date.
    disc_no_date = Member.objects.create(
        full_name="Bez datuma",
        guardian=guardian,
        status=Member.Status.DISCONTINUED,
        discontinued_effective_date=None,
    )
    _make_signed_agreement(disc_no_date, active_plan, now)

    # Second member: active.
    active = Member.objects.create(full_name="Aktīvs", guardian=guardian)
    _make_signed_agreement(active, active_plan, now + datetime.timedelta(hours=1))

    # Defensive exclusion — active member is rank 0.
    assert compute_family_tier(active, active_plan, first_due) == 0


# ---------------------------------------------------------------------------
# P9 renewal exception — cross-season ranking
# ---------------------------------------------------------------------------


def test_renewal_cross_season_ranking(db):
    """Renewal path ranks across plan seasons (season_scoped=False)."""
    from apps.billing.models import MembershipPlan
    from apps.billing.services import compute_family_tier, renew_member_billing
    from tests.support import make_guardian

    plan_old = MembershipPlan.objects.create(
        name="Vecā",
        season="2025/2026",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=False,
    )
    plan_new = MembershipPlan.objects.create(
        name="Jaunā",
        season="2026/2027",
        annual_amount=Decimal("350.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    guardian = make_guardian(full_name="Renewal", email="renew@example.test")

    # Member 1: signed agreement in old season.
    m1, _ = _make_member_with_agreement(guardian, "Vecais", plan_old, timezone.now())

    # Member 2: signed agreement in old season.
    m2, _ = _make_member_with_agreement(
        guardian, "Jaunais", plan_old, timezone.now() + datetime.timedelta(hours=1)
    )

    # Renew both members to new season (no new agreements created).
    renew_member_billing(m1, plan_new, first_billing_month="2026-09")
    renew_member_billing(m2, plan_new, first_billing_month="2026-09")

    first_due = _first_due_date(plan_new)
    # Cross-season: m2 is rank 1 (m1 counted from old season).
    assert compute_family_tier(m2, plan_new, first_due, season_scoped=False) == 1

    # Assert snapshot percent/final via created records.
    from apps.billing.models import BillingRecord

    rec1 = BillingRecord.objects.get(member=m1, season=plan_new.season)
    rec2 = BillingRecord.objects.get(member=m2, season=plan_new.season)
    assert rec1.sibling_discount_percent_applied == Decimal("0.00")
    assert rec1.final_amount == Decimal("350.00")
    assert rec2.sibling_discount_percent_applied == Decimal("50.00")
    assert rec2.final_amount == Decimal("175.00")

    # Assert no new Agreements were created.
    from apps.agreements.models import Agreement

    assert Agreement.objects.filter(member=m1, billing_plan=plan_new).count() == 0
    assert Agreement.objects.filter(member=m2, billing_plan=plan_new).count() == 0


def test_renewal_member_without_signed_agreement_full_price(db):
    """Renewal member without a current signed agreement is rank 0/full price."""
    from apps.billing.models import MembershipPlan
    from apps.billing.services import compute_family_tier, renew_member_billing
    from apps.members.models import Member
    from tests.support import make_guardian

    plan = MembershipPlan.objects.create(
        name="Sezona",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    guardian = make_guardian(full_name="No Agreement", email="noag@example.test")
    member = Member.objects.create(full_name="Bez līguma", guardian=guardian)
    # No signed agreement created.

    # Renew (creates draft record).
    renew_member_billing(member, plan, first_billing_month="2026-09")

    first_due = _first_due_date(plan)
    assert compute_family_tier(member, plan, first_due, season_scoped=False) == 0

    from apps.billing.models import BillingRecord

    rec = BillingRecord.objects.get(member=member, season=plan.season)
    assert rec.sibling_discount_percent_applied == Decimal("0.00")
    assert rec.final_amount == Decimal("300.00")


# ---------------------------------------------------------------------------
# Opt-out — tested through create_draft_billing_for_member
# ---------------------------------------------------------------------------


def test_opt_out_keeps_rank_but_forces_full_price(active_plan, guardian):
    """Opt-out member stores rank but is_full_price=True, discount=0, final=base."""
    from apps.billing.services import create_draft_billing_for_member
    from apps.registrations.models import RegistrationApplication

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)

    # Second member with opt-out.
    second, agreement = _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )
    RegistrationApplication.objects.create(
        approved_member=second,
        support_club_instead_of_multi_child_discount=True,
    )

    rec = create_draft_billing_for_member(second, agreement)
    assert rec.is_full_price is True
    assert rec.sibling_discount_percent_applied == Decimal("0.00")
    assert rec.discount_amount == Decimal("0.00")
    assert rec.final_amount == Decimal("300.00")
    assert rec.full_price_opt_out is True


def test_third_child_after_optout_second_gets_75(active_plan, guardian):
    """Third child after opt-out second gets 75% (rank 2) — €75."""
    from apps.billing.services import create_draft_billing_for_member
    from apps.registrations.models import RegistrationApplication

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)

    # Second member opts out.
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )
    RegistrationApplication.objects.create(
        approved_member=second,
        support_club_instead_of_multi_child_discount=True,
    )

    # Third member: rank 2, gets 75% discount.
    third, agreement = _make_member_with_agreement(
        guardian, "Trešais", active_plan, now + datetime.timedelta(hours=2)
    )

    rec = create_draft_billing_for_member(third, agreement)
    assert rec.is_full_price is False
    assert rec.sibling_discount_percent_applied == Decimal("75.00")
    assert rec.final_amount == Decimal("75.00")


# ---------------------------------------------------------------------------
# Snapshot preservation — recompute / reassign / manual override
# ---------------------------------------------------------------------------


def test_recompute_preserves_stored_percent(active_plan, guardian):
    """recompute_billing_record preserves stored sibling_discount_percent_applied."""
    from apps.billing.models import BillingRecord
    from apps.billing.services import recompute_billing_record

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )

    # Create draft for second member (rank 1, 50% discount).
    rec = BillingRecord.objects.create(
        member=second,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        is_full_price=False,
        sibling_discount_percent_applied=Decimal("50.00"),
        discount_amount=Decimal("150.00"),
        final_amount=Decimal("150.00"),
        status=BillingRecord.Status.DRAFT,
    )

    # Change plan amount.
    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()

    recompute_billing_record(rec)
    rec.refresh_from_db()

    # Stored percent preserved (50%), money recomputed using stored percent.
    assert rec.sibling_discount_percent_applied == Decimal("50.00")
    assert rec.base_amount == Decimal("400.00")
    assert rec.discount_amount == Decimal("200.00")  # 400 * 50%
    assert rec.final_amount == Decimal("200.00")


def test_reassign_preserves_stored_percent(guardian):
    """reassign_draft_billing_record preserves stored snapshot fields."""
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.billing.services import reassign_draft_billing_record

    plan_a = MembershipPlan.objects.create(
        name="A",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    plan_b = MembershipPlan.objects.create(
        name="B",
        season="2027/2028",
        annual_amount=Decimal("350.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", plan_a, now)
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", plan_a, now + datetime.timedelta(hours=1)
    )

    rec = BillingRecord.objects.create(
        member=second,
        plan=plan_a,
        season=plan_a.season,
        base_amount=plan_a.annual_amount,
        is_full_price=False,
        sibling_discount_percent_applied=Decimal("50.00"),
        discount_amount=Decimal("150.00"),
        final_amount=Decimal("150.00"),
        status=BillingRecord.Status.DRAFT,
    )

    reassign_draft_billing_record(rec, plan_b)
    rec.refresh_from_db()

    # Stored percent preserved.
    assert rec.sibling_discount_percent_applied == Decimal("50.00")
    assert rec.is_full_price is False
    assert rec.full_price_opt_out is False


def test_recompute_preserves_opt_out_flags(active_plan, guardian):
    """P14: recompute preserves is_full_price and full_price_opt_out for opt-out records."""
    from apps.billing.models import BillingRecord
    from apps.billing.services import recompute_billing_record
    from apps.registrations.models import RegistrationApplication

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )
    # Opt-out source application.
    RegistrationApplication.objects.create(
        approved_member=second,
        support_club_instead_of_multi_child_discount=True,
    )

    # Create draft with opt-out flags.
    rec = BillingRecord.objects.create(
        member=second,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        is_full_price=True,
        sibling_discount_percent_applied=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        final_amount=Decimal("300.00"),
        full_price_opt_out=True,
        status=BillingRecord.Status.DRAFT,
    )

    # Change plan amount.
    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()

    recompute_billing_record(rec)
    rec.refresh_from_db()

    # All opt-out flags preserved.
    assert rec.is_full_price is True
    assert rec.full_price_opt_out is True
    assert rec.sibling_discount_percent_applied == Decimal("0.00")
    # Natural final equals refreshed base (no discount).
    assert rec.base_amount == Decimal("400.00")
    assert rec.final_amount == Decimal("400.00")


def test_reassign_preserves_opt_out_flags(guardian):
    """P14: reassign preserves is_full_price and full_price_opt_out for opt-out records."""
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.billing.services import reassign_draft_billing_record
    from apps.registrations.models import RegistrationApplication

    plan_a = MembershipPlan.objects.create(
        name="A",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    plan_b = MembershipPlan.objects.create(
        name="B",
        season="2027/2028",
        annual_amount=Decimal("350.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", plan_a, now)
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", plan_a, now + datetime.timedelta(hours=1)
    )
    # Opt-out source application.
    RegistrationApplication.objects.create(
        approved_member=second,
        support_club_instead_of_multi_child_discount=True,
    )

    rec = BillingRecord.objects.create(
        member=second,
        plan=plan_a,
        season=plan_a.season,
        base_amount=plan_a.annual_amount,
        is_full_price=True,
        sibling_discount_percent_applied=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        final_amount=Decimal("300.00"),
        full_price_opt_out=True,
        status=BillingRecord.Status.DRAFT,
    )

    reassign_draft_billing_record(rec, plan_b)
    rec.refresh_from_db()

    # All opt-out flags preserved.
    assert rec.is_full_price is True
    assert rec.full_price_opt_out is True
    assert rec.sibling_discount_percent_applied == Decimal("0.00")


def test_reassign_with_manual_override_preserves_final(guardian):
    """P14: reassign with manual override preserves final_amount and snapshot fields."""
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.billing.services import reassign_draft_billing_record

    plan_a = MembershipPlan.objects.create(
        name="A",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )
    plan_b = MembershipPlan.objects.create(
        name="B",
        season="2027/2028",
        annual_amount=Decimal("350.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", plan_a, now)
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", plan_a, now + datetime.timedelta(hours=1)
    )

    rec = BillingRecord.objects.create(
        member=second,
        plan=plan_a,
        season=plan_a.season,
        base_amount=plan_a.annual_amount,
        is_full_price=False,
        sibling_discount_percent_applied=Decimal("50.00"),
        discount_amount=Decimal("150.00"),
        final_amount=Decimal("150.00"),
        manual_amount_override=Decimal("123.00"),  # Manual override.
        status=BillingRecord.Status.DRAFT,
    )

    reassign_draft_billing_record(rec, plan_b)
    rec.refresh_from_db()

    # Final remains override (123.00), not natural (175.00).
    assert rec.final_amount == Decimal("123.00")
    # Snapshot fields preserved.
    assert rec.sibling_discount_percent_applied == Decimal("50.00")
    assert rec.is_full_price is False
    assert rec.full_price_opt_out is False


def test_manual_override_wins(active_plan, guardian):
    """Manual override wins over natural final_amount."""
    from apps.billing.models import BillingRecord
    from apps.billing.services import recompute_billing_record

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    second, _ = _make_member_with_agreement(
        guardian, "Otrais", active_plan, now + datetime.timedelta(hours=1)
    )

    rec = BillingRecord.objects.create(
        member=second,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        is_full_price=False,
        sibling_discount_percent_applied=Decimal("50.00"),
        discount_amount=Decimal("150.00"),
        final_amount=Decimal("150.00"),
        manual_amount_override=Decimal("100.00"),
        status=BillingRecord.Status.DRAFT,
    )

    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()

    recompute_billing_record(rec)
    rec.refresh_from_db()

    # Manual override wins.
    assert rec.final_amount == Decimal("100.00")


# ---------------------------------------------------------------------------
# Concurrency — select_for_update spy
# ---------------------------------------------------------------------------


def test_create_draft_calls_select_for_update(active_plan, guardian, monkeypatch):
    """create_draft_billing_for_member calls Guardian.objects.select_for_update."""
    from apps.billing.services import create_draft_billing_for_member
    from apps.members.models import Guardian

    called = []
    original_select_for_update = Guardian.objects.select_for_update

    def spy_select_for_update(*args, **kwargs):
        called.append(True)
        return original_select_for_update(*args, **kwargs)

    monkeypatch.setattr(Guardian.objects, "select_for_update", spy_select_for_update)

    member, agreement = _make_member_with_agreement(
        guardian, "Jānis", active_plan, timezone.now()
    )
    create_draft_billing_for_member(member, agreement)

    assert called, "select_for_update must be called during draft creation"


def test_renew_member_billing_calls_select_for_update(active_plan, guardian, monkeypatch):
    """renew_member_billing calls Guardian.objects.select_for_update."""
    from apps.billing.services import renew_member_billing
    from apps.members.models import Guardian

    called = []
    original_select_for_update = Guardian.objects.select_for_update

    def spy_select_for_update(*args, **kwargs):
        called.append(True)
        return original_select_for_update(*args, **kwargs)

    monkeypatch.setattr(Guardian.objects, "select_for_update", spy_select_for_update)

    member, _ = _make_member_with_agreement(guardian, "Jānis", active_plan, timezone.now())
    renew_member_billing(member, active_plan)

    assert called, "select_for_update must be called during renewal"


# ---------------------------------------------------------------------------
# Legacy fallback — create_draft_billing_for_member(member, agreement=None)
# ---------------------------------------------------------------------------


def test_legacy_create_draft_full_price(active_plan, guardian):
    """Legacy create_draft_billing_for_member(member, agreement=None) is full price."""
    from apps.billing.services import create_draft_billing_for_member
    from apps.members.models import Member

    now = timezone.now()
    _make_member_with_agreement(guardian, "Pirmais", active_plan, now)
    second = Member.objects.create(full_name="Otrais", guardian=guardian)
    _make_signed_agreement(second, active_plan, now + datetime.timedelta(hours=1))

    # Deliberately pass agreement=None — legacy fallback.
    rec = create_draft_billing_for_member(second, agreement=None)
    assert rec.is_full_price is True
    assert rec.sibling_discount_percent_applied == Decimal("0.00")
    assert rec.final_amount == Decimal("300.00")

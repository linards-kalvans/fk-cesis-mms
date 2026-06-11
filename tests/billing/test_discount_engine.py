import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _make_member(guardian, name, opt_out=None):
    """Create a Member with a source application carrying the opt-out flag."""
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        approved_member=member,
        support_club_instead_of_multi_child_discount=opt_out,
    )
    return member


def test_single_child_full_price(active_plan, guardian):
    from apps.billing.services import compute_billing_amounts

    m = _make_member(guardian, "Jānis")
    amounts = compute_billing_amounts(m, active_plan)
    assert amounts.is_full_price is True
    assert amounts.base_amount == Decimal("300.00")
    assert amounts.discount_amount == Decimal("0.00")
    assert amounts.final_amount == Decimal("300.00")


def test_second_child_discounted(active_plan, guardian):
    from apps.billing.services import compute_billing_amounts

    first = _make_member(guardian, "Jānis")
    second = _make_member(guardian, "Anna")
    a_first = compute_billing_amounts(first, active_plan)
    a_second = compute_billing_amounts(second, active_plan)
    assert a_first.is_full_price is True
    assert a_first.final_amount == Decimal("300.00")
    assert a_second.is_full_price is False
    assert a_second.discount_percent_applied == Decimal("50.00")
    assert a_second.discount_amount == Decimal("150.00")
    assert a_second.final_amount == Decimal("150.00")


def test_opt_out_forces_full_price_on_second_child(active_plan, guardian):
    from apps.billing.services import compute_billing_amounts

    _make_member(guardian, "Jānis")
    second = _make_member(guardian, "Anna", opt_out=True)
    a = compute_billing_amounts(second, active_plan)
    assert a.is_full_price is True
    assert a.final_amount == Decimal("300.00")


def test_other_guardian_members_excluded(active_plan, guardian):
    from apps.billing.services import compute_billing_amounts
    from apps.members.models import Guardian

    other = Guardian.objects.create(full_name="Cits Vecāks", email="c@example.com")
    _make_member(other, "Sveši bērns")  # earlier pk, different guardian
    only_child = _make_member(guardian, "Vienīgais")
    a = compute_billing_amounts(only_child, active_plan)
    assert a.is_full_price is True  # first for THIS guardian


def test_rounding_to_cents(guardian):
    from apps.billing.models import MembershipPlan
    from apps.billing.services import compute_billing_amounts

    plan = MembershipPlan.objects.create(
        name="Odd", season="2026/2027",
        annual_amount=Decimal("301.00"),
        sibling_discount_percent=Decimal("33.33"),
        installment_count=1, first_installment_month=9, is_active=True,
    )
    _make_member(guardian, "Pirmais")
    second = _make_member(guardian, "Otrais")
    a = compute_billing_amounts(second, plan)
    # 301.00 * 33.33% = 100.3233 -> 100.32 ; final 200.68
    assert a.discount_amount == Decimal("100.32")
    assert a.final_amount == Decimal("200.68")

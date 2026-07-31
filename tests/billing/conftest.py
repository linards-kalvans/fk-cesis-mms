from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture
def active_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    g = make_guardian(full_name="Anna Bērziņa", email="anna@example.com")
    return g


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(full_name="Jānis Bērziņš", guardian=guardian)


@pytest.fixture
def billing_record(db, member, active_plan):
    """A confirmed BillingRecord for the test member + active plan."""
    from apps.billing.models import BillingRecord

    return BillingRecord.objects.create(
        member=member,
        plan=active_plan,
        season=active_plan.season,
        base_amount=active_plan.annual_amount,
        final_amount=active_plan.annual_amount,
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.CONFIRMED,
    )


@pytest.fixture
def billing_invoice(db, billing_record):
    """An unsent, unpaid BillingInvoice for the billing_record fixture."""
    from apps.billing.models import BillingInvoice

    return BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=0,
        due_date="2026-09-20",
        amount=billing_record.final_amount,
    )


@pytest.fixture
def billing_record_factory(db, active_plan):
    """Factory: create a confirmed BillingRecord for any given member."""
    from apps.billing.models import BillingRecord

    def _make(member):
        return BillingRecord.objects.create(
            member=member,
            plan=active_plan,
            season=active_plan.season,
            base_amount=active_plan.annual_amount,
            final_amount=active_plan.annual_amount,
            payment_mode=BillingRecord.PaymentMode.UPFRONT,
            status=BillingRecord.Status.CONFIRMED,
        )

    return _make

import pytest
from decimal import Decimal


@pytest.fixture
def active_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="Sezona 2026/2027",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        sibling_discount_percent=Decimal("50.00"),
        installment_count=10,
        first_installment_month=9,
        is_active=True,
    )


@pytest.fixture
def guardian(db):
    from tests.support import make_guardian

    g = make_guardian(full_name="Anna Bērziņa", email="anna@example.com")
    # Mirror onto the Guardian column so today's column-reading code paths
    # (e.g. send_due_invoices' guardian.email check) still see the address.
    g.email = "anna@example.com"
    g.save(update_fields=["email"])
    return g


@pytest.fixture
def member(db, guardian):
    from apps.members.models import Member

    return Member.objects.create(full_name="Jānis Bērziņš", guardian=guardian)

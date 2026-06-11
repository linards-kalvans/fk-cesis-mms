import pytest

pytestmark = pytest.mark.django_db


def test_billing_summary_copy(active_plan, guardian):
    from apps.billing.presentation import billing_summary_line
    from apps.billing.services import create_draft_billing_for_member
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    RegistrationApplication.objects.create(
        approved_member=member,
        preferred_payment_mode="upfront",
    )
    rec = create_draft_billing_for_member(member, agreement=None)
    line = billing_summary_line(rec)
    assert "300.00" in line
    assert "EUR" in line

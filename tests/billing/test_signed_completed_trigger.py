import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_electronic_agreement_signed_completes_and_triggers_billing(active_plan, guardian):
    """An electronic agreement reaching SIGNED (the 'completed' final state)
    auto-creates a DRAFT BillingRecord via the agreement_signed signal.
    This is the P6 #1-2 'billing starts after completed' guarantee."""
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_signed
    from apps.billing.models import BillingRecord
    from django.utils import timezone

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    RegistrationApplication.objects.create(
        approved_member=member,
        preferred_agreement_signing="electronic",
    )
    agreement = Agreement.objects.create(
        member=member,
        generated_at=timezone.now(),
        signing_path="electronic",
        billing_plan=active_plan,
        first_billing_month="2026-09",
    )

    assert not BillingRecord.objects.filter(member=member).exists()

    mark_agreement_signed(agreement, actor=None)

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SIGNED  # "completed" final state
    rec = BillingRecord.objects.get(member=member)
    assert rec.status == BillingRecord.Status.DRAFT
    assert rec.final_amount == Decimal("300.00")

import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _member_with_app(guardian, name, payment_mode="installments"):
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        approved_member=member,
        preferred_payment_mode=payment_mode,
    )
    return member


def test_signing_creates_draft_billing(active_plan, guardian):
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_signed
    from apps.billing.models import BillingRecord
    from django.utils import timezone

    member = _member_with_app(guardian, "Jānis")
    agreement = Agreement.objects.create(
        member=member,
        generated_at=timezone.now(),
        billing_plan=active_plan,
        first_billing_month="2026-09",
    )
    mark_agreement_signed(agreement, actor=None)

    rec = BillingRecord.objects.get(member=member)
    assert rec.status == BillingRecord.Status.DRAFT
    assert rec.agreement_id == agreement.pk
    # P15: calendar-year partial base for first_billing_month='2026-09'
    # with default skip_months='7,12' → 3 billable months (Sep/Oct/Nov),
    # base = €300 * 3 / 10 = €90.00.
    assert rec.scheduled_installment_count == 3
    assert rec.final_amount == Decimal("90.00")


def test_signing_without_billing_plan_raises_and_creates_no_record(db, guardian):
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_signed
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from django.utils import timezone

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    agreement = Agreement.objects.create(
        member=member,
        generated_at=timezone.now(),
        billing_plan=None,
        first_billing_month="",
    )
    # P9 signing guard: must raise, must not create a billing record, must
    # not flip the agreement to signed.
    with pytest.raises(ValueError, match="billing plan required"):
        mark_agreement_signed(agreement, actor=None)
    assert BillingRecord.objects.count() == 0
    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.GENERATED

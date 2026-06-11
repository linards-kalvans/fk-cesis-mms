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
    agreement = Agreement.objects.create(member=member, generated_at=timezone.now())
    mark_agreement_signed(agreement, actor=None)

    rec = BillingRecord.objects.get(member=member)
    assert rec.status == BillingRecord.Status.DRAFT
    assert rec.agreement_id == agreement.pk
    assert rec.final_amount == Decimal("300.00")


def test_signing_without_active_plan_does_not_break(db, guardian):
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_signed
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from django.utils import timezone

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    agreement = Agreement.objects.create(member=member, generated_at=timezone.now())
    # Must not raise even though no active plan exists.
    mark_agreement_signed(agreement, actor=None)
    assert BillingRecord.objects.count() == 0

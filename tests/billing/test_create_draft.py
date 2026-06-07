import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _member_with_app(guardian, name, payment_mode="installments", opt_out=None):
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        guardian_email=guardian.email,
        approved_member=member,
        preferred_payment_mode=payment_mode,
        support_club_instead_of_multi_child_discount=opt_out,
    )
    return member


def test_creates_draft_snapshot(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member
    from apps.billing.models import BillingRecord

    member = _member_with_app(guardian, "Jānis", payment_mode="upfront")
    rec = create_draft_billing_for_member(member, agreement=None)
    assert rec is not None
    assert rec.status == BillingRecord.Status.DRAFT
    assert rec.season == "2026/2027"
    assert rec.base_amount == Decimal("300.00")
    assert rec.final_amount == Decimal("300.00")
    assert rec.payment_mode == "upfront"
    assert rec.full_price_opt_out is False


def test_idempotent_on_second_call(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member
    from apps.billing.models import BillingRecord

    member = _member_with_app(guardian, "Jānis")
    create_draft_billing_for_member(member, agreement=None)
    create_draft_billing_for_member(member, agreement=None)
    assert BillingRecord.objects.filter(member=member).count() == 1


def test_no_active_plan_noops(db, guardian, caplog):
    from apps.billing.services import create_draft_billing_for_member
    from apps.billing.models import BillingRecord
    from apps.members.models import Member

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    result = create_draft_billing_for_member(member, agreement=None)
    assert result is None
    assert BillingRecord.objects.count() == 0


def test_existing_draft_left_untouched(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    rec.manual_amount_override = Decimal("123.00")
    rec.save()
    create_draft_billing_for_member(member, agreement=None)
    rec.refresh_from_db()
    assert rec.manual_amount_override == Decimal("123.00")

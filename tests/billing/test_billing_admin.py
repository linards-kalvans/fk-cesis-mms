import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _member_with_app(guardian, name):
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        guardian_email=guardian.email, approved_member=member,
    )
    return member


def test_recompute_updates_draft_after_plan_edit(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member, recompute_billing_record

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    assert rec.final_amount == Decimal("300.00")

    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()
    recompute_billing_record(rec)
    rec.refresh_from_db()
    assert rec.base_amount == Decimal("400.00")
    assert rec.final_amount == Decimal("400.00")


def test_recompute_skips_confirmed(active_plan, guardian):
    from apps.billing.models import BillingRecord
    from apps.billing.services import create_draft_billing_for_member, recompute_billing_record

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save()
    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()
    recompute_billing_record(rec)
    rec.refresh_from_db()
    assert rec.base_amount == Decimal("300.00")  # untouched


def test_recompute_preserves_manual_override(active_plan, guardian):
    from apps.billing.services import create_draft_billing_for_member, recompute_billing_record

    member = _member_with_app(guardian, "Jānis")
    rec = create_draft_billing_for_member(member, agreement=None)
    rec.manual_amount_override = Decimal("250.00")
    rec.save()

    active_plan.annual_amount = Decimal("400.00")
    active_plan.save()
    recompute_billing_record(rec)
    rec.refresh_from_db()
    # Natural amounts re-derive from the plan, but final_amount honors the override.
    assert rec.base_amount == Decimal("400.00")
    assert rec.final_amount == Decimal("250.00")


def test_admin_registered():
    from django.contrib import admin
    from apps.billing.models import BillingRecord, MembershipPlan

    assert admin.site.is_registered(BillingRecord)
    assert admin.site.is_registered(MembershipPlan)

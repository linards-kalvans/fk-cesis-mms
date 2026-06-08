import pytest
from io import StringIO
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _signed_member(guardian, name):
    from apps.members.models import Member
    from apps.registrations.models import RegistrationApplication
    from apps.agreements.models import Agreement
    from django.utils import timezone

    member = Member.objects.create(full_name=name, guardian=guardian)
    RegistrationApplication.objects.create(
        guardian_email=guardian.email, approved_member=member,
    )
    Agreement.objects.create(
        member=member, generated_at=timezone.now(),
        state=Agreement.State.SIGNED, signed_at=timezone.now(),
    )
    return member


def test_backfill_creates_missing_records(active_plan, guardian):
    from apps.billing.models import BillingRecord

    member = _signed_member(guardian, "Jānis")
    assert BillingRecord.objects.count() == 0
    call_command("backfill_billing", stdout=StringIO())
    assert BillingRecord.objects.filter(member=member).count() == 1


def test_backfill_is_idempotent(active_plan, guardian):
    from apps.billing.models import BillingRecord

    _signed_member(guardian, "Jānis")
    call_command("backfill_billing", stdout=StringIO())
    call_command("backfill_billing", stdout=StringIO())
    assert BillingRecord.objects.count() == 1


def test_backfill_noop_without_active_plan(db, guardian):
    from apps.billing.models import BillingRecord

    _signed_member(guardian, "Jānis")
    call_command("backfill_billing", stdout=StringIO())
    assert BillingRecord.objects.count() == 0


def test_backfill_reports_honest_created_count(active_plan, guardian):
    member = _signed_member(guardian, "Jānis")  # noqa: F841

    out = StringIO()
    call_command("backfill_billing", stdout=out)
    assert "1 created" in out.getvalue()

    out2 = StringIO()
    call_command("backfill_billing", stdout=out2)
    assert "0 created" in out2.getvalue()

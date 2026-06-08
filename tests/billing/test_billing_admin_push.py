import pytest
from decimal import Decimal
from unittest.mock import patch

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, status):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=status,
    )


def test_action_enqueues_only_confirmed(active_plan, guardian):
    from django.contrib.admin.sites import AdminSite
    from apps.billing.admin import BillingRecordAdmin
    from apps.billing.models import BillingRecord

    confirmed = _record(active_plan, guardian, BillingRecord.Status.CONFIRMED)
    draft = _record(active_plan, guardian, BillingRecord.Status.DRAFT)

    admin = BillingRecordAdmin(BillingRecord, AdminSite())
    request = type("R", (), {})()
    with patch("apps.integrations.tasks.enqueue_push_billing_record") as enqueue, \
         patch.object(admin, "message_user"):
        admin.push_to_invoice_ninja(request, BillingRecord.objects.all())

    called_ids = {c.args[0] for c in enqueue.call_args_list}
    assert called_ids == {confirmed.pk}

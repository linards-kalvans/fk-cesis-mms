import pytest
from decimal import Decimal
from datetime import date
from unittest.mock import patch

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _confirmed_record(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1),
        amount=Decimal("30.00"), external_invoice_id="inv-1",
    )
    return rec


def test_sync_payments_action_enqueues_confirmed(active_plan, guardian, staff_client):
    from django.urls import reverse

    rec = _confirmed_record(active_plan, guardian)
    url = reverse("admin:billing_billingrecord_changelist")
    with patch(
        "apps.integrations.tasks.enqueue_sync_billing_record_payments"
    ) as enq:
        resp = staff_client.post(
            url,
            {"action": "sync_payments", "_selected_action": [str(rec.pk)]},
            follow=True,
        )
    assert resp.status_code == 200
    enq.assert_called_once_with(rec.pk)


def test_sync_payments_action_skips_draft(active_plan, guardian, staff_client):
    from django.urls import reverse
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Anna", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.DRAFT,
    )
    url = reverse("admin:billing_billingrecord_changelist")
    with patch(
        "apps.integrations.tasks.enqueue_sync_billing_record_payments"
    ) as enq:
        staff_client.post(
            url,
            {"action": "sync_payments", "_selected_action": [str(rec.pk)]},
            follow=True,
        )
    enq.assert_not_called()


def test_changelist_shows_payment_status_column(active_plan, guardian, staff_client):
    from django.urls import reverse

    _confirmed_record(active_plan, guardian)
    url = reverse("admin:billing_billingrecord_changelist")
    resp = staff_client.get(url)
    assert resp.status_code == 200
    # Django renders the column as a `column-payment_status` <th>, so this
    # asserts the column is actually present (not just the action label copy).
    assert b"column-payment_status" in resp.content

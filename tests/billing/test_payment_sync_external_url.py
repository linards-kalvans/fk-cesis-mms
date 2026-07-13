"""P12: _sync_invoice_payment saves external_url from provider; preserves
existing non-empty URL when provider returns empty."""

import pytest
from datetime import date
from decimal import Decimal

from apps.integrations.invoice_platform import PaymentResult

pytestmark = pytest.mark.django_db


def _make_invoice(active_plan, guardian, *, external_id="inv-1", external_url=""):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    return BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1),
        amount=Decimal("30.00"), external_invoice_id=external_id,
        external_url=external_url,
    )


def _payment(*, external_url=""):
    return PaymentResult(
        external_invoice_id="inv-1",
        payment_status="unpaid",
        amount=Decimal("30.00"),
        paid_to_date=Decimal("0.00"),
        balance=Decimal("30.00"),
        last_payment_date=None,
        external_url=external_url,
    )


def test_sync_saves_non_empty_external_url(active_plan, guardian):
    from unittest.mock import patch
    from apps.integrations.tasks import _sync_invoice_payment

    inv = _make_invoice(active_plan, guardian, external_id="inv-1")
    assert inv.external_url == ""
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(external_url="https://in.example.com/view/xyz"),
    ):
        _sync_invoice_payment(inv)
    inv.refresh_from_db()
    assert inv.external_url == "https://in.example.com/view/xyz"


def test_sync_preserves_existing_external_url_when_provider_empty(active_plan, guardian):
    from unittest.mock import patch
    from apps.integrations.tasks import _sync_invoice_payment

    inv = _make_invoice(
        active_plan, guardian,
        external_id="inv-1",
        external_url="https://in.example.com/view/already",
    )
    with patch(
        "apps.integrations.invoice_platform.fetch_invoice_payment",
        return_value=_payment(external_url=""),
    ):
        _sync_invoice_payment(inv)
    inv.refresh_from_db()
    assert inv.external_url == "https://in.example.com/view/already"

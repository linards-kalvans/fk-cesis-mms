"""P12: BillingInvoice.external_url field — default blank."""

import pytest
from datetime import date
from decimal import Decimal

pytestmark = pytest.mark.django_db


def test_external_url_defaults_to_blank(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    bi = BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1),
        amount=Decimal("30.00"),
    )
    assert bi.external_url == ""


def test_external_url_accepts_url(active_plan, guardian):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
    )
    bi = BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=date(2026, 9, 1),
        amount=Decimal("30.00"),
        external_url="https://example.com/invoices/123",
    )
    bi.refresh_from_db()
    assert bi.external_url == "https://example.com/invoices/123"

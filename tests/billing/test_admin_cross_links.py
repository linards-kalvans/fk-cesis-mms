"""Cross-links on the billing admin (changelist columns + change page row)."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.billing.models import BillingRecord
from apps.members.models import Member

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _record(active_plan, guardian, agreement=None):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, agreement=agreement,
    )


def test_changelist_links_to_guardian_and_agreement(active_plan, guardian):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, agreement=agreement,
    )
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    assert f"/members/guardian/{guardian.pk}/change/" in html
    assert f"/agreements/agreement/{agreement.pk}/change/" in html


def test_change_page_shows_related_records_row(active_plan, guardian):
    m = Member.objects.create(full_name="Bērns", guardian=guardian)
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT, generated_at=timezone.now()
    )
    rec = BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
        status=BillingRecord.Status.DRAFT, agreement=agreement,
    )
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_change", args=[rec.pk])).content.decode()
    assert "Saistītie ieraksti" in html
    assert f"/members/member/{m.pk}/change/" in html
    assert f"/members/guardian/{guardian.pk}/change/" in html
    assert f"/agreements/agreement/{agreement.pk}/change/" in html  # agreement branch


def test_billing_record_admin_disallows_add():
    # Records are created by the billing service; the admin add form is disabled
    # (it would otherwise crash on obj.member in related_records).
    c = _staff_client()
    resp = c.get(reverse("admin:billing_billingrecord_add"))
    assert resp.status_code == 403

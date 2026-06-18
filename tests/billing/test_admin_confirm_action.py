"""One-click confirm for billing records (change page + changelist)."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from apps.billing.models import BillingRecord
from apps.members.models import Member

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _draft_record(active_plan, guardian):
    m = Member.objects.create(full_name="B", guardian=guardian)
    return BillingRecord.objects.create(
        member=m, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        payment_mode=BillingRecord.PaymentMode.UPFRONT, status=BillingRecord.Status.DRAFT,
    )


def test_confirm_endpoint_flips_draft_to_confirmed(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    original_updated_at = rec.updated_at
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    resp = c.post(url)
    assert resp.status_code == 302
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.CONFIRMED
    # update_fields includes updated_at, so auto_now must still bump it.
    assert rec.updated_at > original_updated_at


def test_confirm_is_noop_when_already_confirmed(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    rec.status = BillingRecord.Status.CONFIRMED
    rec.save(update_fields=["status"])
    c = _staff_client()
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    c.post(url, follow=True)
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.CONFIRMED  # unchanged, no error


def test_confirm_is_staff_permission_gated(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = Client()  # anonymous
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    resp = c.post(url)
    assert resp.status_code in (302, 403)
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.DRAFT


def test_confirm_rejected_for_staff_without_change_permission(active_plan, guardian):
    # Authenticated staff (passes admin_view's is_staff gate) but lacking the
    # billingrecord change permission must be rejected by has_change_permission.
    rec = _draft_record(active_plan, guardian)
    User.objects.create_user("viewonly", "v@example.com", "pw", is_staff=True)
    c = Client()
    c.login(username="viewonly", password="pw")
    url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    resp = c.post(url)
    assert resp.status_code == 403
    rec.refresh_from_db()
    assert rec.status == BillingRecord.Status.DRAFT


def test_change_page_shows_confirm_button_for_draft(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_change", args=[rec.pk])).content.decode()
    confirm_url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    assert confirm_url in html
    assert "Apstiprināt" in html


def test_changelist_shows_one_click_confirm_for_draft(active_plan, guardian):
    rec = _draft_record(active_plan, guardian)
    c = _staff_client()
    html = c.get(reverse("admin:billing_billingrecord_changelist")).content.decode()
    confirm_url = reverse("admin:billing_billingrecord_confirm", args=[rec.pk])
    # A bare formaction button (NOT a nested <form>, which the browser would drop):
    # it rides the changelist's own POST form + CSRF.
    assert f'formaction="{confirm_url}?next=' in html
    assert 'formmethod="post"' in html
    # the old per-row nested <form action="…confirm/"> must be gone
    assert f'<form method="post" action="{confirm_url}"' not in html

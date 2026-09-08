"""Outstanding invoices page."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.admin_hub.invoices import BULK_CONFIRM_THRESHOLD

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


@pytest.fixture
def unpaid_invoice(approved_application, default_plan):
    from apps.billing.models import BillingInvoice, BillingRecord

    record = BillingRecord.objects.create(
        member=approved_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    return BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 7, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-77",
        external_status="sent",
        payment_status="unpaid",
        balance=Decimal("30.00"),
    )


def test_invoices_page_requires_staff(client):
    response = client.get(reverse("admin_hub:invoices"))
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_invoices_page_lists_an_unpaid_invoice(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices")).content.decode()
    assert "Neapmaksātie rēķini" in body
    assert unpaid_invoice.billing_record.member.full_name in body


def test_invoices_page_shows_the_outstanding_total(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices")).content.decode()
    assert "Atlikums kopā" in body
    # A bare "30.00" in body is not enough: the per-row Summa/Atlikums
    # columns show the same figure regardless of whether invoice_totals()
    # aggregates correctly, so that substring appears even when the stat
    # card itself is wrong (verified: forcing outstanding to 0.00 still left
    # a bare "30.00" check green). Pin the value to the stat card's own
    # markup instead, so a broken aggregation actually fails this test.
    assert (
        '<div class="stat__value">30.00</div>'
        '<div class="stat__label">Atlikums kopā (EUR)</div>'
    ) in body


def test_overdue_invoice_is_flagged(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices"), {"tab": "kaveti"}).content.decode()
    assert "is-overdue" in body


def test_invoices_page_has_no_reminder_action(client, reviewer, unpaid_invoice):
    """Reminder e-mails were explicitly ruled out of scope."""
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices")).content.decode()
    assert "atgādin" not in body.lower()


def test_unknown_tab_falls_back_to_the_default(client, reviewer, unpaid_invoice):
    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:invoices"), {"tab": "nonsense"})
    assert response.status_code == 200
    # A 200 alone would also be produced by a view that swallowed the bad tab
    # and rendered any arbitrary tab (or none) as active - confirm the
    # fallback specifically lands on the default tab's own nav link.
    body = response.content.decode()
    assert '<a href="?tab=neapmaksati" class="is-active">' in body


def test_bulk_confirm_page_reports_the_selection_size(client, reviewer):
    client.force_login(reviewer)
    ids = ",".join(str(n) for n in range(BULK_CONFIRM_THRESHOLD + 1))
    response = client.get(
        reverse("admin_hub:bulk_confirm"),
        {"ids": ids, "op": "push"},
    )
    assert response.status_code == 200
    body = response.content.decode()
    assert str(BULK_CONFIRM_THRESHOLD + 1) in body
    assert "Apstiprināt" in body


def test_bulk_confirm_states_the_batch_cap(client, reviewer):
    client.force_login(reviewer)
    ids = ",".join(str(n) for n in range(BULK_CONFIRM_THRESHOLD + 1))
    body = client.get(
        reverse("admin_hub:bulk_confirm"), {"ids": ids, "op": "push"}
    ).content.decode()
    assert str(BULK_CONFIRM_THRESHOLD) in body


def test_bulk_confirm_rejects_a_non_numeric_id_list(client, reviewer):
    client.force_login(reviewer)
    response = client.get(
        reverse("admin_hub:bulk_confirm"), {"ids": "1,2,../etc", "op": "push"}
    )
    assert response.status_code == 400

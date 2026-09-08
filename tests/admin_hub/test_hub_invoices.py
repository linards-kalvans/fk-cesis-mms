"""Outstanding invoices page."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

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


@pytest.fixture
def paid_overdue_invoice(approved_application, default_plan):
    """A fully paid invoice whose due date is in the past. Must never render
    as overdue - only the payment_status/date combination together decide
    that, never the date alone."""
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
        external_invoice_id="IN-88",
        external_status="paid",
        payment_status="paid",
        paid_to_date=Decimal("30.00"),
        balance=Decimal("0.00"),
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


def test_paid_invoice_past_due_date_is_not_flagged_as_overdue(
    client, reviewer, paid_overdue_invoice
):
    """kaveti and overdue_count both require payment_status != PAID as well
    as a past due date. The visi tab shows paid invoices too, so it must
    apply the exact same rule - not just the date half of it - or a paid
    invoice with an old due date renders as "kavēts"."""
    client.force_login(reviewer)
    body = client.get(reverse("admin_hub:invoices"), {"tab": "visi"}).content.decode()
    # Assert the row is actually on screen first: without this, a regression
    # that dropped the row entirely would satisfy the absence checks below.
    member = paid_overdue_invoice.billing_record.member
    assert member.full_name in body
    assert "is-overdue" not in body
    assert "badge--overdue" not in body


def test_invoices_page_paginates_and_totals_cover_the_whole_set(
    client, reviewer, approved_application, default_plan
):
    """Rows paginate; the stat strip does not.

    The stat cards report money owed, so they are computed over the whole
    filtered queryset — a figure describing only page 1 would understate the
    debt. This asserts both halves: PAGE_SIZE rows on screen, but a count and
    an outstanding total reflecting every invoice."""
    import datetime
    from decimal import Decimal

    from apps.admin_hub.invoices import PAGE_SIZE
    from apps.billing.models import BillingInvoice, BillingRecord

    record = BillingRecord.objects.create(
        member=approved_application.approved_member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    total_rows = PAGE_SIZE + 3
    for sequence in range(1, total_rows + 1):
        BillingInvoice.objects.create(
            billing_record=record,
            sequence=sequence,
            due_date=datetime.date(2026, 9, 20),
            amount=Decimal("10.00"),
            balance=Decimal("10.00"),
            payment_status="unpaid",
        )

    client.force_login(reviewer)
    response = client.get(reverse("admin_hub:invoices"), {"tab": "visi"})
    assert response.status_code == 200
    page_obj = response.context["page_obj"]
    assert len(response.context["rows"]) == PAGE_SIZE
    assert page_obj.paginator.num_pages == 2
    # Totals span every row, not just this page.
    totals = response.context["totals"]
    assert totals["count"] == total_rows
    assert totals["outstanding"] == Decimal("10.00") * total_rows


def test_invoices_invalid_page_falls_back_to_page_one(
    client, reviewer, unpaid_invoice
):
    client.force_login(reviewer)
    response = client.get(
        reverse("admin_hub:invoices"), {"tab": "visi", "page": "../etc/passwd"}
    )
    assert response.status_code == 200
    assert response.context["page_obj"].number == 1


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

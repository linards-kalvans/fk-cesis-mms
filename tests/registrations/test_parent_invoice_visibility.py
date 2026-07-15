"""P12: Parent portal invoice visibility — builder + template rendering.

Builder: parent_invoice_groups(account) returns issued invoices for the
parent's children, grouped by child + season. Hides unissued (sent_at null
and external_status != "sent") and other guardian's invoices.

Template: /portal/ renders the invoice section heading, empty state, and
per-row invoice data including the proxy URL or unavailable-link copy.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member, mark_agreement_signed
from apps.billing.models import BillingInvoice, BillingRecord
from apps.members.models import Member
from apps.registrations.services import approve_application

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer", is_staff=True)


@pytest.fixture
def default_plan(db):
    from apps.billing.models import MembershipPlan

    existing = MembershipPlan.objects.filter(is_default=True, is_active=True).first()
    if existing:
        return existing
    return MembershipPlan.objects.create(
        name="P12 Default Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
        is_default=True,
    )


@pytest.fixture
def approved_app(submitted_application, reviewer, default_plan):
    app = approve_application(submitted_application, reviewer)
    agreement = create_agreement_for_member(
        app.approved_member, Agreement.SigningPath.PAPER
    )
    mark_agreement_signed(agreement, reviewer)
    return app


@pytest.fixture
def issued_invoice(approved_app, default_plan):
    """A sent BillingInvoice attached to the approved app's billing record."""
    member = approved_app.approved_member
    rec, _ = BillingRecord.objects.get_or_create(
        member=member,
        season="2026/2027",
        defaults={
            "plan": default_plan,
            "base_amount": Decimal("300.00"),
            "final_amount": Decimal("300.00"),
            "status": BillingRecord.Status.CONFIRMED,
        },
    )
    return BillingInvoice.objects.create(
        billing_record=rec,
        sequence=1,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="inv-issued",
        external_status="sent",
        payment_status="paid",
        sent_at="2026-09-15T10:00:00Z",
        external_url="https://in.example.com/view/issued",
    )


@pytest.fixture
def unissued_invoice(approved_app, default_plan):
    """A draft BillingInvoice (sent_at null, external_status != sent)."""
    member = approved_app.approved_member
    rec, _ = BillingRecord.objects.get_or_create(
        member=member,
        season="2026/2027",
        defaults={
            "plan": default_plan,
            "base_amount": Decimal("300.00"),
            "final_amount": Decimal("300.00"),
            "status": BillingRecord.Status.CONFIRMED,
        },
    )
    return BillingInvoice.objects.create(
        billing_record=rec,
        sequence=2,
        due_date=date(2026, 11, 20),
        amount=Decimal("30.00"),
        external_invoice_id="inv-future",
        external_status="created",
    )


# ---------------------------------------------------------------------------
# Builder tests
# ---------------------------------------------------------------------------


def test_builder_includes_only_current_parent_issued_invoices(
    parent_account, issued_invoice, unissued_invoice
):
    from apps.billing.parent_portal import parent_invoice_groups

    groups = parent_invoice_groups(parent_account)
    # Flatten all invoices returned
    all_invoices = [
        row["invoice"]
        for group in groups
        for row in group["rows"]
    ]
    assert issued_invoice in all_invoices
    assert unissued_invoice not in all_invoices


def test_builder_hides_other_parent_invoices(
    parent_account, other_parent_account, issued_invoice
):
    from apps.billing.parent_portal import parent_invoice_groups

    groups = parent_invoice_groups(other_parent_account)
    all_invoices = [
        row["invoice"]
        for group in groups
        for row in group["rows"]
    ]
    assert issued_invoice not in all_invoices


def test_builder_separates_groups_by_child_and_season(
    parent_account, make_guardian, default_plan
):
    """Builder must produce one group per (child, season) pair."""
    from apps.billing.parent_portal import parent_invoice_groups

    # Two children under the same guardian
    guardian = make_guardian(parent_account, full_name="Test Guardian")
    child_a = Member.objects.create(full_name="Child A", guardian=guardian)
    child_b = Member.objects.create(full_name="Child B", guardian=guardian)

    # Two seasons per child → 4 distinct groups expected
    for member in (child_a, child_b):
        for season in ("2025/2026", "2026/2027"):
            rec = BillingRecord.objects.create(
                member=member,
                plan=default_plan,
                season=season,
                base_amount=Decimal("300.00"),
                final_amount=Decimal("300.00"),
                status=BillingRecord.Status.CONFIRMED,
            )
            BillingInvoice.objects.create(
                billing_record=rec,
                sequence=1,
                due_date=date(2026, 10, 20),
                amount=Decimal("30.00"),
                external_invoice_id=f"inv-{member.pk}-{season}",
                external_status="sent",
                sent_at="2026-09-15T10:00:00Z",
            )

    groups = parent_invoice_groups(parent_account)
    pairs = {(g["member_name"], g["season"]) for g in groups}
    assert pairs == {
        ("Child A", "2025/2026"),
        ("Child A", "2026/2027"),
        ("Child B", "2025/2026"),
        ("Child B", "2026/2027"),
    }


# ---------------------------------------------------------------------------
# Template rendering tests
# ---------------------------------------------------------------------------


def test_portal_renders_heading_and_empty_state(verified_client, parent_account, make_guardian):
    """When the parent has no issued invoices, the empty state renders."""
    make_guardian(parent_account, full_name="Test Parent")
    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode()
    assert "Mani rēķini" in html
    assert "Šobrīd nav izsūtītu rēķinu." in html


def test_portal_renders_invoice_rows(
    verified_client, issued_invoice, approved_app
):
    """Issued invoices render with member name, season, sequence marker, amount,
    'Izsūtīts', payment status label, and proxy URL with 'Atvērt rēķinu' link."""
    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode()

    # Heading
    assert "Mani rēķini" in html

    # Member name from approved_app
    member_name = approved_app.approved_member.full_name
    assert member_name in html

    # Season
    assert "2026/2027" in html

    # Sequence marker (e.g., "#1")
    assert "#1" in html

    # Amount
    assert "30.00" in html

    # Sent status
    assert "Izsūtīts" in html

    # Payment status label (deterministic: fixture sets payment_status="paid")
    assert "Apmaksāts" in html

    # Proxy URL
    proxy_url = reverse("registrations:parent-invoice-open", args=[issued_invoice.pk])
    assert proxy_url in html

    # Link text
    assert "Atvērt rēķinu" in html


def test_portal_renders_unavailable_link_copy_when_no_external_url(
    verified_client, approved_app, default_plan
):
    """When an issued invoice has no external_url, show unavailable-link copy
    and do NOT show 'Atvērt rēķinu'."""
    member = approved_app.approved_member
    rec, _ = BillingRecord.objects.get_or_create(
        member=member,
        season="2026/2027",
        defaults={
            "plan": default_plan,
            "base_amount": Decimal("300.00"),
            "final_amount": Decimal("300.00"),
            "status": BillingRecord.Status.CONFIRMED,
        },
    )
    BillingInvoice.objects.create(
        billing_record=rec,
        sequence=1,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="inv-no-url",
        external_status="sent",
        sent_at="2026-09-15T10:00:00Z",
        external_url="",
    )
    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode()
    assert "Saite būs pieejama pēc maksājuma sinhronizācijas." in html
    assert "Atvērt rēķinu" not in html


def test_portal_shows_needs_sync_copy_when_no_last_synced_at(
    verified_client, approved_app, default_plan
):
    """When an issued invoice has no last_synced_at, show 'Vēl nav sinhronizēts'."""
    member = approved_app.approved_member
    rec, _ = BillingRecord.objects.get_or_create(
        member=member,
        season="2026/2027",
        defaults={
            "plan": default_plan,
            "base_amount": Decimal("300.00"),
            "final_amount": Decimal("300.00"),
            "status": BillingRecord.Status.CONFIRMED,
        },
    )
    BillingInvoice.objects.create(
        billing_record=rec,
        sequence=1,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="inv-no-sync",
        external_status="sent",
        sent_at="2026-09-15T10:00:00Z",
        last_synced_at=None,
    )
    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode()
    assert "Vēl nav sinhronizēts" in html

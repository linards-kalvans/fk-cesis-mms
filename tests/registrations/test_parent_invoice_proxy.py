"""P12: Parent invoice proxy route — GET /portal/invoices/<id>/open/.

Ownership-scoped redirect: the parent must own the invoice via
ParentAccount -> Guardian -> Member -> BillingRecord -> BillingInvoice.
Only issued invoices (sent_at not null OR external_status == "sent") with
a non-empty external_url redirect. Other cases return 404.

No session -> redirect to start-registration.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member, mark_agreement_signed
from apps.billing.models import BillingInvoice, BillingRecord
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
        name="P12 Proxy Plan",
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
def owned_issued_invoice_with_url(approved_app, default_plan):
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
        external_invoice_id="inv-owned",
        external_status="sent",
        sent_at="2026-09-15T10:00:00Z",
        external_url="https://in.example.com/view/owned",
    )


@pytest.fixture
def other_guardians_issued_invoice(
    other_parent_account, default_plan, make_guardian
):
    """An issued invoice belonging to a different parent."""
    from apps.members.models import Member

    guardian = make_guardian(other_parent_account, full_name="Other Guardian")
    member = Member.objects.create(full_name="Other Child", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member,
        plan=default_plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    return BillingInvoice.objects.create(
        billing_record=rec,
        sequence=1,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="inv-other",
        external_status="sent",
        sent_at="2026-09-15T10:00:00Z",
        external_url="https://in.example.com/view/other",
    )


@pytest.fixture
def unissued_invoice(approved_app, default_plan):
    """An invoice that has not been issued (sent_at null, external_status != sent)."""
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
        external_invoice_id="inv-unissued",
        external_status="created",
        external_url="https://in.example.com/view/unissued",
    )


@pytest.fixture
def issued_invoice_no_url(approved_app, default_plan):
    """An issued invoice with no external_url set."""
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
        external_invoice_id="inv-no-url",
        external_status="sent",
        sent_at="2026-09-15T10:00:00Z",
        external_url="",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_owned_issued_invoice_with_url_redirects(
    verified_client, owned_issued_invoice_with_url
):
    url = reverse(
        "registrations:parent-invoice-open",
        args=[owned_issued_invoice_with_url.pk],
    )
    resp = verified_client.get(url)
    assert resp.status_code == 302
    assert resp.url == "https://in.example.com/view/owned"


def test_other_guardian_returns_404(
    verified_client, other_guardians_issued_invoice
):
    url = reverse(
        "registrations:parent-invoice-open",
        args=[other_guardians_issued_invoice.pk],
    )
    resp = verified_client.get(url)
    assert resp.status_code == 404


def test_unissued_invoice_returns_404(verified_client, unissued_invoice):
    url = reverse(
        "registrations:parent-invoice-open",
        args=[unissued_invoice.pk],
    )
    resp = verified_client.get(url)
    assert resp.status_code == 404


def test_missing_external_url_returns_404(verified_client, issued_invoice_no_url):
    url = reverse(
        "registrations:parent-invoice-open",
        args=[issued_invoice_no_url.pk],
    )
    resp = verified_client.get(url)
    assert resp.status_code == 404


def test_no_session_redirects_to_start_registration(
    db, owned_issued_invoice_with_url
):
    client = Client()
    url = reverse(
        "registrations:parent-invoice-open",
        args=[owned_issued_invoice_with_url.pk],
    )
    resp = client.get(url)
    assert resp.status_code == 302
    assert resp.url == reverse("registrations:start-registration")

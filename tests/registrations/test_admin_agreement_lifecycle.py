"""P8: Admin agreement lifecycle action tests.

Tests that the RegistrationApplication admin change page shows lifecycle
forms/actions for signed agreements, that POST workflows work, and that
paid-invoice discontinuation blocks with a Latvian warning.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    mark_agreement_sent,
    mark_agreement_signed,
)
from apps.registrations.services import approve_application


pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer", is_staff=True)


@pytest.fixture
def approved_with_signed_agreement(submitted_application, reviewer):
    """An approved application whose agreement has been sent + signed."""
    app = approve_application(submitted_application, reviewer)
    agreement = create_agreement_for_member(
        app.approved_member, Agreement.SigningPath.PAPER
    )
    mark_agreement_sent(agreement, reviewer)
    mark_agreement_signed(agreement, reviewer)
    return app


@pytest.fixture
def active_plan(db):
    from apps.billing.models import MembershipPlan

    return MembershipPlan.objects.create(
        name="P8 Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
    )


@pytest.fixture
def billing_record_factory(db, active_plan):
    """Factory: create a confirmed BillingRecord for any given member."""
    from apps.billing.models import BillingRecord

    def _make(member):
        return BillingRecord.objects.create(
            member=member,
            plan=active_plan,
            season=active_plan.season,
            base_amount=active_plan.annual_amount,
            final_amount=active_plan.annual_amount,
            status=BillingRecord.Status.CONFIRMED,
        )

    return _make


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


# -- Visibility on signed agreements --


def test_signed_agreement_page_shows_lifecycle_forms_and_labels(
    approved_with_signed_agreement, staff_client
):
    """Change page for a signed agreement must show the minor amendment,
    material amendment, and discontinuation affordances with the new
    Latvian labels and disclosure copy, and must NOT carry the old
    void label.
    """
    resp = staff_client.get(
        _change_url(approved_with_signed_agreement.id)
    )
    html = resp.content.decode("utf-8")
    html_lower = html.lower()

    # Lifecycle action affordances (P8 originals).
    assert "Neliels labojums" in html
    assert "Sagatavot aizvietojošu līgumu" in html
    assert "Pārtraukt dalību" in html

    # Void disclosure must explain it is document-only and NOT change
    # participation or invoices.
    assert "dokument" in html_lower, (
        "void disclosure must mention the document scope"
    )
    void_negations = ["nemaina dalību", "neietekmē", "neizmaina", "neattiecas"]
    assert any(phrase in html_lower for phrase in void_negations), (
        f"void disclosure must explain limited scope; expected one of {void_negations}"
    )

    # Discontinue disclosure must mention invoice processing and
    # participation ending.
    assert "norēķin" in html_lower, (
        "discontinue disclosure must mention invoice processing"
    )
    assert "dalīb" in html_lower, (
        "discontinue disclosure must mention participation"
    )

    # P8 rework: label changes (J).
    assert "Anulēt līguma dokumentu" in html, (
        "expected new void label in admin page"
    )
    assert "Pārtraukt dalību un norēķinus" in html, (
        "expected new discontinue label in admin page"
    )

    # P8 rework: old void label must be gone.
    assert "Atcelt līgumu" not in html, (
        "old void label must be replaced by 'Anulēt līguma dokumentu'"
    )


# -- Generated (not signed) shows no lifecycle actions --


def test_generated_agreement_shows_no_lifecycle_actions(
    submitted_application, staff_client, reviewer
):
    """Agreement in generated state does not show lifecycle forms."""
    approve_application(submitted_application, reviewer)
    resp = staff_client.get(_change_url(submitted_application.id))
    html = resp.content.decode("utf-8")
    assert "Neliels labojums" not in html
    assert "Sagatavot aizvietojošu līgumu" not in html
    assert "Pārtraukt dalību" not in html


# -- POST minor amendment --


def test_post_minor_amendment_creates_event(
    approved_with_signed_agreement, staff_client
):
    """POST with action=minor_amendment creates a lifecycle event."""
    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "minor_amendment", "note": "Labots e-pasts"},
    )
    assert resp.status_code == 302

    agreement = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED
    assert agreement.lifecycle_events.filter(event_type="minor_amendment").exists()


# -- POST material amendment --


def test_post_material_amendment_creates_new_agreement(
    approved_with_signed_agreement, staff_client
):
    """POST with action=material_amendment supersedes old + creates new."""
    old = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    old_id = old.id

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "material_amendment", "note": "Mainīti noteikumi"},
    )
    assert resp.status_code == 302

    old.refresh_from_db()
    assert old.state == Agreement.State.SUPERSEDED
    assert old.is_current is False

    new = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    assert new.id != old_id
    assert new.state == Agreement.State.GENERATED


# -- POST discontinuation blocks with paid invoice --


def test_post_discontinuation_with_paid_invoice_warns_with_latvian(
    approved_with_signed_agreement, staff_client, active_plan, billing_record_factory
):
    """When a selected invoice is paid, the admin action must show a Latvian
    warning and NOT change agreement/member state."""
    from apps.billing.models import BillingInvoice

    member = approved_with_signed_agreement.approved_member
    record = billing_record_factory(member)

    paid = BillingInvoice.objects.create(
        billing_record=record,
        sequence=99,
        due_date="2026-12-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-PAID-1",
        external_status="sent",
        payment_status="paid",
    )

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {
            "action": "discontinue_member",
            "effective_date": "2026-09-01",
            "reason": "Pārcelšanās",
            "selected_invoices": [str(paid.pk)],
        },
        follow=True,
    )
    html = resp.content.decode("utf-8")

    # Latvian warning about paid invoice
    assert "apmaksātu" in html.lower() or "apmaksāt" in html.lower()

    # Nothing mutated
    agreement = Agreement.objects.filter(
        member=member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED
    member.refresh_from_db()
    assert member.status != member.Status.DISCONTINUED  # still active


# -- Anonymous blocked --


def test_post_discontinuation_with_invalid_date_is_rejected(
    approved_with_signed_agreement, staff_client
):
    """An invalid effective_date must not call the service or change state."""
    from apps.agreements.models import Agreement

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {
            "action": "discontinue_member",
            "effective_date": "not-a-date",
            "reason": "Pārcelšanās",
            "selected_invoices": [],
        },
        follow=True,
    )
    assert resp.status_code == 200

    agreement = Agreement.objects.filter(
        member=approved_with_signed_agreement.approved_member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED
    assert not agreement.lifecycle_events.filter(
        event_type="discontinued"
    ).exists()


def test_anonymous_cannot_post_lifecycle_actions(
    approved_with_signed_agreement, client
):
    resp = client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "minor_amendment", "note": "test"},
    )
    assert resp.status_code in (302, 403, 404)


# -- Non-staff blocked --


def test_non_staff_verified_parent_cannot_post_actions(
    approved_with_signed_agreement, verified_client
):
    resp = verified_client.post(
        _action_url(approved_with_signed_agreement.id),
        {"action": "minor_amendment", "note": "test"},
    )
    assert resp.status_code in (302, 403, 404)


# -- P8 rework: Partial invoice blocks (K) --


def test_post_discontinuation_with_partial_invoice_blocks(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory,
):
    """When a selected invoice is partially paid, the admin action must block
    with a Latvian error and leave agreement/member/invoices UNCHANGED."""
    from apps.billing.models import BillingInvoice

    member = approved_with_signed_agreement.approved_member
    record = billing_record_factory(member)

    partial = BillingInvoice.objects.create(
        billing_record=record,
        sequence=99,
        due_date="2026-12-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-PARTIAL-1",
        external_status="sent",
        payment_status="partial",
    )

    resp = staff_client.post(
        _action_url(approved_with_signed_agreement.id),
        {
            "action": "discontinue_member",
            "effective_date": "2026-09-01",
            "reason": "Pārcelšanās",
            "selected_invoices": [str(partial.pk)],
        },
        follow=True,
    )
    html = resp.content.decode("utf-8")
    assert resp.status_code == 200

    # Must show some Latvian error message about the partially paid invoice
    assert "apmaks" in html.lower(), (
        "expected a Latvian error about the partially paid invoice"
    )

    # Nothing mutated — agreement still signed
    agreement = Agreement.objects.filter(
        member=member, is_current=True
    ).first()
    assert agreement.state == Agreement.State.SIGNED, (
        "agreement must stay signed after partial block"
    )
    member.refresh_from_db()
    assert member.status == member.Status.ACTIVE, (
        "member must stay active after partial block"
    )

    # Invoice unchanged
    partial.refresh_from_db()
    assert partial.cancelled_at is None, (
        "invoice must not be cancelled on block"
    )
    assert partial.payment_status == "partial", (
        "payment status must be unchanged"
    )


# -- P8 rework: Post-discontinuation cancelled invoice visibility (L) --


def test_post_discontinuation_shows_cancelled_invoice_on_change_page(
    approved_with_signed_agreement, staff_client, active_plan,
    billing_record_factory,
):
    """After a successful discontinuation with a selected sent-unpaid invoice,
    the admin change page must still show the cancelled invoice state
    even though the member is now discontinued."""
    from apps.billing.models import BillingInvoice
    from apps.agreements.services import discontinue_agreement
    import datetime

    member = approved_with_signed_agreement.approved_member
    record = billing_record_factory(member)

    sent_unpaid = BillingInvoice.objects.create(
        billing_record=record,
        sequence=99,
        due_date="2026-12-20",
        amount=Decimal("30.00"),
        external_invoice_id="IN-CANCEL-VIS",
        external_status="sent",
        payment_status="unpaid",
    )

    agreement = Agreement.objects.filter(
        member=member, is_current=True
    ).first()
    discontinue_agreement(
        agreement=agreement,
        actor=None,
        effective_date=datetime.date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[sent_unpaid.pk],
    )

    # Verify member is discontinued
    member.refresh_from_db()
    assert member.status == member.Status.DISCONTINUED

    # Verify the invoice is locally cancelled
    sent_unpaid.refresh_from_db()
    assert sent_unpaid.cancelled_at is not None, (
        "invoice must be locally cancelled"
    )

    # Open the admin change page — must still show the invoice details
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")
    assert resp.status_code == 200

    # After discontinuation, the agreement state must be visible
    assert "Pārtraukts" in html, (
        "agreement state 'Pārtraukts' must be visible on change page"
    )

    # The cancelled invoice's IN id must still be visible on the page
    assert "IN-CANCEL-VIS" in html, (
        "cancelled invoice external id must still be visible on change page"
    )

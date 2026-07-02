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


pytestmark = pytest.mark.django_db


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


def test_signed_agreement_page_shows_minor_amendment_form(
    approved_with_signed_agreement, staff_client
):
    """Change page for a signed agreement must show minor amendment affordance."""
    resp = staff_client.get(
        _change_url(approved_with_signed_agreement.id)
    )
    html = resp.content.decode("utf-8")
    assert "Neliels labojums" in html


def test_signed_agreement_page_shows_material_amendment_form(
    approved_with_signed_agreement, staff_client
):
    resp = staff_client.get(
        _change_url(approved_with_signed_agreement.id)
    )
    html = resp.content.decode("utf-8")
    assert "Sagatavot aizvietojošu līgumu" in html


def test_signed_agreement_page_shows_discontinuation_form(
    approved_with_signed_agreement, staff_client
):
    resp = staff_client.get(
        _change_url(approved_with_signed_agreement.id)
    )
    html = resp.content.decode("utf-8")
    assert "Pārtraukt dalību" in html


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


# -- P8 rework: Void disclosure explanation (J extended) --


def test_void_disclosure_explains_document_only_scope(
    approved_with_signed_agreement, staff_client
):
    """Void disclosure must explain it only annuls the agreement document
    and does NOT change participation or invoices. Expected RED."""
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")

    # The void <details> must contain explanatory copy that it is
    # document-only — doesn't change membership or billing.
    assert "dokument" in html.lower(), (
        "void disclosure must mention the document scope"
    )
    # Must mention that participation/invoices are NOT affected.
    # At minimum one of these negations must appear:
    negations = ["nemaina dalību", "neietekmē", "neizmaina", "neattiecas"]
    found_any = any(phrase in html.lower() for phrase in negations)
    assert found_any, (
        f"void disclosure must explain limited scope; expected one of {negations}"
    )


# -- P8 rework: Discontinue disclosure explanation (J extended) --


def test_discontinue_disclosure_explains_invoice_processing(
    approved_with_signed_agreement, staff_client
):
    """Discontinue disclosure must explain it stops participation and
    processes selected invoices. Expected RED."""
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")

    # The discontinue <details> must mention invoice processing.
    assert "norēķin" in html.lower(), (
        "discontinue disclosure must mention invoice processing"
    )
    # Must mention participation ending.
    assert "dalīb" in html.lower(), (
        "discontinue disclosure must mention participation"
    )


# -- P8 rework: Label changes (J) --


def test_agreement_module_shows_anule_liguma_dokumentu(
    approved_with_signed_agreement, staff_client
):
    """Void disclosure must show 'Anulēt līguma dokumentu' label
    (was 'Atcelt līgumu'). Expected RED: string not present yet."""
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")
    assert "Anulēt līguma dokumentu" in html, (
        "expected new void label in admin page"
    )


def test_agreement_module_shows_partraukt_dalibu_un_norekinus(
    approved_with_signed_agreement, staff_client
):
    """Discontinue disclosure must show 'Pārtraukt dalību un norēķinus'
    label (was 'Pārtraukt dalību'). Expected RED: not present yet."""
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")
    assert "Pārtraukt dalību un norēķinus" in html, (
        "expected new discontinue label in admin page"
    )


def test_old_void_label_atcelt_ligumu_not_in_page(
    approved_with_signed_agreement, staff_client
):
    """The old 'Atcelt līgumu' label must not appear as a void-disclosure
    summary in the admin page. Expected RED: it IS present now."""
    resp = staff_client.get(_change_url(approved_with_signed_agreement.id))
    html = resp.content.decode("utf-8")
    assert "Atcelt līgumu" not in html, (
        "old void label must be replaced by 'Anulēt līguma dokumentu'"
    )


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

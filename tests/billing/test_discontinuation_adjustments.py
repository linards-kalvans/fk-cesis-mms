"""P8: Billing discontinuation invoice selection and local cancellation tests.

Tests PaidInvoiceSelected guard, unsent local cancellation, and sent unpaid
adjustment creation. These functions do not exist yet — expected RED phase.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def unsent_invoice(billing_invoice):
    """An invoice that has no external id and has never been sent."""
    billing_invoice.external_invoice_id = ""
    billing_invoice.sent_at = None
    billing_invoice.save(update_fields=["external_invoice_id", "sent_at"])
    return billing_invoice


@pytest.fixture
def sent_unpaid_invoice(billing_invoice):
    """An invoice pushed to IN and sent, but unpaid."""
    billing_invoice.external_invoice_id = "IN-123"
    billing_invoice.sent_at = "2026-06-15T12:00:00Z"
    billing_invoice.external_status = "sent"
    billing_invoice.payment_status = "unpaid"
    billing_invoice.save(
        update_fields=[
            "external_invoice_id", "sent_at", "external_status", "payment_status"
        ]
    )
    return billing_invoice


@pytest.fixture
def paid_invoice(sent_unpaid_invoice):
    """A sent invoice that has been fully paid."""
    sent_unpaid_invoice.payment_status = "paid"
    sent_unpaid_invoice.save(update_fields=["payment_status"])
    return sent_unpaid_invoice


# -- PaidInvoiceSelected guard --


def test_paid_selected_invoice_blocks():
    """PaidInvoiceSelected must be importable and a ValueError subclass."""
    from apps.billing.services import PaidInvoiceSelected

    assert issubclass(PaidInvoiceSelected, ValueError)


def test_discontinuation_with_paid_invoice_raises(paid_invoice):
    """When a selected invoice is paid, the service must raise PaidInvoiceSelected."""
    from apps.billing.services import (
        PaidInvoiceSelected,
        create_discontinuation_adjustments,
    )

    member = paid_invoice.billing_record.member

    with pytest.raises(PaidInvoiceSelected):
        create_discontinuation_adjustments(
            member=member,
            event=None,
            invoice_ids=[paid_invoice.pk],
            reason="Pārtraukta dalība",
        )


def test_paid_invoice_block_happens_before_state_change(paid_invoice):
    """The guard must raise before any DB mutation — the invoice state must remain."""
    from apps.billing.services import (
        PaidInvoiceSelected,
        create_discontinuation_adjustments,
    )

    member = paid_invoice.billing_record.member

    try:
        create_discontinuation_adjustments(
            member=member,
            event=None,
            invoice_ids=[paid_invoice.pk],
            reason="Pārtraukta dalība",
        )
    except PaidInvoiceSelected:
        pass

    # Invoice still paid — nothing was mutated
    paid_invoice.refresh_from_db()
    assert paid_invoice.payment_status == "paid"


# -- Local unsent cancellation --


def test_unsent_local_invoice_marked_cancelled(unsent_invoice):
    """An unsent local invoice must be marked cancelled_at, not create an adjustment."""
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingAdjustment

    member = unsent_invoice.billing_record.member

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[unsent_invoice.pk],
        reason="Pārtraukta dalība",
    )

    unsent_invoice.refresh_from_db()
    assert unsent_invoice.cancelled_at is not None
    assert unsent_invoice.cancellation_reason != ""

    # No BillingAdjustment created for an unsent local invoice
    assert BillingAdjustment.objects.count() == 0


# -- Sent unpaid/partial adjustment --


def test_sent_unpaid_invoice_creates_adjustment(sent_unpaid_invoice):
    """A sent unpaid invoice must create a BillingAdjustment and NOT cancel locally."""
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingAdjustment

    member = sent_unpaid_invoice.billing_record.member

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[sent_unpaid_invoice.pk],
        reason="Pārtraukta dalība",
    )

    sent_unpaid_invoice.refresh_from_db()
    # Not cancelled locally — it's already sent in IN
    assert sent_unpaid_invoice.cancelled_at is None

    # Adjustment row created
    adjustment = BillingAdjustment.objects.get(invoice=sent_unpaid_invoice)
    assert adjustment.kind == BillingAdjustment.Kind.CREDIT_NOTE
    assert adjustment.amount == sent_unpaid_invoice.amount
    assert adjustment.external_status == "pending"


def test_sent_partial_invoice_also_creates_adjustment(sent_unpaid_invoice):
    """A sent partially-paid invoice must also create a BillingAdjustment."""
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingAdjustment

    sent_unpaid_invoice.payment_status = "partial"
    sent_unpaid_invoice.save(update_fields=["payment_status"])

    member = sent_unpaid_invoice.billing_record.member

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[sent_unpaid_invoice.pk],
        reason="Pārtraukta dalība",
    )

    adjustment = BillingAdjustment.objects.get(invoice=sent_unpaid_invoice)
    assert adjustment.kind == BillingAdjustment.Kind.CREDIT_NOTE


# -- Mixed invoice batch --


def test_mixed_batch_cancels_unsent_and_creates_adjustments(billing_record):
    """When both an unsent and a sent unpaid invoice are selected, each gets
    the correct treatment."""
    from datetime import date
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingInvoice, BillingAdjustment

    member = billing_record.member

    unsent = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=0,
        due_date=date(2026, 9, 20),
        amount=Decimal("30.00"),
        external_invoice_id="",
        sent_at=None,
    )
    sent = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=1,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-456",
        sent_at="2026-06-15T12:00:00Z",
        external_status="sent",
        payment_status="unpaid",
    )

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[unsent.pk, sent.pk],
        reason="Pārtraukta dalība",
    )

    unsent.refresh_from_db()
    assert unsent.cancelled_at is not None

    sent.refresh_from_db()
    assert sent.cancelled_at is None
    assert BillingAdjustment.objects.filter(invoice=sent).exists()


# -- Foreign invoice id guard --


def test_foreign_invoice_rejected(billing_record):
    """Selecting an invoice from a different member must raise ValueError."""
    from tests.support import make_guardian
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice
    from apps.billing.services import create_discontinuation_adjustments

    # Create a different member + record + invoice
    other_guardian = make_guardian(full_name="Other", email="other@example.test")
    other_member = Member.objects.create(
        full_name="Other Child", guardian=other_guardian
    )
    other_plan = billing_record.plan
    other_record = BillingRecord.objects.create(
        member=other_member,
        plan=other_plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )
    other_invoice = BillingInvoice.objects.create(
        billing_record=other_record,
        sequence=0,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
    )

    member = billing_record.member

    with pytest.raises(ValueError, match="foreign"):
        create_discontinuation_adjustments(
            member=member,
            event=None,
            invoice_ids=[other_invoice.pk],
            reason="Pārtraukta dalība",
        )


# -- is_invoice_due_to_send skips cancelled --


def test_sent_invoice_without_external_id_raises(billing_record):
    """An invoice marked sent but lacking an external id is an unclear state;
    it must not silently create a credit note."""
    from django.utils import timezone
    from apps.billing.models import BillingInvoice
    from apps.billing.services import (
        DiscontinuationInvoiceError,
        create_discontinuation_adjustments,
    )

    invoice = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=0,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
        external_invoice_id="",
        sent_at=timezone.now(),
    )

    with pytest.raises(DiscontinuationInvoiceError):
        create_discontinuation_adjustments(
            member=billing_record.member,
            event=None,
            invoice_ids=[invoice.pk],
            reason="Pārtraukta dalība",
        )

    invoice.refresh_from_db()
    assert invoice.cancelled_at is None


def test_cancelled_invoice_excluded_from_due_to_send(unsent_invoice):
    """Once cancelled, is_invoice_due_to_send must return False."""
    from datetime import date
    from apps.billing.services import is_invoice_due_to_send

    # First, confirm the invoice would normally be eligible.
    # Mark as if pushed and due — use a proper date object.
    unsent_invoice.external_invoice_id = "IN-123"
    unsent_invoice.external_status = "created"
    unsent_invoice.due_date = date(2026, 2, 20)
    unsent_invoice.save(
        update_fields=["external_invoice_id", "external_status", "due_date"]
    )

    assert is_invoice_due_to_send(unsent_invoice, date(2026, 6, 30))

    # Cancel it
    from django.utils import timezone
    unsent_invoice.cancelled_at = timezone.now()
    unsent_invoice.save(update_fields=["cancelled_at"])

    # Now it must be excluded
    assert not is_invoice_due_to_send(unsent_invoice, date(2026, 6, 30))

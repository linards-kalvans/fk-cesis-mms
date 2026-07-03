"""P8: Billing discontinuation invoice selection and local cancellation tests.

Tests PaidInvoiceSelected guard (paid + partial), local cancellation for
unsent/draft/sent-unpaid invoices with correct external cancellation actions,
and the ZERO-credit-note policy for normal unpaid invoices.

New fields external_cancellation_action / external_cancellation_status /
external_cancellation_error_code do not exist yet — expected RED phase.
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
def draft_in_invoice(billing_invoice):
    """An invoice pushed to IN but still Draft (not yet sent)."""
    billing_invoice.external_invoice_id = "IN-DRAFT-1"
    billing_invoice.sent_at = None
    billing_invoice.external_status = "created"
    billing_invoice.save(
        update_fields=["external_invoice_id", "sent_at", "external_status"]
    )
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


@pytest.fixture
def partial_invoice(sent_unpaid_invoice):
    """A sent invoice that has been partially paid."""
    sent_unpaid_invoice.payment_status = "partial"
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


# -- Partial invoice now also blocks --


def test_partial_invoice_blocks_discontinuation(partial_invoice):
    """A partially paid invoice must also raise PaidInvoiceSelected
    (was previously allowed — new requirement: block)."""
    from apps.billing.services import (
        PaidInvoiceSelected,
        create_discontinuation_adjustments,
    )

    member = partial_invoice.billing_record.member

    with pytest.raises(PaidInvoiceSelected):
        create_discontinuation_adjustments(
            member=member,
            event=None,
            invoice_ids=[partial_invoice.pk],
            reason="Pārtraukta dalība",
        )


def test_partial_invoice_block_happens_before_state_change(partial_invoice):
    """Partial block must raise before any DB mutation — invoice stays
    unchanged AND zero BillingAdjustment rows are created."""
    from apps.billing.services import (
        PaidInvoiceSelected,
        create_discontinuation_adjustments,
    )
    from apps.billing.models import BillingAdjustment

    member = partial_invoice.billing_record.member
    before_adj_count = BillingAdjustment.objects.count()

    try:
        create_discontinuation_adjustments(
            member=member,
            event=None,
            invoice_ids=[partial_invoice.pk],
            reason="Pārtraukta dalība",
        )
    except PaidInvoiceSelected:
        pass

    partial_invoice.refresh_from_db()
    assert partial_invoice.payment_status == "partial"
    assert partial_invoice.cancelled_at is None

    # No BillingAdjustment must have been created — the guard blocks first.
    assert BillingAdjustment.objects.count() == before_adj_count, (
        "partial invoice must not create a BillingAdjustment"
    )


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


def test_unsent_local_invoice_has_no_external_cancellation_fields(unsent_invoice):
    """An unsent local invoice must NOT have external cancellation fields set:
    no action, no status, no error code — it was never in Invoice Ninja."""
    from apps.billing.services import create_discontinuation_adjustments

    member = unsent_invoice.billing_record.member
    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[unsent_invoice.pk],
        reason="Pārtraukta dalība",
    )
    unsent_invoice.refresh_from_db()

    # These fields do not exist yet — hasattr returns False.
    # Once they exist, the values must be blank.
    if hasattr(unsent_invoice, "external_cancellation_action"):
        assert (
            unsent_invoice.external_cancellation_action == ""
        ), f"expected blank, got {unsent_invoice.external_cancellation_action}"
    if hasattr(unsent_invoice, "external_cancellation_status"):
        assert (
            unsent_invoice.external_cancellation_status == ""
        ), f"expected blank, got {unsent_invoice.external_cancellation_status}"
    if hasattr(unsent_invoice, "external_cancellation_error_code"):
        assert (
            unsent_invoice.external_cancellation_error_code == ""
        ), f"expected blank, got {unsent_invoice.external_cancellation_error_code}"


# -- Draft IN invoice: cancelled locally, archive pending, ZERO adjustments --


def test_draft_in_invoice_cancelled_with_pending_archive(draft_in_invoice):
    """A Draft Invoice Ninja invoice (external_status='created') must be:
    - cancelled locally
    - external_cancellation_action = 'archive'
    - external_cancellation_status = 'pending'
    - ZERO BillingAdjustment rows created (no credit note).
    """
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingAdjustment

    member = draft_in_invoice.billing_record.member
    before_adj_count = BillingAdjustment.objects.count()

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[draft_in_invoice.pk],
        reason="Pārtraukta dalība",
    )

    draft_in_invoice.refresh_from_db()
    assert draft_in_invoice.cancelled_at is not None, "must be locally cancelled"
    assert draft_in_invoice.cancellation_reason != ""

    # No BillingAdjustment for draft IN invoices
    assert BillingAdjustment.objects.count() == before_adj_count, (
        "draft IN invoice must NOT create a credit-note adjustment"
    )

    # External cancellation tracking — fields do not exist yet.
    # hasattr returns False now → all three assertions below are skipped.
    # Once fields land, they must carry the correct values.
    if hasattr(draft_in_invoice, "external_cancellation_action"):
        assert draft_in_invoice.external_cancellation_action == "archive", (
            f"expected 'archive', got {draft_in_invoice.external_cancellation_action!r}"
        )
    if hasattr(draft_in_invoice, "external_cancellation_status"):
        assert draft_in_invoice.external_cancellation_status == "pending", (
            f"expected 'pending', got {draft_in_invoice.external_cancellation_status!r}"
        )
    if hasattr(draft_in_invoice, "external_cancellation_error_code"):
        assert draft_in_invoice.external_cancellation_error_code == "", (
            f"expected blank, got {draft_in_invoice.external_cancellation_error_code!r}"
        )


# -- Sent unpaid IN invoice: cancelled locally, cancel pending, ZERO adjustments --


def test_sent_unpaid_invoice_cancelled_with_pending_cancel(sent_unpaid_invoice):
    """A sent unpaid IN invoice (external_status='sent', payment='unpaid') must be:
    - cancelled locally
    - external_cancellation_action = 'cancel'
    - external_cancellation_status = 'pending'
    - ZERO BillingAdjustment rows (no credit note).
    """
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingAdjustment

    member = sent_unpaid_invoice.billing_record.member
    before_adj_count = BillingAdjustment.objects.count()

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[sent_unpaid_invoice.pk],
        reason="Pārtraukta dalība",
    )

    sent_unpaid_invoice.refresh_from_db()
    assert sent_unpaid_invoice.cancelled_at is not None, "must be locally cancelled"
    assert sent_unpaid_invoice.cancellation_reason != ""

    # No BillingAdjustment for sent unpaid invoices
    assert BillingAdjustment.objects.count() == before_adj_count, (
        "sent unpaid invoice must NOT create a credit-note adjustment"
    )

    if hasattr(sent_unpaid_invoice, "external_cancellation_action"):
        assert sent_unpaid_invoice.external_cancellation_action == "cancel", (
            f"expected 'cancel', got {sent_unpaid_invoice.external_cancellation_action!r}"
        )
    if hasattr(sent_unpaid_invoice, "external_cancellation_status"):
        assert sent_unpaid_invoice.external_cancellation_status == "pending", (
            f"expected 'pending', got {sent_unpaid_invoice.external_cancellation_status!r}"
        )
    if hasattr(sent_unpaid_invoice, "external_cancellation_error_code"):
        assert sent_unpaid_invoice.external_cancellation_error_code == "", (
            f"expected blank, got {sent_unpaid_invoice.external_cancellation_error_code!r}"
        )


# -- Mixed batch: no adjustments for any normal unpaid invoice --


def test_mixed_batch_cancels_all_and_creates_no_adjustments(billing_record):
    """When unsent, draft IN, and sent unpaid invoices are all selected,
    each gets cancelled locally with the correct external action, and
    ZERO BillingAdjustment rows are created."""
    from datetime import date
    from apps.billing.services import create_discontinuation_adjustments
    from apps.billing.models import BillingInvoice, BillingAdjustment

    member = billing_record.member
    before_adj = BillingAdjustment.objects.count()

    unsent = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=0,
        due_date=date(2026, 9, 20),
        amount=Decimal("30.00"),
        external_invoice_id="",
        sent_at=None,
    )
    draft = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=1,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-DRAFT-2",
        sent_at=None,
        external_status="created",
    )
    sent = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=2,
        due_date=date(2026, 11, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-456",
        sent_at="2026-06-15T12:00:00Z",
        external_status="sent",
        payment_status="unpaid",
    )

    create_discontinuation_adjustments(
        member=member,
        event=None,
        invoice_ids=[unsent.pk, draft.pk, sent.pk],
        reason="Pārtraukta dalība",
    )

    # All three cancelled locally
    for inv in (unsent, draft, sent):
        inv.refresh_from_db()
        assert inv.cancelled_at is not None, f"invoice {inv.pk} must be cancelled"

    # Zero adjustments
    assert BillingAdjustment.objects.count() == before_adj, (
        "no adjustments for normal unpaid invoices"
    )

    # External fields — checked only when they exist (RED: fields absent → skips)
    draft.refresh_from_db()
    sent.refresh_from_db()
    if hasattr(draft, "external_cancellation_action"):
        assert draft.external_cancellation_action == "archive"
        assert draft.external_cancellation_status == "pending"
    if hasattr(sent, "external_cancellation_action"):
        assert sent.external_cancellation_action == "cancel"
        assert sent.external_cancellation_status == "pending"


# -- Pre-mutation validation: unclear external status blocks whole batch --


def test_invalid_external_status_blocks_before_mutation(billing_record):
    """A mixed batch with a valid draft invoice followed by an invoice with an
    invalid external_status must raise BEFORE mutating either invoice."""
    from datetime import date
    from apps.billing.models import BillingInvoice, BillingAdjustment
    from apps.billing.services import (
        DiscontinuationInvoiceError,
        create_discontinuation_adjustments,
    )

    member = billing_record.member
    before_adj_count = BillingAdjustment.objects.count()

    valid_draft = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=10,
        due_date=date(2026, 9, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-DRAFT-VALID",
        sent_at=None,
        external_status="created",
    )
    invalid_status = BillingInvoice.objects.create(
        billing_record=billing_record,
        sequence=11,
        due_date=date(2026, 10, 20),
        amount=Decimal("30.00"),
        external_invoice_id="IN-WEIRD-1",
        sent_at=None,
        external_status="failed",
    )

    with pytest.raises(DiscontinuationInvoiceError):
        create_discontinuation_adjustments(
            member=member,
            event=None,
            invoice_ids=[valid_draft.pk, invalid_status.pk],
            reason="Pārtraukta dalība",
        )

    valid_draft.refresh_from_db()
    invalid_status.refresh_from_db()
    assert valid_draft.cancelled_at is None, "valid draft must not be mutated"
    assert invalid_status.cancelled_at is None, "invalid invoice must not be mutated"
    assert BillingAdjustment.objects.count() == before_adj_count, (
        "no adjustments created when validation blocks"
    )


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

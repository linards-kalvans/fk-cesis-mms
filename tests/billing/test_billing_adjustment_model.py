"""P8: BillingAdjustment model tests + BillingInvoice.cancelled_at."""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# -- BillingAdjustment model --


def test_billing_adjustment_model_exists():
    from apps.billing.models import BillingAdjustment  # noqa: F401


def test_billing_adjustment_defaults(billing_record):
    from apps.billing.models import BillingAdjustment

    adjustment = BillingAdjustment.objects.create(
        billing_record=billing_record,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount=Decimal("10.00"),
        reason="Pārtraukta dalība",
    )
    assert adjustment.external_credit_id == ""
    assert adjustment.external_status == "pending"
    assert adjustment.requires_staff_apply is False
    assert adjustment.applied_to_external_invoice_id == ""
    assert adjustment.external_error_code == ""


def test_billing_adjustment_kind_choices():
    from apps.billing.models import BillingAdjustment

    assert hasattr(BillingAdjustment.Kind, "CREDIT_NOTE")
    assert BillingAdjustment.Kind.CREDIT_NOTE == "credit_note"


def test_billing_adjustment_invoice_fk(billing_record, billing_invoice):
    from apps.billing.models import BillingAdjustment

    adjustment = BillingAdjustment.objects.create(
        billing_record=billing_record,
        invoice=billing_invoice,
        kind=BillingAdjustment.Kind.CREDIT_NOTE,
        amount=Decimal("30.00"),
        reason="Pārtraukta dalība",
    )
    assert adjustment.invoice_id == billing_invoice.pk


def test_billing_adjustment_agreement_event_fk_nullable():
    """agreement_event FK is nullable per spec."""
    from apps.billing.models import BillingAdjustment

    assert BillingAdjustment._meta.get_field("agreement_event").null is True


# -- BillingInvoice cancelled_at --


def test_billing_invoice_cancelled_at_defaults_to_none(billing_invoice):
    """cancelled_at must be None by default."""
    assert hasattr(billing_invoice, "cancelled_at")
    assert billing_invoice.cancelled_at is None


def test_billing_invoice_cancellation_reason_defaults_blank(billing_invoice):
    assert hasattr(billing_invoice, "cancellation_reason")
    assert billing_invoice.cancellation_reason == ""

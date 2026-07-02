"""P8: Invoice platform credit-note adapter boundary tests.

Tests the stub-mode shapes for create_credit_note and apply_credit_to_invoice.
These functions + dataclasses do not exist yet — expected RED phase.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.external_contract]


# -- CreditResult / CreditApplyResult dataclasses --


def test_credit_result_dataclass_exists():
    from apps.integrations.invoice_platform import CreditResult  # noqa: F401


def test_credit_apply_result_dataclass_exists():
    from apps.integrations.invoice_platform import CreditApplyResult  # noqa: F401


def test_credit_result_has_expected_fields():
    from apps.integrations.invoice_platform import CreditResult

    result = CreditResult(external_id="cr-1", external_status="created")
    assert result.external_id == "cr-1"
    assert result.external_status == "created"


def test_credit_apply_result_has_expected_fields():
    from apps.integrations.invoice_platform import CreditApplyResult

    result = CreditApplyResult(applied=True, external_status="applied")
    assert result.applied is True
    assert result.external_status == "applied"

    result_false = CreditApplyResult(applied=False, external_status="pending")
    assert result_false.applied is False


# -- Stub create_credit_note --


def test_stub_create_credit_note_returns_deterministic_id():
    """In stub mode, create_credit_note returns a deterministic external id."""
    from django.conf import settings
    from apps.integrations import invoice_platform
    from apps.billing.models import BillingAdjustment

    assert settings.INVOICE_PROVIDER_MODE == "stub"

    rec = _make_billing_record()
    adjustment = BillingAdjustment.objects.create(
        billing_record=rec,
        kind="credit_note",
        amount=Decimal("30.00"),
        reason="Pārtraukta dalība",
    )

    result = invoice_platform.create_credit_note(adjustment)
    assert result.external_id == f"stub-credit-{adjustment.pk}"
    assert result.external_status == "created"


def test_stub_create_credit_note_different_ids_for_different_adjustments():
    from apps.integrations import invoice_platform
    from apps.billing.models import BillingAdjustment

    rec = _make_billing_record()

    adj1 = BillingAdjustment.objects.create(
        billing_record=rec, kind="credit_note",
        amount=Decimal("10.00"), reason="A",
    )
    adj2 = BillingAdjustment.objects.create(
        billing_record=rec, kind="credit_note",
        amount=Decimal("20.00"), reason="B",
    )

    r1 = invoice_platform.create_credit_note(adj1)
    r2 = invoice_platform.create_credit_note(adj2)
    assert r1.external_id != r2.external_id


# -- Stub apply_credit_to_invoice --


def test_stub_apply_credit_returns_applied():
    from apps.integrations import invoice_platform

    result = invoice_platform.apply_credit_to_invoice(
        credit_id="stub-credit-1",
        invoice_id="IN-123",
        amount=Decimal("30.00"),
    )
    assert result.applied is True
    assert result.external_status == "applied"


# -- Mode dispatch --


def test_unknown_mode_raises_config_error():
    from django.conf import settings
    from unittest.mock import patch

    with patch.object(settings, "INVOICE_PROVIDER_MODE", "unknown-mode"):
        from apps.integrations.invoice_platform import (
            InvoicePlatformConfigError,
            create_credit_note,
        )
        with pytest.raises(InvoicePlatformConfigError):
            create_credit_note(None)


# -- Helpers --


def _make_billing_record():
    """Create a minimal confirmed BillingRecord for adjustment tests."""
    from tests.support import make_guardian
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, MembershipPlan

    guardian = make_guardian(full_name="Test", email="test@example.test")
    member = Member.objects.create(full_name="Test Child", guardian=guardian)
    plan = MembershipPlan.objects.create(
        name="Test Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
    )
    return BillingRecord.objects.create(
        member=member,
        plan=plan,
        season="2026/2027",
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
        status=BillingRecord.Status.CONFIRMED,
    )

import pytest
from decimal import Decimal
from types import SimpleNamespace  # noqa: F401
from unittest.mock import patch  # noqa: F401

import requests  # noqa: F401
from django.test import override_settings

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
)


def test_stub_mode_returns_unpaid_projection():
    from apps.integrations import invoice_platform

    result = invoice_platform.fetch_invoice_payment("anything")
    assert result.external_invoice_id == "anything"
    assert result.payment_status == "unpaid"
    assert result.amount == Decimal("0.00")
    assert result.paid_to_date == Decimal("0.00")
    assert result.balance is None
    assert result.last_payment_date is None


@override_settings(INVOICE_PROVIDER_MODE="bogus")
def test_unknown_mode_raises_config_error():
    from apps.integrations import invoice_platform
    from apps.integrations.invoice_platform import InvoicePlatformConfigError

    with pytest.raises(InvoicePlatformConfigError):
        invoice_platform.fetch_invoice_payment("x")

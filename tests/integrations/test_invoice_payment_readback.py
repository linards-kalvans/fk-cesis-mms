import pytest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import override_settings

pytestmark = pytest.mark.external_contract

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


@override_settings(**INVOICE_NINJA)
def test_paid_invoice_maps_to_paid_with_amounts():
    from datetime import date
    from apps.integrations import invoice_ninja

    payload = {
        "id": "inv-1", "status_id": "4", "amount": "30.00",
        "paid_to_date": "30.00", "balance": "0.00",
        "payments": [{"date": "2026-09-15"}, {"date": "2026-09-10"}],
    }
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake) as m:
        result = invoice_ninja.fetch_invoice_payment("inv-1")
    assert result.payment_status == "paid"
    assert result.paid_to_date == Decimal("30.00")
    assert result.balance == Decimal("0.00")
    assert result.last_payment_date == date(2026, 9, 15)
    assert m.call_args.kwargs["headers"]["X-Api-Token"] == "secret-token"
    assert m.call_args.args[0] == "GET"
    assert "include=payments" in m.call_args.args[1]


@override_settings(**INVOICE_NINJA)
def test_partial_invoice_maps_to_partial():
    from apps.integrations import invoice_ninja

    payload = {"id": "inv-2", "status_id": "3", "amount": "30.00",
               "paid_to_date": "10.00", "balance": "20.00", "payments": []}
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-2")
    assert result.payment_status == "partial"
    assert result.balance == Decimal("20.00")
    assert result.last_payment_date is None


@override_settings(**INVOICE_NINJA)
def test_sent_unpaid_invoice_maps_to_unpaid():
    from apps.integrations import invoice_ninja

    payload = {"id": "inv-3", "status_id": "2", "amount": "30.00",
               "paid_to_date": "0.00", "balance": "30.00"}
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-3")
    assert result.payment_status == "unpaid"


@override_settings(**INVOICE_NINJA)
def test_amount_derived_fallback_when_status_id_absent():
    from apps.integrations import invoice_ninja

    payload = {"id": "inv-4", "amount": "30.00", "paid_to_date": "30.00", "balance": "0.00"}
    fake = SimpleNamespace(status_code=200, json=lambda: {"data": payload}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        result = invoice_ninja.fetch_invoice_payment("inv-4")
    assert result.payment_status == "paid"


@override_settings(**INVOICE_NINJA)
def test_readback_auth_error_maps_to_auth_exception():
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    fake = SimpleNamespace(status_code=401, json=lambda: {}, text="nope")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformAuthError):
            invoice_ninja.fetch_invoice_payment("inv-5")


@override_settings(**INVOICE_NINJA)
def test_readback_not_found_maps_to_not_found_exception():
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformNotFoundError

    fake = SimpleNamespace(status_code=404, json=lambda: {}, text="missing")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformNotFoundError):
            invoice_ninja.fetch_invoice_payment("inv-gone")


@override_settings(**INVOICE_NINJA)
def test_readback_timeout_maps_to_transient():
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    with patch("apps.integrations.invoice_ninja.requests.request", side_effect=requests.Timeout("t")):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.fetch_invoice_payment("inv-6")

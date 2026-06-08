import pytest
from django.test import override_settings


def test_stub_ensure_product_is_deterministic():
    from apps.integrations import invoice_platform

    class _Plan:
        pk = 7

    result = invoice_platform.ensure_product(_Plan())
    assert result.external_id == "stub-product-7"


def test_stub_create_invoice_is_deterministic():
    from apps.integrations import invoice_platform

    class _BI:
        pk = 42

    result = invoice_platform.create_invoice(record=object(), billing_invoice=_BI())
    assert result.external_id == "stub-invoice-42"


@override_settings(INVOICE_PROVIDER_MODE="bogus")
def test_unknown_mode_raises_config_error():
    from apps.integrations import invoice_platform

    with pytest.raises(invoice_platform.InvoicePlatformConfigError):
        invoice_platform.ensure_client(object())

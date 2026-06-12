"""Platform seam: email_invoice dispatches stub vs invoiceninja."""

import pytest  # noqa: F401
from django.test import override_settings


@override_settings(INVOICE_PROVIDER_MODE="stub")
def test_email_invoice_stub_is_noop():
    from apps.integrations import invoice_platform

    assert invoice_platform.email_invoice("anything") is None


@override_settings(INVOICE_PROVIDER_MODE="invoiceninja")
def test_email_invoice_invoiceninja_delegates(monkeypatch):
    from apps.integrations import invoice_platform, invoice_ninja

    called = {}
    monkeypatch.setattr(invoice_ninja, "email_invoice", lambda eid: called.setdefault("id", eid))

    invoice_platform.email_invoice("HASHED123")
    assert called["id"] == "HASHED123"

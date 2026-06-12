"""IN provider: email_invoice issues the v5 bulk-email action."""

import pytest


def test_email_invoice_posts_bulk_email_action(monkeypatch):
    from apps.integrations import invoice_ninja

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

    def fake_request(method, url, api_key, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _Resp()

    monkeypatch.setattr(invoice_ninja, "_require_config", lambda: ("https://in.example/api/v1", "key"))
    monkeypatch.setattr(invoice_ninja, "_request", fake_request)

    invoice_ninja.email_invoice("HASHED123")

    assert captured["method"] == "POST"
    assert captured["url"] == "https://in.example/api/v1/invoices/bulk"
    assert captured["json"] == {"action": "email", "ids": ["HASHED123"]}


def test_email_invoice_raises_on_error_status(monkeypatch):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformConfigError

    class _Resp:
        status_code = 422
        text = "bad"

    monkeypatch.setattr(invoice_ninja, "_require_config", lambda: ("https://in.example/api/v1", "key"))
    monkeypatch.setattr(invoice_ninja, "_request", lambda *a, **k: _Resp())

    with pytest.raises(InvoicePlatformConfigError):
        invoice_ninja.email_invoice("HASHED123")

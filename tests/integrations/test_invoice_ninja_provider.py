import pytest
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import override_settings

pytestmark = pytest.mark.django_db

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
    INVOICE_NINJA_NUMBER_PREFIX="MMS",
)


def _record(active_plan, guardian, full_price=True):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    guardian.external_client_id = "client-1"
    guardian.save(update_fields=["external_client_id"])
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        is_full_price=full_price,
        sibling_discount_percent_applied=Decimal("0.00") if full_price else Decimal("50.00"),
    )
    bi = BillingInvoice.objects.create(
        billing_record=rec, sequence=3, due_date=date(2026, 11, 1), amount=Decimal("30.00")
    )
    return rec, bi


@override_settings(**INVOICE_NINJA)
def test_build_invoice_body_shape(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    body = invoice_ninja._build_invoice_body(rec, bi)
    assert body["client_id"] == "client-1"
    assert body["number"] == "MMS-{}-3".format(rec.pk)
    assert body["due_date"] == "2026-11-01"
    line = body["line_items"][0]
    assert line["product_key"] == "biedra-maksa-2026-2027"
    assert line["cost"] == "30.00"
    assert line["notes"] == "Biedra maksa 2026/2027"
    assert "Jānis" not in line["notes"]
    assert body["public_notes"] == "Biedra maksa — Jānis — 2026/2027"


@override_settings(**INVOICE_NINJA)
def test_sibling_note_appended_for_discounted(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian, full_price=False)
    body = invoice_ninja._build_invoice_body(rec, bi)
    line = body["line_items"][0]
    assert "Ietverta 50% atlaide" in body["public_notes"]
    assert "Ietverta" not in line["notes"]


@override_settings(**INVOICE_NINJA)
def test_create_invoice_posts_and_returns_id(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    fake = SimpleNamespace(status_code=200, json=lambda: {"id": "inv-99"}, text="")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake) as m:
        result = invoice_ninja.create_invoice(rec, bi)
    assert result.external_id == "inv-99"
    assert m.call_args.kwargs["headers"]["X-Api-Token"] == "secret-token"
    assert m.call_args.kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert m.call_args.kwargs["headers"]["Accept"] == "application/json"


@override_settings(**INVOICE_NINJA)
def test_auth_error_maps_to_auth_exception(active_plan, guardian):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    rec, bi = _record(active_plan, guardian)
    fake = SimpleNamespace(status_code=401, json=lambda: {}, text="nope")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformAuthError):
            invoice_ninja.create_invoice(rec, bi)


@override_settings(**INVOICE_NINJA)
def test_timeout_maps_to_transient(active_plan, guardian):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    rec, bi = _record(active_plan, guardian)
    with patch("apps.integrations.invoice_ninja.requests.request", side_effect=requests.Timeout("t")):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.create_invoice(rec, bi)


@override_settings(**INVOICE_NINJA)
def test_rate_limit_maps_to_transient(active_plan, guardian):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    rec, bi = _record(active_plan, guardian)
    fake = SimpleNamespace(status_code=429, json=lambda: {}, text="rate limited")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.create_invoice(rec, bi)


@override_settings(**INVOICE_NINJA)
def test_http_408_maps_to_transient(active_plan, guardian):
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    rec, bi = _record(active_plan, guardian)
    fake = SimpleNamespace(status_code=408, json=lambda: {}, text="request timeout")
    with patch("apps.integrations.invoice_ninja.requests.request", return_value=fake):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.create_invoice(rec, bi)


@override_settings(**INVOICE_NINJA)
def test_duplicate_number_recovers_existing_id(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    post_resp = SimpleNamespace(
        status_code=422, json=lambda: {},
        text='{"message":"The given data was invalid.","errors":{"number":["The number has already been taken."]}}'
    )
    lookup_resp = SimpleNamespace(
        status_code=200, json=lambda: {"data": [{"id": "inv-existing"}]}, text=""
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[post_resp, lookup_resp],
    ):
        result = invoice_ninja.create_invoice(rec, bi)
    assert result.external_id == "inv-existing"

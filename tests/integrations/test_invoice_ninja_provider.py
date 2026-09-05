import pytest
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.test import override_settings

pytestmark = [pytest.mark.django_db, pytest.mark.external_contract]

INVOICE_NINJA = dict(
    INVOICE_PROVIDER_MODE="invoiceninja",
    INVOICE_NINJA_API_URL="https://in.example.com/api/v1",
    INVOICE_NINJA_API_KEY="secret-token",
    INVOICE_NINJA_NUMBER_PREFIX="MMS",
)


def _record(active_plan, guardian, full_price=True, payment_mode=None, personal_id=None):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord, BillingInvoice

    member = Member.objects.create(full_name="Jānis", guardian=guardian, personal_id=personal_id or "")
    guardian.external_client_id = "client-1"
    guardian.save(update_fields=["external_client_id"])
    kwargs = {}
    if payment_mode is not None:
        kwargs["payment_mode"] = payment_mode
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        is_full_price=full_price,
        sibling_discount_percent_applied=Decimal("0.00") if full_price else Decimal("50.00"),
        **kwargs,
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
    # Payload date must be the first calendar day of the due_date month,
    # not the current date. Fixture due_date is 2026-11-01 (already day 1).
    assert body["date"] == "2026-11-01"
    line = body["line_items"][0]
    assert line["product_key"] == "biedra-maksa-2026-2027"
    assert line["cost"] == "30.00"
    assert line["notes"] == "Biedra maksa 2026/2027"
    assert "Jānis" not in line["notes"]
    assert "Futbola treniņu" not in line["notes"]
    # public_notes carries the new heading + per-installment period line.
    assert body["public_notes"] == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2026. gada novembri"
    )


@override_settings(**INVOICE_NINJA)
def test_sibling_note_appended_for_discounted(active_plan, guardian):
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian, full_price=False)
    body = invoice_ninja._build_invoice_body(rec, bi)
    line = body["line_items"][0]
    assert body["public_notes"] == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2026. gada novembri\n"
        "Ietverta 50% atlaide"
    )
    assert "Ietverta" not in line["notes"]


@override_settings(**INVOICE_NINJA)
def test_public_notes_installment_period_uses_due_date(active_plan, guardian):
    """The installment period line derives from the invoice due_date
    (2027-09-20 -> 'Maksājums par 2027. gada septembri')."""
    from datetime import date
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    bi.due_date = date(2027, 9, 20)
    bi.save(update_fields=["due_date"])
    body = invoice_ninja._build_invoice_body(rec, bi)
    # Non-first due day (20th) maps to the month first day in payload date.
    assert body["date"] == "2027-09-01"
    assert body["public_notes"] == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2027. gada septembri"
    )


@override_settings(**INVOICE_NINJA)
def test_public_notes_upfront_period_normalized_season(active_plan, guardian):
    """Upfront record: 'Maksājums par 2026./2027. gada sezonu'."""
    from apps.billing.models import BillingRecord
    from apps.integrations import invoice_ninja

    rec, bi = _record(
        active_plan, guardian,
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
    )
    bi.due_date = date(2027, 8, 20)
    bi.save(update_fields=["due_date"])
    body = invoice_ninja._build_invoice_body(rec, bi)
    # Upfront follows the same rule: payload date = first day of due month.
    assert body["date"] == "2027-08-01"
    assert body["public_notes"] == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2026./2027. gada sezonu"
    )
    assert "2026./2027.." not in body["public_notes"]


@override_settings(**INVOICE_NINJA)
def test_public_notes_never_contain_personal_id(active_plan, guardian):
    """No personal IDs may appear in public_notes."""
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian, personal_id="151210-22222")
    body = invoice_ninja._build_invoice_body(rec, bi)
    assert rec.member.personal_id
    assert rec.member.personal_id not in body["public_notes"]


@override_settings(**INVOICE_NINJA)
def test_build_invoice_body_no_new_http_fields(active_plan, guardian):
    """The create payload keeps exactly the existing Invoice Ninja fields."""
    from apps.integrations import invoice_ninja

    rec, bi = _record(active_plan, guardian)
    body = invoice_ninja._build_invoice_body(rec, bi)
    assert set(body.keys()) == {
        "client_id", "number", "date", "due_date", "public_notes", "line_items",
    }


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
    number = invoice_ninja._number(rec, bi.sequence)
    post_resp = SimpleNamespace(
        status_code=422, json=lambda: {},
        text='{"message":"The given data was invalid.","errors":{"number":["The number has already been taken."]}}'
    )
    # The recovery lookup verifies the number matches and the row is active.
    lookup_resp = SimpleNamespace(
        status_code=200,
        json=lambda: {"data": [{"id": "inv-existing", "number": number}]},
        text="",
    )
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[post_resp, lookup_resp],
    ):
        result = invoice_ninja.create_invoice(rec, bi)
    assert result.external_id == "inv-existing"


# -- P8 rework: archive_invoice + cancel_invoice HTTP shapes (F, G) --


@override_settings(**INVOICE_NINJA)
def test_archive_invoice_posts_to_bulk_archive():
    """archive_invoice('abc') must POST /invoices/bulk with
    {'action':'archive','ids':['abc']}. Expected RED: function absent."""
    from apps.integrations import invoice_ninja

    fake = SimpleNamespace(status_code=200, json=lambda: {}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=fake
    ) as m:
        invoice_ninja.archive_invoice("IN-ABC-1")

    call_kwargs = m.call_args.kwargs
    assert call_kwargs["json"]["action"] == "archive"
    assert call_kwargs["json"]["ids"] == ["IN-ABC-1"]
    assert "/invoices/bulk" in m.call_args.args[1]


@override_settings(**INVOICE_NINJA)
def test_cancel_invoice_posts_to_bulk_cancel_with_reason():
    """cancel_invoice('abc', 'reason') must POST /invoices/bulk with
    {'action':'cancel','ids':['abc'],'reason':'reason'}. Expected RED."""
    from apps.integrations import invoice_ninja

    fake = SimpleNamespace(status_code=200, json=lambda: {}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=fake
    ) as m:
        invoice_ninja.cancel_invoice("IN-SENT-1", "Pārtraukta dalība")

    call_kwargs = m.call_args.kwargs
    assert call_kwargs["json"]["action"] == "cancel"
    assert call_kwargs["json"]["ids"] == ["IN-SENT-1"]
    assert call_kwargs["json"]["reason"] == "Pārtraukta dalība"
    assert "/invoices/bulk" in m.call_args.args[1]


@override_settings(**INVOICE_NINJA)
def test_archive_invoice_auth_error_maps():
    """archive_invoice auth failure (401) maps to AuthError."""
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformAuthError

    fake = SimpleNamespace(status_code=401, json=lambda: {}, text="nope")
    with patch(
        "apps.integrations.invoice_ninja.requests.request", return_value=fake
    ):
        with pytest.raises(InvoicePlatformAuthError):
            invoice_ninja.archive_invoice("IN-ABC-1")


@override_settings(**INVOICE_NINJA)
def test_cancel_invoice_timeout_maps_to_transient():
    """cancel_invoice timeout maps to TransientError."""
    from apps.integrations import invoice_ninja
    from apps.integrations.invoice_platform import InvoicePlatformTransientError

    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=requests.Timeout("t"),
    ):
        with pytest.raises(InvoicePlatformTransientError):
            invoice_ninja.cancel_invoice("IN-SENT-1", "reason")


# -- P13: ensure_client sends separate first_name / last_name in contacts --


@override_settings(**INVOICE_NINJA)
def test_ensure_client_posts_name_parts_in_contacts(db):
    """ensure_client must send contacts[0].first_name and contacts[0].last_name separately."""
    from apps.integrations import invoice_ninja
    from tests.support import make_guardian

    guardian = make_guardian(
        first_name="Anna Marija",
        family_name="Ozola",
        email="anna@example.com",
    )
    lookup = SimpleNamespace(status_code=200, json=lambda: {"data": []}, text="")
    created = SimpleNamespace(status_code=200, json=lambda: {"id": "client-99"}, text="")
    with patch(
        "apps.integrations.invoice_ninja.requests.request",
        side_effect=[lookup, created],
    ) as m:
        result = invoice_ninja.ensure_client(guardian)

    assert result.external_id == "client-99"
    body = m.call_args_list[1].kwargs["json"]
    assert body["name"] == "Anna Marija Ozola"
    assert body["custom_value1"] == str(guardian.pk)
    assert body["contacts"] == [
        {
            "first_name": "Anna Marija",
            "last_name": "Ozola",
            "email": "anna@example.com",
        }
    ]

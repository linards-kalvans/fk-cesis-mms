import pytest
from decimal import Decimal
from datetime import date

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, full_price, season="2026/2027", payment_mode=None):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    kwargs = {}
    if payment_mode is not None:
        kwargs["payment_mode"] = payment_mode
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season=season,
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        is_full_price=full_price,
        sibling_discount_percent_applied=Decimal("0.00") if full_price else Decimal("50.00"),
        **kwargs,
    )


def _invoice(rec, due_date):
    from apps.billing.models import BillingInvoice

    return BillingInvoice.objects.create(
        billing_record=rec, sequence=1, due_date=due_date, amount=rec.final_amount,
    )


def test_sibling_discount_note_uses_percent(active_plan, guardian):
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=False)
    assert messages.sibling_discount_note(rec) == "Ietverta 50% atlaide"


def test_sibling_discount_note_fractional_percent(active_plan, guardian):
    from apps.billing import messages
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Pēteris", guardian=guardian)
    rec = BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("200.01"),
        is_full_price=False,
        sibling_discount_percent_applied=Decimal("33.33"),
    )
    assert messages.sibling_discount_note(rec) == "Ietverta 33.33% atlaide"


def test_product_name(active_plan):
    from apps.billing import messages

    assert messages.product_name(active_plan) == "Biedra maksa 2026/2027"


def test_error_message_fallback():
    from apps.billing import messages

    assert messages.get_invoice_error_message("auth_failed").startswith("Invoice Ninja")
    assert messages.get_invoice_error_message("totally-unknown") == messages._INVOICE_GENERIC


def test_payment_status_labels_latvian():
    from apps.billing.messages import PAYMENT_STATUS_LABELS

    assert PAYMENT_STATUS_LABELS["unpaid"] == "Nav apmaksāts"
    assert PAYMENT_STATUS_LABELS["partial"] == "Daļēji apmaksāts"
    assert PAYMENT_STATUS_LABELS["paid"] == "Apmaksāts"
    assert PAYMENT_STATUS_LABELS[""] == "—"


def test_invoice_public_note_installment_period_from_due_date(active_plan, guardian):
    """Installments line comes from the invoice due_date, example:
    2027-09-20 -> 'Maksājums par 2027. gada septembri'."""
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=True)
    inv = _invoice(rec, date(2027, 9, 20))
    note = messages.invoice_public_note(rec, inv)
    assert note == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2027. gada septembri"
    )


@pytest.mark.parametrize(
    ("due_date", "expected_period"),
    [
        (date(2027, 1, 20), "Maksājums par 2027. gada janvāri"),
        (date(2027, 2, 20), "Maksājums par 2027. gada februāri"),
        (date(2027, 3, 20), "Maksājums par 2027. gada martu"),
        (date(2027, 4, 20), "Maksājums par 2027. gada aprīli"),
        (date(2027, 5, 20), "Maksājums par 2027. gada maiju"),
        (date(2027, 6, 20), "Maksājums par 2027. gada jūniju"),
        (date(2027, 7, 20), "Maksājums par 2027. gada jūliju"),
        (date(2027, 8, 20), "Maksājums par 2027. gada augustu"),
        (date(2027, 9, 20), "Maksājums par 2027. gada septembri"),
        (date(2027, 10, 20), "Maksājums par 2027. gada oktobri"),
        (date(2027, 11, 20), "Maksājums par 2027. gada novembri"),
        (date(2027, 12, 20), "Maksājums par 2027. gada decembri"),
    ],
)
def test_invoice_public_note_installment_period_month_names(
    active_plan, guardian, due_date, expected_period
):
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=True)
    inv = _invoice(rec, due_date)
    note = messages.invoice_public_note(rec, inv)
    assert expected_period in note
    assert note.count("\n") == 1  # heading + period, no discount line


def test_invoice_public_note_upfront_period_normalized_season(active_plan, guardian):
    """Upfront period line: 'Maksājums par 2026./2027. gada sezonu'."""
    from apps.billing import messages
    from apps.billing.models import BillingRecord

    rec = _record(
        active_plan, guardian, full_price=True,
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
    )
    inv = _invoice(rec, date(2027, 9, 20))
    note = messages.invoice_public_note(rec, inv)
    assert note == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2026./2027. gada sezonu"
    )


@pytest.mark.parametrize(
    ("season",),
    [
        ("2027/2028",),      # plain
        ("2027./2028.",),    # already correctly formatted
        ("2027./2028..",),   # malformed double terminal dot
    ],
)
def test_invoice_public_note_upfront_period_season_forms(active_plan, guardian, season):
    """All three approved season inputs normalize to exactly one trailing dot
    per part: 'Maksājums par 2027./2028. gada sezonu' — the final text never
    contains '2027./2028.. gada'."""
    from apps.billing import messages
    from apps.billing.models import BillingRecord

    rec = _record(
        active_plan, guardian, full_price=True, season=season,
        payment_mode=BillingRecord.PaymentMode.UPFRONT,
    )
    inv = _invoice(rec, date(2027, 9, 20))
    note = messages.invoice_public_note(rec, inv)
    assert "Maksājums par 2027./2028. gada sezonu" in note
    assert "2027./2028.. gada" not in note


def test_invoice_public_note_discounted_third_line(active_plan, guardian):
    """Discounted record keeps the sibling-discount message as an exact
    newline-separated third line."""
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=False)
    inv = _invoice(rec, date(2027, 9, 20))
    note = messages.invoice_public_note(rec, inv)
    assert note == (
        "Futbola treniņu un spēļu nodrošināšana — Jānis — 2026/2027\n"
        "Maksājums par 2027. gada septembri\n"
        "Ietverta 50% atlaide"
    )


def test_invoice_public_note_full_price_has_no_discount_line(active_plan, guardian):
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=True)
    inv = _invoice(rec, date(2027, 9, 20))
    note = messages.invoice_public_note(rec, inv)
    assert note.count("\n") == 1
    assert "atlaide" not in note



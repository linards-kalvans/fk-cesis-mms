import pytest
from decimal import Decimal

pytestmark = pytest.mark.django_db


def _record(active_plan, guardian, full_price):
    from apps.members.models import Member
    from apps.billing.models import BillingRecord

    member = Member.objects.create(full_name="Jānis", guardian=guardian)
    return BillingRecord.objects.create(
        member=member, plan=active_plan, season="2026/2027",
        base_amount=Decimal("300.00"), final_amount=Decimal("300.00"),
        is_full_price=full_price,
        sibling_discount_percent_applied=Decimal("0.00") if full_price else Decimal("50.00"),
    )


def test_invoice_line_label(active_plan, guardian):
    from apps.billing import messages

    rec = _record(active_plan, guardian, full_price=True)
    assert messages.invoice_line_label(rec) == "Biedra maksa — Jānis — 2026/2027"


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

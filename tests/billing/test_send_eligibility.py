"""is_invoice_due_to_send — pure eligibility predicate (date + draft state)."""

import datetime
from types import SimpleNamespace

from apps.billing.services import is_invoice_due_to_send


def _inv(due_date, external_status="created", external_invoice_id="inv-1"):
    return SimpleNamespace(
        due_date=due_date,
        external_status=external_status,
        external_invoice_id=external_invoice_id,
    )


def test_eligible_on_first_of_due_month():
    today = datetime.date(2026, 9, 1)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is True


def test_not_eligible_last_day_of_prior_month():
    today = datetime.date(2026, 8, 31)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is False


def test_eligible_mid_month_current_month_signup():
    today = datetime.date(2026, 9, 10)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is True


def test_eligible_overdue_catch_up():
    today = datetime.date(2026, 11, 5)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20)), today) is True


def test_not_eligible_when_already_sent():
    today = datetime.date(2026, 9, 1)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20), external_status="sent"), today) is False


def test_not_eligible_without_external_id():
    today = datetime.date(2026, 9, 1)
    assert is_invoice_due_to_send(_inv(datetime.date(2026, 9, 20), external_invoice_id=""), today) is False

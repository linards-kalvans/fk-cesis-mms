"""8-step pipeline derivation."""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from apps.admin_hub.pipeline import (
    build_pipeline,
    current_step,
    load_pipeline_objects,
    pipeline_progress,
)

pytestmark = pytest.mark.django_db


def _states(steps):
    return {step.key: step.state for step in steps}


def test_pipeline_always_has_eight_ordered_steps(submitted_application):
    steps = build_pipeline(load_pipeline_objects(submitted_application))
    assert len(steps) == 8
    assert [step.number for step in steps] == list(range(1, 9))
    assert [step.key for step in steps] == [
        "verify",
        "approve",
        "agreement",
        "handover",
        "signed",
        "plan",
        "invoices",
        "next_season",
    ]


def test_submitted_application_is_on_step_one(submitted_application):
    steps = build_pipeline(load_pipeline_objects(submitted_application))
    states = _states(steps)
    assert states["verify"] == "current"
    assert states["approve"] == "available"
    assert states["agreement"] == "locked"
    assert pipeline_progress(steps) == (0, 8)
    assert current_step(steps).key == "verify"


def test_draft_application_has_nothing_available(draft_application):
    states = _states(build_pipeline(load_pipeline_objects(draft_application)))
    assert states["verify"] == "locked"
    assert states["approve"] == "locked"


def test_approved_application_completes_steps_one_and_two(approved_application):
    steps = build_pipeline(load_pipeline_objects(approved_application))
    states = _states(steps)
    assert states["verify"] == "done"
    assert states["approve"] == "done"
    done, total = pipeline_progress(steps)
    assert done >= 2
    assert total == 8


def test_sent_agreement_completes_handover(approved_application):
    from django.utils import timezone

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["agreement"] == "done"
    assert states["handover"] == "done"
    assert states["signed"] == "current"


def test_signed_agreement_completes_step_five(approved_application):
    from django.utils import timezone

    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at", "signed_at"])

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["signed"] == "done"


def test_plan_step_needs_both_plan_and_first_month(approved_application, default_plan):
    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.billing_plan = default_plan
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month"])

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["plan"] != "done", "a plan without a first month is not finished"

    agreement.first_billing_month = "2026-09"
    agreement.save(update_fields=["first_billing_month"])
    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["plan"] == "done"


def test_invoices_step_is_done_only_when_every_invoice_is_pushed(
    approved_application, default_plan
):
    from apps.billing.models import BillingInvoice, BillingRecord

    member = approved_application.approved_member
    record = BillingRecord.objects.create(
        member=member,
        plan=default_plan,
        season=default_plan.season,
        base_amount=Decimal("300.00"),
        final_amount=Decimal("300.00"),
    )
    first = BillingInvoice.objects.create(
        billing_record=record,
        sequence=1,
        due_date=datetime.date(2026, 9, 20),
        amount=Decimal("150.00"),
    )
    BillingInvoice.objects.create(
        billing_record=record,
        sequence=2,
        due_date=datetime.date(2026, 10, 20),
        amount=Decimal("150.00"),
        external_invoice_id="IN-2",
    )

    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["invoices"] != "done", "one un-pushed invoice blocks the step"

    first.external_invoice_id = "IN-1"
    first.save(update_fields=["external_invoice_id"])
    states = _states(build_pipeline(load_pipeline_objects(approved_application)))
    assert states["invoices"] == "done"


def test_only_one_step_is_current(approved_application):
    steps = build_pipeline(load_pipeline_objects(approved_application))
    assert [s.state for s in steps].count("current") <= 1

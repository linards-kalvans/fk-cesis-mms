"""P8: Agreement lifecycle service tests.

Tests record_minor_amendment, start_material_amendment, and discontinue_agreement
function signatures, guards, and side effects. These tests import functions that
do not exist yet — expected RED phase.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core import mail

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    mark_agreement_sent,
    mark_agreement_signed,
    void_agreement,
)
from apps.core.models import AuditEvent


pytestmark = pytest.mark.django_db


@pytest.fixture
def staff_user(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(
        username="staff_user", email="staff@example.test", is_staff=True
    )


@pytest.fixture
def signed_agreement(agreement_member, staff_user, default_plan):
    """A signed, current agreement for the test member.

    ``default_plan`` makes ``create_agreement_for_member`` preselect a
    ``billing_plan`` on the new agreement so the P9 signing guard passes.
    """
    agreement = create_agreement_for_member(
        agreement_member, Agreement.SigningPath.PAPER
    )
    mark_agreement_sent(agreement, staff_user)
    mark_agreement_signed(agreement, staff_user)
    return agreement


# -- record_minor_amendment --


def test_record_minor_amendment_function_exists():
    from apps.agreements.services import record_minor_amendment  # noqa: F401


def test_minor_amendment_creates_lifecycle_event(signed_agreement, staff_user):
    """record_minor_amendment creates a lifecycle event and does not change state."""
    from apps.agreements.services import record_minor_amendment

    record_minor_amendment(signed_agreement, staff_user, "Nomainīts e-pasts")

    signed_agreement.refresh_from_db()
    # State stays signed
    assert signed_agreement.state == Agreement.State.SIGNED
    # Lifecycle event created
    event = signed_agreement.lifecycle_events.latest("created_at")
    assert event.event_type == "minor_amendment"
    assert event.note == "Nomainīts e-pasts"
    assert event.actor_label == staff_user.email


def test_minor_amendment_sends_no_email(signed_agreement, staff_user):
    """Minor amendment must NOT send an email to the parent."""
    from apps.agreements.services import record_minor_amendment

    mail.outbox.clear()
    record_minor_amendment(signed_agreement, staff_user, "Labojums")

    assert len(mail.outbox) == 0


def test_minor_amendment_records_audit(signed_agreement, staff_user):
    """record_minor_amendment must record an audit event."""
    from apps.agreements.services import record_minor_amendment

    before = AuditEvent.objects.count()
    record_minor_amendment(signed_agreement, staff_user, "Labojums")

    assert AuditEvent.objects.count() == before + 1
    event = AuditEvent.objects.latest("created_at")
    assert event.action == str(AuditEvent.Action.AGREEMENT_MINOR_AMENDED)


def test_minor_amendment_requires_signed(signed_agreement, staff_user):
    """Only signed agreements can have minor amendments."""
    from apps.agreements.services import record_minor_amendment

    # Override state to generated
    signed_agreement.state = Agreement.State.GENERATED
    signed_agreement.save(update_fields=["state"])

    with pytest.raises(ValueError):
        record_minor_amendment(signed_agreement, staff_user, "Labojums")


# -- start_material_amendment --


def test_start_material_amendment_function_exists():
    from apps.agreements.services import start_material_amendment  # noqa: F401


def test_material_amendment_supersedes_old_and_creates_new(
    signed_agreement, agreement_member, staff_user
):
    """start_material_amendment sets old to superseded/is_current=False and
    creates a new generated current agreement."""
    from apps.agreements.services import start_material_amendment

    old_id = signed_agreement.id

    new_agreement = start_material_amendment(
        signed_agreement, staff_user, "Būtiskas izmaiņas nosacījumos"
    )

    signed_agreement.refresh_from_db()
    assert signed_agreement.state == Agreement.State.SUPERSEDED
    assert signed_agreement.is_current is False

    assert new_agreement.pk != old_id
    assert new_agreement.state == Agreement.State.GENERATED
    assert new_agreement.is_current is True
    assert new_agreement.member_id == agreement_member.id


def test_material_amendment_requires_signed_agreement(signed_agreement, staff_user):
    """Must raise ValueError for non-signed agreements."""
    from apps.agreements.services import start_material_amendment

    # Force to void
    void_agreement(signed_agreement, staff_user, "test")

    with pytest.raises(ValueError):
        start_material_amendment(signed_agreement, staff_user, "Mēģinājums")


def test_material_amendment_records_audit(signed_agreement, staff_user):
    from apps.agreements.services import start_material_amendment

    before = AuditEvent.objects.count()
    start_material_amendment(signed_agreement, staff_user, "Būtiskas izmaiņas")

    # Expect at least AGREEMENT_MATERIAL_AMENDMENT_STARTED and AGREEMENT_SUPERSEDED
    events = AuditEvent.objects.filter(created_at__gt=signed_agreement.created_at)
    actions = {e.action for e in events}
    assert str(AuditEvent.Action.AGREEMENT_MATERIAL_AMENDMENT_STARTED) in actions
    assert str(AuditEvent.Action.AGREEMENT_SUPERSEDED) in actions


def test_material_amendment_creates_lifecycle_events(signed_agreement, staff_user):
    from apps.agreements.services import start_material_amendment

    start_material_amendment(signed_agreement, staff_user, "Būtiskas izmaiņas")

    signed_agreement.refresh_from_db()
    # Old agreement has superseded lifecycle event
    events = signed_agreement.lifecycle_events.all()
    event_types = {e.event_type for e in events}
    assert "superseded" in event_types
    assert "material_amendment_started" in event_types


def test_material_amendment_assigns_new_agreement_number(
    signed_agreement, staff_user
):
    """The new current agreement must carry its own immutable agreement number
    (different from the superseded one's)."""
    from django.utils import timezone

    from apps.agreements.services import start_material_amendment

    old_number = signed_agreement.agreement_number
    assert old_number  # baseline: existing fixture already has one

    new_agreement = start_material_amendment(
        signed_agreement, staff_user, "Būtiskas izmaiņas"
    )

    year = timezone.localtime(new_agreement.generated_at).year
    assert new_agreement.agreement_number is not None
    assert new_agreement.agreement_number != old_number
    assert new_agreement.agreement_number == f"FKC-{year}-002"


# -- discontinue_agreement --


def test_discontinue_agreement_function_exists():
    from apps.agreements.services import discontinue_agreement  # noqa: F401


def test_discontinue_agreement_requires_signed_current(signed_agreement, staff_user):
    """discontinue_agreement must raise ValueError when agreement is not signed."""
    from apps.agreements.services import discontinue_agreement

    # Force to generated
    signed_agreement.state = Agreement.State.GENERATED
    signed_agreement.save(update_fields=["state"])

    with pytest.raises(ValueError):
        discontinue_agreement(
            signed_agreement,
            staff_user,
            effective_date=date(2026, 9, 1),
            reason="Pārcelšanās",
            selected_invoice_ids=[],
        )


def test_discontinue_agreement_sets_agreement_and_member(
    signed_agreement, staff_user, agreement_member
):
    """discontinue_agreement sets agreement state to discontinued and member
    to discontinued with effective date, reason, and timestamp."""
    from apps.agreements.services import discontinue_agreement

    # Wire member to the agreement (fixture agreement member is separate from
    # the Member fixture — skip re-creating, just use agreement_member).
    # signed_agreement already points to agreement_member via create_agreement_for_member.
    discontinue_agreement(
        signed_agreement,
        staff_user,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[],
    )

    signed_agreement.refresh_from_db()
    assert signed_agreement.state == Agreement.State.DISCONTINUED
    assert signed_agreement.is_current is True  # remains current per spec

    member = signed_agreement.member
    member.refresh_from_db()
    assert member.status == member.Status.DISCONTINUED
    assert str(member.discontinued_effective_date) == "2026-09-01"
    assert member.discontinuation_reason == "Pārcelšanās"
    assert member.discontinued_at is not None


def test_discontinue_agreement_creates_lifecycle_event(
    signed_agreement, staff_user
):
    from apps.agreements.services import discontinue_agreement

    discontinue_agreement(
        signed_agreement,
        staff_user,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[],
    )

    event = signed_agreement.lifecycle_events.filter(
        event_type="discontinued"
    ).first()
    assert event is not None
    assert event.note == "Pārcelšanās"
    assert str(event.effective_date) == "2026-09-01"


def test_discontinue_agreement_sends_email(signed_agreement, staff_user):
    from apps.agreements.services import discontinue_agreement

    mail.outbox.clear()
    discontinue_agreement(
        signed_agreement,
        staff_user,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[],
    )

    assert len(mail.outbox) == 1
    email = mail.outbox[0]
    assert "Pārcelšanās" in email.body
    assert "2026-09-01" in email.body


def test_discontinue_agreement_records_audit(signed_agreement, staff_user):
    from apps.agreements.services import discontinue_agreement

    before = AuditEvent.objects.count()
    discontinue_agreement(
        signed_agreement,
        staff_user,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[],
    )

    assert AuditEvent.objects.count() == before + 1
    event = AuditEvent.objects.latest("created_at")
    assert event.action == str(AuditEvent.Action.MEMBER_DISCONTINUED)


def test_discontinue_agreement_is_atomic(signed_agreement, staff_user):
    """If a post-billing mutation fails, billing/agreement/member changes must
    all roll back together."""
    from decimal import Decimal
    from unittest.mock import patch

    from apps.agreements.models import Agreement, AgreementLifecycleEvent
    from apps.agreements.services import discontinue_agreement
    from apps.billing.models import BillingInvoice, BillingRecord, MembershipPlan
    from apps.members.models import Member

    member = signed_agreement.member
    plan = MembershipPlan.objects.create(
        name="Atomic Plan",
        season="2026/2027",
        annual_amount=Decimal("300.00"),
        is_active=True,
    )
    # Reuse the draft record the signing signal already created (P9
    # preselects ``default_plan``); update it to CONFIRMED on the test plan.
    record, _ = BillingRecord.objects.update_or_create(
        member=member,
        season=plan.season,
        defaults=dict(
            plan=plan,
            base_amount=plan.annual_amount,
            final_amount=plan.annual_amount,
            status=BillingRecord.Status.CONFIRMED,
        ),
    )
    invoice = BillingInvoice.objects.create(
        billing_record=record,
        sequence=0,
        due_date="2026-09-20",
        amount=Decimal("30.00"),
    )

    with patch.object(
        AgreementLifecycleEvent.objects,
        "create",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError):
            discontinue_agreement(
                signed_agreement,
                staff_user,
                effective_date=date(2026, 9, 1),
                reason="Pārcelšanās",
                selected_invoice_ids=[invoice.pk],
            )

    invoice.refresh_from_db()
    signed_agreement.refresh_from_db()
    member.refresh_from_db()
    assert invoice.cancelled_at is None
    assert signed_agreement.state == Agreement.State.SIGNED
    assert member.status == Member.Status.ACTIVE
    assert not AgreementLifecycleEvent.objects.filter(
        agreement=signed_agreement, event_type="discontinued"
    ).exists()

"""Audit events for agreement state transitions (P7 audit baseline)."""

from __future__ import annotations

import pytest

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    mark_agreement_sent,
    mark_agreement_signed,
    void_agreement,
)
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_mark_agreement_sent_records_audit_event(agreement_member, actor):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.PAPER)
    mark_agreement_sent(a, actor=actor)

    event = AuditEvent.objects.get(action=AuditEvent.Action.AGREEMENT_SENT)
    assert event.actor == actor
    assert event.target_type == "agreement"
    assert event.target_id == str(a.pk)


def test_mark_agreement_signed_via_webhook_records_system_event(
    agreement_member, actor, default_plan
):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.PAPER)
    mark_agreement_sent(a, actor=actor)
    mark_agreement_signed(a, actor=None)

    event = AuditEvent.objects.get(action=AuditEvent.Action.AGREEMENT_SIGNED)
    assert event.actor is None
    assert event.actor_label == "system: docuseal_webhook"
    assert event.target_type == "agreement"
    assert event.target_id == str(a.pk)


def test_void_agreement_records_audit_event(agreement_member, actor):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.PAPER)
    void_agreement(a, actor, "test reason")

    event = AuditEvent.objects.get(action=AuditEvent.Action.AGREEMENT_VOIDED)
    assert event.actor == actor
    assert event.target_type == "agreement"
    assert event.target_id == str(a.pk)

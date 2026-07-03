"""P8: Agreement lifecycle model tests — new states + AgreementLifecycleEvent."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def test_agreement_has_superseded_state():
    """Agreement.State must include SUPERSEDED and DISCONTINUED."""
    from apps.agreements.models import Agreement

    assert hasattr(Agreement.State, "SUPERSEDED")
    assert Agreement.State.SUPERSEDED == "superseded"
    assert hasattr(Agreement.State, "DISCONTINUED")
    assert Agreement.State.DISCONTINUED == "discontinued"


def test_agreement_state_choices_include_new():
    from apps.agreements.models import Agreement

    values = {v for v, _ in Agreement.State.choices}
    assert "superseded" in values
    assert "discontinued" in values


def test_lifecycle_event_model_exists():
    """AgreementLifecycleEvent must exist and be importable."""
    from apps.agreements.models import AgreementLifecycleEvent  # noqa: F401


def test_lifecycle_event_event_type_choices():
    from apps.agreements.models import AgreementLifecycleEvent

    assert hasattr(AgreementLifecycleEvent, "EventType")
    assert hasattr(AgreementLifecycleEvent.EventType, "MINOR_AMENDMENT")
    assert hasattr(AgreementLifecycleEvent.EventType, "MATERIAL_AMENDMENT_STARTED")
    assert hasattr(AgreementLifecycleEvent.EventType, "SUPERSEDED")
    assert hasattr(AgreementLifecycleEvent.EventType, "DISCONTINUED")


def test_lifecycle_event_has_expected_fields():
    """AgreementLifecycleEvent must carry the fields from the design spec."""
    from apps.agreements.models import AgreementLifecycleEvent

    assert hasattr(AgreementLifecycleEvent, "agreement")
    assert hasattr(AgreementLifecycleEvent, "event_type")
    assert hasattr(AgreementLifecycleEvent, "note")
    assert hasattr(AgreementLifecycleEvent, "effective_date")
    assert hasattr(AgreementLifecycleEvent, "actor_label")
    assert hasattr(AgreementLifecycleEvent, "metadata")
    assert hasattr(AgreementLifecycleEvent, "created_at")


def test_lifecycle_event_creation(agreement_guardian, agreement_member):
    """AgreementLifecycleEvent can be created via ORM."""
    from apps.agreements.models import Agreement, AgreementLifecycleEvent

    agreement = Agreement.objects.create(
        member=agreement_member,
        state=Agreement.State.SIGNED,
        generated_at="2026-06-01T12:00:00Z",
        signed_at="2026-06-01T13:00:00Z",
    )
    event = AgreementLifecycleEvent.objects.create(
        agreement=agreement,
        event_type=AgreementLifecycleEvent.EventType.MINOR_AMENDMENT,
        note="Nomainīts vecāka e-pasts.",
        actor_label="admin@klubs.test",
    )
    assert event.pk is not None
    assert event.agreement_id == agreement.id
    assert event.event_type == "minor_amendment"
    assert event.note == "Nomainīts vecāka e-pasts."
    assert event.effective_date is None

"""Unit tests for apps.admin_hub.timeline.build_agreement_timeline.

Pure-function tests — no HTTP, no view. `agreement` fixtures come straight
from `approved_application` (tests/admin_hub/conftest.py), which already
gives a real, persisted Agreement row so `.lifecycle_events` is a real
queryset, not a mock.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.admin_hub.timeline import TimelineEntry, build_agreement_timeline
from apps.agreements.models import Agreement, AgreementLifecycleEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def agreement(approved_application):
    """A freshly generated agreement: only `generated_at` set."""
    agreement = approved_application.approved_member.agreements.get(is_current=True)
    agreement.sent_at = None
    agreement.signed_at = None
    agreement.voided_at = None
    agreement.save(update_fields=["sent_at", "signed_at", "voided_at"])
    return agreement


def test_only_generated_at_yields_a_single_entry(agreement):
    timeline = build_agreement_timeline(agreement)

    assert timeline == [
        TimelineEntry(when=agreement.generated_at, label="Sagatavots"),
    ]


def test_generated_sent_signed_merge_and_sort_newest_first(agreement):
    # generated_at is whatever the fixture happened to set at creation time
    # (effectively "now"), so it must be pushed further into the past than
    # sent_at/signed_at here — otherwise it would itself be the newest
    # timestamp and the assertion below would be testing the wrong order.
    now = timezone.now()
    agreement.generated_at = now - timezone.timedelta(days=3)
    agreement.sent_at = now - timezone.timedelta(days=2)
    agreement.signed_at = now - timezone.timedelta(days=1)
    agreement.save(update_fields=["generated_at", "sent_at", "signed_at"])

    timeline = build_agreement_timeline(agreement)

    assert [entry.label for entry in timeline] == [
        "Parakstīts",
        "Nosūtīts parakstīšanai",
        "Sagatavots",
    ]
    assert [entry.when for entry in timeline] == [
        agreement.signed_at,
        agreement.sent_at,
        agreement.generated_at,
    ]


def test_voided_entry_carries_the_void_reason_as_detail(agreement):
    agreement.voided_at = timezone.now()
    agreement.void_reason = "Novecojis"
    agreement.save(update_fields=["voided_at", "void_reason"])

    timeline = build_agreement_timeline(agreement)

    voided = [entry for entry in timeline if entry.label == "Atcelts"]
    assert len(voided) == 1
    assert voided[0].detail == "Novecojis"


def test_null_timestamps_yield_no_entry(agreement):
    """`agreement` already has sent_at/signed_at/voided_at cleared — only
    the generated_at entry should be present, never a synthesised one for
    a stage that never happened."""
    timeline = build_agreement_timeline(agreement)

    labels = {entry.label for entry in timeline}
    assert labels == {"Sagatavots"}


def test_merges_lifecycle_event_rows(agreement):
    event = AgreementLifecycleEvent.objects.create(
        agreement=agreement,
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED,
        actor_label="hub_reviewer",
    )

    timeline = build_agreement_timeline(agreement)

    matches = [entry for entry in timeline if entry.label == "Dalība pārtraukta"]
    assert len(matches) == 1
    assert matches[0].detail == "hub_reviewer"
    assert matches[0].when == event.created_at
    # The event was created strictly after the agreement's own generated_at,
    # so it must sort to the front.
    assert timeline[0] == matches[0]


def test_equal_timestamps_break_ties_deterministically(agreement):
    """Two entries sharing the exact same instant must always come out in
    the same order across repeated calls, never depending on however the
    underlying sort happens to break the tie that particular time."""
    same = agreement.generated_at
    agreement.sent_at = same
    agreement.save(update_fields=["sent_at"])

    first = build_agreement_timeline(agreement)
    second = build_agreement_timeline(agreement)

    assert first == second
    tied = [entry.label for entry in first if entry.when == same]
    # Canonical build order is generated-stage before sent-stage; a stable
    # sort preserves that order for equal keys instead of reversing it.
    assert tied == ["Sagatavots", "Nosūtīts parakstīšanai"]


def test_agreement_state_labels_match_the_domain_choices(agreement):
    """Guards against the timeline module's labels drifting from
    Agreement.State's own display strings, which the rest of this page
    (the "Stāvoklis" row) already shows."""
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.voided_at = timezone.now()
    agreement.save(update_fields=["sent_at", "signed_at", "voided_at"])

    timeline = build_agreement_timeline(agreement)

    labels = {entry.label for entry in timeline}
    assert labels == {
        Agreement.State.GENERATED.label,
        Agreement.State.SENT.label,
        Agreement.State.SIGNED.label,
        Agreement.State.VOID.label,
    }

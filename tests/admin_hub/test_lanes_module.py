"""The lane derivation lives in apps.members.lanes; family_hub re-exports it."""

from __future__ import annotations

import pytest

from apps.members import family_hub, lanes

pytestmark = pytest.mark.django_db


_MOVED_NAMES = (
    "FamilyLaneStatus",
    "application_lane",
    "agreement_lane",
    "membership_lane",
    "billing_lane",
    "canonical_kit_size_label",
)


def test_lanes_module_exposes_the_moved_names():
    for name in _MOVED_NAMES:
        assert hasattr(lanes, name), f"apps.members.lanes is missing {name}"


def test_family_hub_re_exports_the_same_objects():
    """Existing imports from family_hub must keep working and resolve to the
    very same objects, so there is only one implementation."""
    for name in _MOVED_NAMES:
        assert getattr(family_hub, name) is getattr(lanes, name)


def test_family_hub_no_longer_defines_the_lanes_itself():
    """Guards against a copy-paste extraction that leaves both versions."""
    source = (
        __import__("pathlib").Path(family_hub.__file__).read_text(encoding="utf-8")
    )
    assert "def application_lane(" not in source
    assert "def agreement_lane(" not in source
    assert "def billing_lane(" not in source
    assert "class FamilyLaneStatus" not in source


def test_application_lane_behaviour_is_unchanged(submitted_application):
    lane = lanes.application_lane(submitted_application)
    assert lane.key == "application"
    assert lane.badge == "Iesniegts"
    assert lane.level == "pending"
    assert lane.next_action == "Apstiprināt"


def test_agreement_lane_handles_none():
    lane = lanes.agreement_lane(None)
    assert lane.key == "agreement"
    assert lane.level == "muted"


def test_draft_application_lane_is_muted(draft_application):
    lane = lanes.application_lane(draft_application)
    assert lane.badge == "Melnraksts"
    assert lane.level == "muted"

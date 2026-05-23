"""Tests for the central Latvian copy module used by P4 Slice C.

The module `apps.registrations.messages` exposes plain top-level string
constants for wizard gating, the consent gate, and the auto-save indicator.
These tests pin the shape (non-empty `str`, distinct messages, short badge
labels) and guard against English bleed-through.
"""

from __future__ import annotations

import pytest

from apps.registrations import messages

_REQUIRED_CONSTANTS = (
    "STEP_FIELD_REQUIRED",
    "STEP_FIELD_FORMAT",
    "CONSENT_REQUIRED",
    "SAVE_INDICATOR_SAVING",
    "SAVE_INDICATOR_SAVED",
    "SAVE_INDICATOR_ERROR",
)

# Common English words that must not appear in Latvian parent-facing copy.
_FORBIDDEN_ENGLISH = ("the ", "and ", "please ", "click ", "submit")


@pytest.mark.parametrize("name", _REQUIRED_CONSTANTS)
def test_constant_exists_and_is_non_empty_str(name: str) -> None:
    assert hasattr(messages, name), f"messages.{name} is missing"
    value = getattr(messages, name)
    assert isinstance(value, str), f"messages.{name} must be str, got {type(value)!r}"
    assert value.strip(), f"messages.{name} must be non-empty"


@pytest.mark.parametrize("name", _REQUIRED_CONSTANTS)
def test_constant_has_no_english_bleed(name: str) -> None:
    value = getattr(messages, name).lower()
    for token in _FORBIDDEN_ENGLISH:
        assert token not in value, (
            f"messages.{name} contains forbidden English token {token!r}: {value!r}"
        )


def test_inline_error_messages_are_distinct() -> None:
    assert (
        messages.STEP_FIELD_REQUIRED
        != messages.STEP_FIELD_FORMAT
        != messages.CONSENT_REQUIRED
    )
    # Explicit pairwise check (chained != only enforces neighbouring pairs).
    assert messages.STEP_FIELD_REQUIRED != messages.CONSENT_REQUIRED


def test_save_indicator_messages_are_distinct() -> None:
    assert (
        messages.SAVE_INDICATOR_SAVING
        != messages.SAVE_INDICATOR_SAVED
        != messages.SAVE_INDICATOR_ERROR
    )
    # Explicit pairwise check (chained != only enforces neighbouring pairs).
    assert messages.SAVE_INDICATOR_SAVING != messages.SAVE_INDICATOR_ERROR


@pytest.mark.parametrize(
    "name",
    ("SAVE_INDICATOR_SAVING", "SAVE_INDICATOR_SAVED", "SAVE_INDICATOR_ERROR"),
)
def test_save_indicator_labels_are_short(name: str) -> None:
    value = getattr(messages, name)
    assert len(value) <= 50, (
        f"messages.{name} is {len(value)} chars; must be <= 50 for the badge"
    )

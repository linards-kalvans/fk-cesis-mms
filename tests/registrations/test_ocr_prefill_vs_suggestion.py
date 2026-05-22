"""Unit tests for the prefill-vs-suggestion classifier.

P3.5 Phase 4 — `classify_field_action(current_value, ocr_value)` decides
whether OCR should prefill (empty field) or surface a suggestion chip
(non-empty field) or do nothing (already matches or no value).
"""

from __future__ import annotations

import pytest

from apps.registrations.presentation import classify_field_action


@pytest.mark.parametrize(
    "current,ocr,expected",
    [
        ("", "Anna", "prefill"),
        ("   ", "Anna", "prefill"),
        ("Anna", "Anna", "noop"),
        ("anna", "Anna", "noop"),
        ("Anna ", " Anna", "noop"),
        ("Janis", "Anna", "suggest"),
        ("", "", "noop"),
        ("   ", "", "noop"),
        ("Anna", "", "noop"),
    ],
)
def test_classify_field_action(current, ocr, expected):
    assert classify_field_action(current, ocr) == expected

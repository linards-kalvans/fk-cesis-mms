"""Unit tests for Latvian name normalization helper."""

import pytest

from apps.integrations.name_normalization import normalize_latvian_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("JĀNIS BĒRZIŅŠ", "Jānis Bērziņš"),
        ("jānis bērziņš", "Jānis Bērziņš"),
        ("BĒRZIŅŠ-KALNIŅŠ", "Bērziņš-Kalniņš"),
        ("ANNA MARIJA", "Anna Marija"),
        ("ŪLA", "Ūla"),
        ("VAN DER BERG", "van der Berg"),
        ("DE LA CRUZ", "de la Cruz"),
        ("VON TRAPP", "von Trapp"),
        ("VAN", "Van"),  # particle as the only/first token must capitalize.
        ("KALNIŅŠ-VAN-BERG", "Kalniņš-van-Berg"),
        ("  KRŪMIŅŠ   ", "Krūmiņš"),
        ("", ""),
        ("   ", ""),
        ("Jānis", "Jānis"),  # already normalized stays stable.
        ("ČUKČA-ĶĒNIŅŠ", "Čukča-Ķēniņš"),
    ],
)
def test_normalize_latvian_name(raw, expected):
    assert normalize_latvian_name(raw) == expected


def test_non_string_input_returns_empty_string():
    # Defensive: OCR payload values are always strings, but the helper should
    # not crash if callers pass None or a non-string.
    assert normalize_latvian_name(None) == ""  # type: ignore[arg-type]

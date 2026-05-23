"""Unit tests for OCR error-code → Latvian-message mapping."""

import pytest

from apps.integrations.ocr_messages import (
    OCR_ERROR_MESSAGES_LV,
    get_ocr_error_message,
)


KNOWN_CODES = (
    "provider_misconfigured",
    "auth_failed",
    "rate_limited",
    "request_timeout",
    "provider_unavailable",
    "invalid_response",
)


@pytest.mark.parametrize("code", KNOWN_CODES)
def test_every_known_code_has_a_latvian_message(code):
    assert code in OCR_ERROR_MESSAGES_LV
    msg = OCR_ERROR_MESSAGES_LV[code]
    assert isinstance(msg, str)
    assert msg  # non-empty
    # Latvian copy must not be a copy of the code itself.
    assert msg != code
    # Sanity: messages must end with a period or ellipsis (full sentence).
    assert msg.rstrip().endswith((".", "…"))


def test_get_returns_mapped_message_for_known_code():
    assert get_ocr_error_message("auth_failed") == OCR_ERROR_MESSAGES_LV["auth_failed"]


def test_get_returns_generic_fallback_for_unknown_code():
    message = get_ocr_error_message("totally_unknown_code")
    assert isinstance(message, str)
    assert message
    assert "manuāli" in message.lower() or "vēlāk" in message.lower()


def test_get_returns_generic_fallback_for_empty_code():
    assert get_ocr_error_message("") == get_ocr_error_message("unknown")

"""P3 follow-up — tiny-IDP runtime transport / config tests (red phase).

Scope: transport and config only. No dispatcher, document persistence,
registration workflow, or admin UI.

Target module: apps.integrations.tiny_idp

Canonical config names: TINY_IDP_API_URL, TINY_IDP_API_KEY.
No backward-compat expectations for OCR_API_URL / OCR_API_KEY.

Runtime expectations:
- Provider misconfiguration when required tiny-IDP settings are missing
- Successful request path against tiny-IDP transport boundary (mocked HTTP)
- Classified failure mapping: auth failure, rate limiting, timeout,
  provider unavailable, invalid response
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# Import exception classes from the production module.
# These must be defined in apps.integrations.tiny_idp.
from apps.integrations.tiny_idp import (
    AuthError,
    InvalidResponseError,
    ProviderMisconfigurationError,
    ProviderUnavailableError,
    RateLimitError,
    RequestTimeoutError,
)
from apps.integrations.ocr import OCRProviderMode, extract_document_data


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guardian_file():
    """Return a minimal guardian identity document blob."""
    return b"fake-guardian-id-bytes"


def _member_file():
    """Return a minimal member identity document blob."""
    return b"fake-member-id-bytes"


# Sample tiny-IDP JSON response used in mocked transport tests.
# Shape matches the real generic-id-document API (see apps/integrations/tiny_idp.py).
_SAMPLE_TINY_IDP_RESPONSE = {
    "success": True,
    "data": {
        "given_names": "Anna",
        "given_names_verified": True,
        "first_surname": "Bērziņa",
        "first_surname_verified": True,
        "personal_number": "010101-12345",
        "personal_number_verified": True,
        "document_number": "AB1234567",
        "document_number_verified": True,
        "issuing_authority": "MLP",
        "issuing_date": "2020-01-01",
        "issuing_date_verified": True,
        "expiry_date": "2030-01-01",
        "expiry_date_verified": True,
        "date_of_birth": "1980-01-01",
        "date_of_birth_verified": True,
    },
    "balance": 15.0,
    "cost": 0.005,
}


# ---------------------------------------------------------------------------
# Unit A — provider misconfiguration: missing TINY_IDP_API_URL
# ---------------------------------------------------------------------------


class TestProviderMisconfigurationMissingApiUrl:
    """When TINY_IDP_API_URL is missing, tiny-IDP mode must raise."""

    def test_missing_api_url_raises_error(self, settings):
        """TINY_IDP_API_URL absent → ProviderMisconfigurationError."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = None  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "fake-key"  # type: ignore[attr-defined]

        with pytest.raises(ProviderMisconfigurationError) as exc_info:
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

        assert "TINY_IDP_API_URL" in str(exc_info.value)

    def test_error_type_is_misconfiguration(self, settings):
        """The raised exception must be ProviderMisconfigurationError."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = None  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "fake-key"  # type: ignore[attr-defined]

        with pytest.raises(ProviderMisconfigurationError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )


# ---------------------------------------------------------------------------
# Unit A — provider misconfiguration: missing TINY_IDP_API_KEY
# ---------------------------------------------------------------------------


class TestProviderMisconfigurationMissingApiKey:
    """When TINY_IDP_API_KEY is missing, tiny-IDP mode must raise."""

    def test_missing_api_key_raises_error(self, settings):
        """TINY_IDP_API_KEY absent → ProviderMisconfigurationError."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = None  # type: ignore[attr-defined]

        with pytest.raises(ProviderMisconfigurationError) as exc_info:
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

        assert "TINY_IDP_API_KEY" in str(exc_info.value)

    def test_error_type_is_misconfiguration(self, settings):
        """The raised exception must be ProviderMisconfigurationError."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = None  # type: ignore[attr-defined]

        with pytest.raises(ProviderMisconfigurationError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )


# ---------------------------------------------------------------------------
# Unit A — provider misconfiguration: both missing
# ---------------------------------------------------------------------------


class TestProviderMisconfigurationBothMissing:
    """When both TINY_IDP_API_URL and TINY_IDP_API_KEY are missing,
    a misconfiguration error must still be raised."""

    def test_both_missing_raises_error(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = None  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = None  # type: ignore[attr-defined]

        with pytest.raises(ProviderMisconfigurationError) as exc_info:
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

        assert "TINY_IDP" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Unit A — no backward compatibility: OCR_API_URL / OCR_API_KEY ignored
# ---------------------------------------------------------------------------


class TestNoBackwardCompatOcrApiKeys:
    """Old config names OCR_API_URL / OCR_API_KEY must NOT satisfy tiny-IDP."""

    def test_ocr_api_url_does_not_satisfy_tiny_idp(self, settings):
        """Setting only OCR_API_URL should not bypass TINY_IDP_API_URL check."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.OCR_API_URL = "http://old-ocr.local"  # type: ignore[attr-defined]
        settings.OCR_API_KEY = "old-key"  # type: ignore[attr-defined]
        # Neutralize canonical tiny-IDP config so misconfiguration is certain
        settings.TINY_IDP_API_URL = ""  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = ""  # type: ignore[attr-defined]

        with pytest.raises(ProviderMisconfigurationError) as exc_info:
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

        assert "TINY_IDP_API_URL" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Unit B — successful request path: mocked HTTP transport
# ---------------------------------------------------------------------------


class TestSuccessfulRequestPath:
    """When config is valid and HTTP returns a 200 with JSON,
    the transport must call normalize_tiny_idp_response and return
    a valid OCRExtractionResult."""

    def test_successful_request_returns_valid_result(self, settings, monkeypatch):
        """Mock requests.post → 200 with valid JSON → normalized result."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _SAMPLE_TINY_IDP_RESPONSE
        mock_response.raise_for_status.return_value = None

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        result = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_guardian_file(),
            content_type="image/png",
        )

        assert result.subject == "guardian"
        assert result.person_fields.get("first_name") == "Anna"
        assert result.document_metadata.get("document_number") == "AB1234567"

    def test_successful_request_sends_api_key_header(self, settings, monkeypatch):
        """Transport must include TINY_IDP_API_KEY as Authorization header."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "secret-key-123"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _SAMPLE_TINY_IDP_RESPONSE
        mock_response.raise_for_status.return_value = None

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_guardian_file(),
            content_type="image/png",
        )

        call_kwargs = mock_requests.post.call_args
        headers = call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))
        assert headers.get("x-api-key") == "secret-key-123"

    def test_successful_request_sends_to_correct_url(self, settings, monkeypatch):
        """Transport must POST to TINY_IDP_API_URL."""
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local/v1/extract"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _SAMPLE_TINY_IDP_RESPONSE
        mock_response.raise_for_status.return_value = None

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_guardian_file(),
            content_type="image/png",
        )

        call_args = mock_requests.post.call_args
        called_url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", call_args[1].get("url", ""))
        assert called_url == "http://tiny-idp.local/v1/extract"


# ---------------------------------------------------------------------------
# Unit B — classified failure: auth failure (401/403)
# ---------------------------------------------------------------------------


class TestFailureAuthFailure:
    """HTTP 401/403 from tiny-IDP must map to AuthError."""

    def test_401_raises_auth_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "bad-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = Exception("401 Unauthorized")

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(AuthError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

    def test_403_raises_auth_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "forbidden-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.raise_for_status.side_effect = Exception("403 Forbidden")

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(AuthError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )


# ---------------------------------------------------------------------------
# Unit B — classified failure: rate limiting (429)
# ---------------------------------------------------------------------------


class TestFailureRateLimiting:
    """HTTP 429 from tiny-IDP must map to RateLimitError."""

    def test_429_raises_rate_limit_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status.side_effect = Exception("429 Too Many Requests")

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(RateLimitError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )


# ---------------------------------------------------------------------------
# Unit B — classified failure: timeout
# ---------------------------------------------------------------------------


class TestFailureTimeout:
    """Connection timeout from tiny-IDP must map to RequestTimeoutError.

    Uses built-in OSError (not requests.exceptions.Timeout) so the test
    does not depend on the requests package being installed.
    """

    def test_timeout_raises_timeout_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_requests = MagicMock()
        mock_requests.post.side_effect = OSError("Connection timed out")

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(RequestTimeoutError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )


# ---------------------------------------------------------------------------
# Unit B — classified failure: provider unavailable (connection refused)
# ---------------------------------------------------------------------------


class TestFailureProviderUnavailable:
    """Connection refused / network errors from tiny-IDP must map to
    ProviderUnavailableError.

    Uses built-in OSError (not requests.exceptions.ConnectionError) so the
    test does not depend on the requests package being installed.
    """

    def test_connection_refused_raises_unavailable_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_requests = MagicMock()
        mock_requests.post.side_effect = OSError("Connection refused")

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(ProviderUnavailableError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )


# ---------------------------------------------------------------------------
# Unit B — classified failure: invalid response (malformed JSON)
# ---------------------------------------------------------------------------


class TestFailureInvalidResponse:
    """Non-JSON or malformed response from tiny-IDP must map to
    InvalidResponseError."""

    def test_non_json_body_raises_invalid_response_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(InvalidResponseError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

    def test_empty_response_raises_invalid_response_error(self, settings, monkeypatch):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.TINY_IDP
        settings.TINY_IDP_API_URL = "http://tiny-idp.local"  # type: ignore[attr-defined]
        settings.TINY_IDP_API_KEY = "test-key"  # type: ignore[attr-defined]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON object could be decoded")

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        monkeypatch.setattr("apps.integrations.tiny_idp.requests", mock_requests)

        with pytest.raises(InvalidResponseError):
            extract_document_data(
                kind="guardian_identity",
                file_name="guardian.png",
                content=_guardian_file(),
                content_type="image/png",
            )

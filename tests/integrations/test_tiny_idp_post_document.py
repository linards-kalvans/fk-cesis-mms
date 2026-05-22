"""Unit tests for the tiny-IDP HTTP-only transport split (post_document)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.integrations.tiny_idp import (
    AuthError,
    InvalidResponseError,
    ProviderMisconfigurationError,
    ProviderUnavailableError,
    RateLimitError,
    RequestTimeoutError,
    post_document,
)


_SAMPLE_PAYLOAD = {
    "entities": [
        {
            "type": "person",
            "fields": {
                "first_name": "Anna",
                "last_name": "Bērziņa",
                "personal_id": "010180-12345",
                "date_of_birth": "1980-01-01",
            },
        }
    ],
    "document": {
        "document_number": "LV1234567",
        "issuer": "PMLP",
        "issuance_date": "2020-05-21",
        "expiry_date": "2030-05-21",
    },
    "confidence": {"first_name": 0.99},
    "flags": [],
    "model_version": "tinyidp-1.0.0",
}


@pytest.fixture
def tiny_idp_settings(settings):
    settings.TINY_IDP_API_URL = "https://tiny-idp.test/extract"
    settings.TINY_IDP_API_KEY = "test-key"
    return settings


def test_post_document_returns_raw_payload(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = _SAMPLE_PAYLOAD
    mock_response.raise_for_status = MagicMock()

    captured = {}

    def fake_post(url, files=None, headers=None, **kwargs):
        captured["url"] = url
        captured["files"] = files
        captured["headers"] = headers
        return mock_response

    monkeypatch.setattr("apps.integrations.tiny_idp.requests.post", fake_post)

    payload = post_document(
        file_name="doc.jpg",
        content=b"binary-content",
        content_type="image/jpeg",
    )

    assert payload == _SAMPLE_PAYLOAD
    assert captured["url"] == "https://tiny-idp.test/extract"
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["files"]["file"][0] == "doc.jpg"
    assert captured["files"]["file"][1] == b"binary-content"
    assert captured["files"]["file"][2] == "image/jpeg"


def test_post_document_raises_misconfig_when_url_missing(settings):
    settings.TINY_IDP_API_URL = ""
    settings.TINY_IDP_API_KEY = "key"

    with pytest.raises(ProviderMisconfigurationError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_auth_error(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.raise_for_status.side_effect = Exception("401 unauthorized")

    monkeypatch.setattr(
        "apps.integrations.tiny_idp.requests.post",
        lambda *a, **kw: mock_response,
    )

    with pytest.raises(AuthError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_rate_limit(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 429
    mock_response.raise_for_status.side_effect = Exception("429 rate limited")

    monkeypatch.setattr(
        "apps.integrations.tiny_idp.requests.post",
        lambda *a, **kw: mock_response,
    )

    with pytest.raises(RateLimitError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_timeout(tiny_idp_settings, monkeypatch):
    def raise_timeout(*a, **kw):
        raise OSError("connection timed out")

    monkeypatch.setattr("apps.integrations.tiny_idp.requests.post", raise_timeout)

    with pytest.raises(RequestTimeoutError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_unavailable(tiny_idp_settings, monkeypatch):
    def raise_conn(*a, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr("apps.integrations.tiny_idp.requests.post", raise_conn)

    with pytest.raises(ProviderUnavailableError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")


def test_post_document_classifies_invalid_response(tiny_idp_settings, monkeypatch):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.side_effect = ValueError("not json")

    monkeypatch.setattr(
        "apps.integrations.tiny_idp.requests.post",
        lambda *a, **kw: mock_response,
    )

    with pytest.raises(InvalidResponseError):
        post_document(file_name="x.jpg", content=b"x", content_type="image/jpeg")

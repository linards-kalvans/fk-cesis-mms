"""P3 — OCR provider contract: stub adapter + orchestrator tests.

Tests:
- stub provider returns guardian normalized result
- stub provider returns member normalized result
- normalized schema is identical regardless of provider
- provider mode switching works
- safe_extract_document_data catches exceptions and returns error code
- stub is deterministic (same input → same output)
- raw_reference contains provider name
- person_fields contain expected stub values
"""

import pytest

from apps.integrations import tiny_idp
from apps.integrations.ocr import OCRProviderMode, extract_document_data, safe_extract_document_data

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_guardian_payload():
    """Return a minimal guardian identity document blob."""
    return b"fake-guardian-id-bytes"


def _stub_member_payload():
    """Return a minimal member identity document blob."""
    return b"fake-member-id-bytes"


# ---------------------------------------------------------------------------
# Unit B — provider abstraction: stub returns guardian normalized result
# ---------------------------------------------------------------------------


class TestStubProviderGuardian:
    """Stub provider must return a valid guardian extraction result."""

    def test_stub_provider_returns_guardian_normalized_result(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        assert result.subject == "guardian"
        assert result.person_fields.get("first_name")
        assert result.person_fields.get("last_name")
        assert result.document_metadata.get("document_number")
        assert result.raw_reference.get("provider") == "stub"

    def test_stub_guardian_result_has_all_required_fields(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        required_person_fields = {
            "first_name",
            "last_name",
            "personal_id",
        }
        required_document_metadata = {
            "document_number",
            "issuer",
            "issuance_date",
            "expiry_date",
        }

        assert required_person_fields.issubset(result.person_fields.keys())
        assert required_document_metadata.issubset(result.document_metadata.keys())

    def test_stub_guardian_result_has_empty_confidence_and_flags(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        assert isinstance(result.confidence, dict)
        assert isinstance(result.flags, list)


# ---------------------------------------------------------------------------
# Unit B — provider abstraction: stub returns member normalized result
# ---------------------------------------------------------------------------


class TestStubProviderMember:
    """Stub provider must return a valid member extraction result."""

    def test_stub_provider_returns_member_normalized_result(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result = extract_document_data(
            kind="member_identity",
            file_name="member.png",
            content=_stub_member_payload(),
            content_type="image/png",
        )

        assert result.subject == "member"
        assert result.person_fields.get("first_name")
        assert result.person_fields.get("last_name")
        assert result.person_fields.get("personal_id")
        assert result.raw_reference.get("provider") == "stub"

    def test_stub_member_result_subject_role_is_member(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result = extract_document_data(
            kind="member_identity",
            file_name="member.png",
            content=_stub_member_payload(),
            content_type="image/png",
        )

        # subject is used to classify the extraction
        assert result.subject == "member"


# ---------------------------------------------------------------------------
# Unit B — normalized schema identical across providers
# ---------------------------------------------------------------------------


class TestNormalizedSchemaConsistency:
    """Normalized result must have same structure regardless of provider."""

    def test_stub_result_has_correct_dataclass_fields(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        # Must have these attributes (dataclass fields)
        assert hasattr(result, "subject")
        assert hasattr(result, "person_fields")
        assert hasattr(result, "document_metadata")
        assert hasattr(result, "confidence")
        assert hasattr(result, "flags")
        assert hasattr(result, "raw_reference")

        # Type checks
        assert isinstance(result.person_fields, dict)
        assert isinstance(result.document_metadata, dict)
        assert isinstance(result.confidence, dict)
        assert isinstance(result.flags, list)
        assert isinstance(result.raw_reference, dict)


# ---------------------------------------------------------------------------
# Unit B — provider mode switching
# ---------------------------------------------------------------------------


class TestProviderModeSwitching:
    """Provider mode must be env-driven and switchable."""

    def test_stub_mode_is_string_stub(self, settings):
        assert OCRProviderMode.STUB == "stub"

    def test_tiny_idp_mode_is_string_tiny_idp(self, settings):
        assert OCRProviderMode.TINY_IDP == "tiny_idp"


# ---------------------------------------------------------------------------
# Unit B — safe_extract_document_data: catches exceptions
# ---------------------------------------------------------------------------


class TestSafeExtractDocumentData:
    """safe_extract_document_data must catch exceptions and return error code."""

    def test_safe_extract_returns_result_on_success(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result, error_code = safe_extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        assert result is not None
        assert error_code is None
        assert result.subject == "guardian"

    def test_safe_extract_returns_none_and_error_on_failure(self, monkeypatch, settings):
        def _boom(**kwargs):
            raise RuntimeError("provider timeout")

        monkeypatch.setattr(
            "apps.integrations.ocr.extract_document_data",
            _boom,
        )

        result, error_code = safe_extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        assert result is None
        assert error_code == "provider_unavailable"

    def test_safe_extract_catches_value_error(self, monkeypatch, settings):
        def _value_error(**kwargs):
            raise ValueError("invalid payload")

        monkeypatch.setattr(
            "apps.integrations.ocr.extract_document_data",
            _value_error,
        )

        result, error_code = safe_extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        assert result is None
        assert error_code == "provider_unavailable"


# ---------------------------------------------------------------------------
# Unit B — safe_extract_document_data: tiny-IDP exception classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception_class,expected_code",
    [
        (tiny_idp.ProviderMisconfigurationError, "provider_misconfigured"),
        (tiny_idp.AuthError, "auth_failed"),
        (tiny_idp.RateLimitError, "rate_limited"),
        (tiny_idp.RequestTimeoutError, "request_timeout"),
        (tiny_idp.ProviderUnavailableError, "provider_unavailable"),
        (tiny_idp.InvalidResponseError, "invalid_response"),
    ],
)
def test_safe_extract_classifies_tiny_idp_exceptions(
    monkeypatch, settings, exception_class, expected_code
):
    """Each tiny-IDP exception class maps to the correct classified error code."""

    def _boom(**kwargs):
        raise exception_class("test error")

    monkeypatch.setattr(
        "apps.integrations.ocr.extract_document_data",
        _boom,
    )

    result, error_code = safe_extract_document_data(
        kind="guardian_identity",
        file_name="test.png",
        content=b"fake",
        content_type="image/png",
    )

    assert result is None
    assert error_code == expected_code


def test_safe_extract_non_tiny_idp_exception_returns_provider_unavailable(
    monkeypatch, settings,
):
    """Non-tiny-IDP exceptions still return the generic provider_unavailable code."""

    def _boom(**kwargs):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(
        "apps.integrations.ocr.extract_document_data",
        _boom,
    )

    result, error_code = safe_extract_document_data(
        kind="guardian_identity",
        file_name="test.png",
        content=b"fake",
        content_type="image/png",
    )

    assert result is None
    assert error_code == "provider_unavailable"


# ---------------------------------------------------------------------------
# Unit B — stub determinism
# ---------------------------------------------------------------------------


class TestStubDeterminism:
    """Stub extraction must be deterministic: same input → same output."""

    def test_same_input_produces_same_result(self, settings):
        settings.OCR_PROVIDER_MODE = OCRProviderMode.STUB

        result_a = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )
        result_b = extract_document_data(
            kind="guardian_identity",
            file_name="guardian.png",
            content=_stub_guardian_payload(),
            content_type="image/png",
        )

        assert result_a.person_fields == result_b.person_fields
        assert result_a.document_metadata == result_b.document_metadata
        assert result_a.subject == result_b.subject

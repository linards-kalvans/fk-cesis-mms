"""P3 — tiny-IDP adapter normalization tests.

Tests:
- normalize_tiny_idp_response parses guardian identity payload (real shape)
- normalize_tiny_idp_response parses member identity payload (real shape)
- empty-string fields are skipped (treated as "not extracted")
- raw_reference contains provider name
- person_fields map correctly from the real provider keys
- document_metadata maps correctly from the real provider keys
- success=false raises InvalidResponseError
"""

import pytest

from apps.integrations.tiny_idp import (
    InvalidResponseError,
    normalize_tiny_idp_response,
)

pytestmark = [pytest.mark.django_db, pytest.mark.external_contract]


# ---------------------------------------------------------------------------
# Fixtures — real tiny-IDP response shape (uppercase keys, no *_verified)
# ---------------------------------------------------------------------------


GUARDIAN_PAYLOAD_FIXTURE = {
    "success": True,
    "data": {
        "ISSUING_COUNTRY_NAME": "Latvia",
        "DOCUMENT_TYPE": "ID_CARD",
        "DOCUMENT_NUMBER": "AB1234567",
        "SURNAME": "Bērziņa",
        "GIVEN_NAME": "Anna",
        "NATIONALITY": "LVA",
        "GENDER": "F",
        "DATE_OF_BIRTH": "1980-01-01",
        "PERSONAL_ID": "010101-12345",
        "DATE_OF_ISSUE": "2020-01-01",
        "DATE_OF_EXPIRY": "2030-01-01",
    },
    "balance": 15.25,
    "cost": 0.005,
}


MEMBER_PAYLOAD_FIXTURE = {
    "success": True,
    "data": {
        "ISSUING_COUNTRY_NAME": "Latvia",
        "DOCUMENT_TYPE": "ID_CARD",
        "DOCUMENT_NUMBER": "CD9876543",
        "SURNAME": "Kalējs",
        "GIVEN_NAME": "Jānis",
        "NATIONALITY": "LVA",
        "GENDER": "M",
        "DATE_OF_BIRTH": "2001-01-25",
        "PERSONAL_ID": "010125-67890",
        "DATE_OF_ISSUE": "2023-06-15",
        "DATE_OF_EXPIRY": "2033-06-15",
    },
    "balance": 14.5,
    "cost": 0.005,
}


# Minimal: only a few fields populated; rest empty (means "not extracted").
MINIMAL_PAYLOAD_FIXTURE = {
    "success": True,
    "data": {
        "ISSUING_COUNTRY_NAME": "",
        "DOCUMENT_TYPE": "",
        "DOCUMENT_NUMBER": "ZZ0000001",
        "SURNAME": "User",
        "GIVEN_NAME": "Minimal",
        "NATIONALITY": "",
        "GENDER": "",
        "DATE_OF_BIRTH": "",
        "PERSONAL_ID": "010101-00001",
        "DATE_OF_ISSUE": "",
        "DATE_OF_EXPIRY": "",
    },
    "balance": 10.0,
    "cost": 0.005,
}


# ---------------------------------------------------------------------------
# Unit B — tiny-IDP normalization: guardian identity
# ---------------------------------------------------------------------------


class TestNormalizeGuardianIdentity:
    """normalize_tiny_idp_response must correctly parse guardian identity payloads."""

    def test_normalize_guardian_identity_subject(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.subject == "guardian"

    def test_normalize_guardian_identity_first_name(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["first_name"] == "Anna"

    def test_normalize_guardian_identity_last_name(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["last_name"] == "Bērziņa"

    def test_normalize_guardian_identity_personal_id(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["personal_id"] == "010101-12345"

    def test_normalize_guardian_identity_document_number(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.document_metadata["document_number"] == "AB1234567"

    def test_normalize_guardian_identity_issuance_date(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.document_metadata["issuance_date"] == "2020-01-01"

    def test_normalize_guardian_identity_expiry_date(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.document_metadata["expiry_date"] == "2030-01-01"

    def test_normalize_guardian_identity_date_of_birth(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["date_of_birth"] == "1980-01-01"

    def test_normalize_guardian_identity_issuer_not_in_metadata(self):
        """Current spec returns ISSUING_COUNTRY_NAME, not an issuer authority."""
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert "issuer" not in result.document_metadata

    def test_normalize_guardian_identity_confidence_empty(self):
        """Current spec exposes no per-field confidence."""
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.confidence == {}

    def test_normalize_guardian_identity_flags_empty(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.flags == []

    def test_normalize_guardian_identity_raw_reference(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.raw_reference["provider"] == "tiny_idp"
        assert result.raw_reference["provider_version"] == ""


# ---------------------------------------------------------------------------
# Unit B — tiny-IDP normalization: member identity
# ---------------------------------------------------------------------------


class TestNormalizeMemberIdentity:
    """normalize_tiny_idp_response must correctly parse member identity payloads."""

    def test_normalize_member_identity_subject(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.subject == "member"

    def test_normalize_member_identity_first_name(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["first_name"] == "Jānis"

    def test_normalize_member_identity_last_name(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["last_name"] == "Kalējs"

    def test_normalize_member_identity_personal_id(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["personal_id"] == "010125-67890"

    def test_normalize_member_identity_document_number(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.document_metadata["document_number"] == "CD9876543"

    def test_normalize_member_identity_flags_empty(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.flags == []


# ---------------------------------------------------------------------------
# Unit B — tiny-IDP normalization: minimal / missing fields
# ---------------------------------------------------------------------------


class TestNormalizeMinimalPayload:
    """Normalizer must skip empty strings and not crash on absent optional fields."""

    def test_minimal_payload_keeps_populated_fields(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["first_name"] == "Minimal"
        assert result.person_fields["last_name"] == "User"
        assert result.person_fields["personal_id"] == "010101-00001"
        assert result.document_metadata["document_number"] == "ZZ0000001"

    def test_minimal_payload_skips_empty_dates(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert "issuance_date" not in result.document_metadata
        assert "expiry_date" not in result.document_metadata
        assert "date_of_birth" not in result.person_fields

    def test_minimal_payload_confidence_empty(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.confidence == {}

    def test_minimal_payload_flags_empty(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.flags == []


# ---------------------------------------------------------------------------
# Unit B — tiny-IDP normalization: success=false
# ---------------------------------------------------------------------------


class TestSuccessFalse:
    """Failed extractions (success=false) must raise InvalidResponseError."""

    def test_success_false_raises_invalid_response(self):
        payload = {"success": False, "cost": 0}

        with pytest.raises(InvalidResponseError):
            normalize_tiny_idp_response(
                kind="guardian_identity",
                payload=payload,
            )

    def test_missing_data_field_raises_invalid_response(self):
        payload = {"success": True, "balance": 10.0, "cost": 0.005}

        with pytest.raises(InvalidResponseError):
            normalize_tiny_idp_response(
                kind="guardian_identity",
                payload=payload,
            )

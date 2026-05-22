"""P3 — tiny-IDP adapter normalization tests.

Tests target the real generic-id-document API response shape:
    {"success": bool, "data": {...}, "balance": float, "cost": float}

Coverage:
- normalize_tiny_idp_response parses guardian identity payload (real shape)
- normalize_tiny_idp_response parses member identity payload (real shape)
- confidence is derived from *_verified flags (1.0 / 0.0)
- flags are always [] (no analogue in real API)
- raw_reference contains provider name; provider_version is ""
- person_fields map correctly from provider keys
- document_metadata maps correctly from provider keys
- empty-string values are skipped
- missing optional fields do not crash normalizer
- success=false raises InvalidResponseError
- missing "data" raises InvalidResponseError
"""

import pytest

from apps.integrations.tiny_idp import (
    InvalidResponseError,
    normalize_tiny_idp_response,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures — real tiny-IDP response shape
# ---------------------------------------------------------------------------


GUARDIAN_PAYLOAD_FIXTURE = {
    "success": True,
    "data": {
        "document_type": "ID_CARD",
        "document_type_verified": True,
        "document_number": "AB1234567",
        "document_number_verified": True,
        "nationality": "LVA",
        "nationality_verified": True,
        "given_names": "Anna",
        "given_names_verified": True,
        "first_surname": "Bērziņa",
        "first_surname_verified": True,
        "second_surname": "",
        "second_surname_verified": True,
        "date_of_birth": "1980-01-01",
        "date_of_birth_verified": True,
        "place_of_birth": "Riga",
        "gender": "F",
        "gender_verified": True,
        "issuing_date": "2020-01-01",
        "issuing_date_verified": True,
        "expiry_date": "2030-01-01",
        "expiry_date_verified": False,
        "issuing_authority": "MLP",
        "personal_number": "010101-12345",
        "personal_number_verified": True,
        "mrz_detected": True,
        "address_line_1": "",
        "address_line_2": "",
        "address_city": "",
        "address_state": "",
        "address_country": "",
        "address_zip_code": "",
    },
    "balance": 15.25,
    "cost": 0.005,
}


MEMBER_PAYLOAD_FIXTURE = {
    "success": True,
    "data": {
        "document_type": "ID_CARD",
        "document_type_verified": True,
        "document_number": "CD9876543",
        "document_number_verified": True,
        "nationality": "LVA",
        "nationality_verified": True,
        "given_names": "Jānis",
        "given_names_verified": True,
        "first_surname": "Kalējs",
        "first_surname_verified": False,
        "second_surname": "",
        "second_surname_verified": True,
        "date_of_birth": "2001-01-25",
        "date_of_birth_verified": True,
        "place_of_birth": "",
        "gender": "M",
        "gender_verified": True,
        "issuing_date": "2023-06-15",
        "issuing_date_verified": True,
        "expiry_date": "2033-06-15",
        "expiry_date_verified": True,
        "issuing_authority": "MLP",
        "personal_number": "010125-67890",
        "personal_number_verified": True,
        "mrz_detected": True,
        "address_line_1": "",
        "address_line_2": "",
        "address_city": "",
        "address_state": "",
        "address_country": "",
        "address_zip_code": "",
    },
    "balance": 14.5,
    "cost": 0.005,
}


# Minimal: only required-ish fields present, others empty (means "not extracted").
MINIMAL_PAYLOAD_FIXTURE = {
    "success": True,
    "data": {
        "document_type": "",
        "document_type_verified": True,
        "document_number": "ZZ0000001",
        "document_number_verified": True,
        "nationality": "",
        "nationality_verified": True,
        "given_names": "Minimal",
        "given_names_verified": True,
        "first_surname": "User",
        "first_surname_verified": True,
        "second_surname": "",
        "second_surname_verified": True,
        "date_of_birth": "",
        "date_of_birth_verified": True,
        "place_of_birth": "",
        "gender": "",
        "gender_verified": True,
        "issuing_date": "",
        "issuing_date_verified": True,
        "expiry_date": "",
        "expiry_date_verified": True,
        "issuing_authority": "",
        "personal_number": "010101-00001",
        "personal_number_verified": True,
        "mrz_detected": False,
        "address_line_1": "",
        "address_line_2": "",
        "address_city": "",
        "address_state": "",
        "address_country": "",
        "address_zip_code": "",
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

    def test_normalize_guardian_identity_issuer(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.document_metadata["issuer"] == "MLP"

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

    def test_normalize_guardian_identity_confidence_from_verified_flags(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        # verified=True → 1.0; verified=False → 0.0
        assert result.confidence["first_name"] == 1.0
        assert result.confidence["last_name"] == 1.0
        assert result.confidence["personal_id"] == 1.0
        assert result.confidence["document_number"] == 1.0
        assert result.confidence["issuance_date"] == 1.0
        assert result.confidence["expiry_date"] == 0.0
        assert result.confidence["date_of_birth"] == 1.0

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

    def test_normalize_member_identity_last_name_low_confidence(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.confidence["last_name"] == 0.0


# ---------------------------------------------------------------------------
# Unit B — tiny-IDP normalization: minimal / missing fields
# ---------------------------------------------------------------------------


class TestNormalizeMinimalPayload:
    """Normalizer must skip empty strings and not crash on absent optional fields."""

    def test_minimal_payload_skips_empty_issuer(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["first_name"] == "Minimal"
        assert result.document_metadata["document_number"] == "ZZ0000001"
        # issuing_authority is "" — must be skipped, not stored as empty.
        assert "issuer" not in result.document_metadata

    def test_minimal_payload_skips_empty_dates(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert "issuance_date" not in result.document_metadata
        assert "expiry_date" not in result.document_metadata
        assert "date_of_birth" not in result.person_fields

    def test_minimal_payload_skips_confidence_for_absent_fields(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        # Empty value means we don't emit confidence for that field.
        assert "issuer" not in result.confidence
        assert "issuance_date" not in result.confidence
        assert "expiry_date" not in result.confidence
        assert "date_of_birth" not in result.confidence
        # But fields with values do get confidence.
        assert result.confidence["first_name"] == 1.0
        assert result.confidence["personal_id"] == 1.0

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

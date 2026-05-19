"""P3 — tiny-IDP adapter normalization tests.

Tests:
- normalize_tiny_idp_response parses guardian identity payload
- normalize_tiny_idp_response parses member identity payload
- confidence and flags are passed through
- raw_reference contains provider name and version
- person_fields map correctly from provider keys
- document_metadata maps correctly from provider keys
- missing optional fields do not crash normalizer
"""

import pytest

from apps.integrations.tiny_idp import normalize_tiny_idp_response

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures — sample tiny-IDP responses
# ---------------------------------------------------------------------------


GUARDIAN_PAYLOAD_FIXTURE = {
    "entities": [
        {
            "type": "person",
            "fields": {
                "first_name": "Anna",
                "last_name": "Bērziņa",
                "personal_id": "010101-12345",
            },
        }
    ],
    "document": {
        "document_number": "AB1234567",
        "issuer": "MLP",
        "issuance_date": "2020-01-01",
        "expiry_date": "2030-01-01",
    },
    "confidence": {
        "first_name": 0.98,
        "last_name": 0.97,
        "personal_id": 0.99,
    },
    "flags": [
        {"type": "low_confidence", "field": "last_name", "threshold": 0.90}
    ],
    "model_version": "tiny-idp-v2.1.0",
}


MEMBER_PAYLOAD_FIXTURE = {
    "entities": [
        {
            "type": "person",
            "fields": {
                "first_name": "Jānis",
                "last_name": "Kalējs",
                "personal_id": "010125-67890",
            },
        }
    ],
    "document": {
        "document_number": "CD9876543",
        "issuer": "MLP",
        "issuance_date": "2023-06-15",
        "expiry_date": "2033-06-15",
    },
    "confidence": {
        "first_name": 0.95,
        "personal_id": 0.99,
    },
    "flags": [],
    "model_version": "tiny-idp-v2.1.0",
}


MINIMAL_PAYLOAD_FIXTURE = {
    "entities": [
        {
            "type": "person",
            "fields": {
                "first_name": "Minimal",
                "last_name": "User",
                "personal_id": "010101-00001",
            },
        }
    ],
    "document": {
        "document_number": "ZZ0000001",
    },
    "model_version": "tiny-idp-v2.0.0",
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

    def test_normalize_guardian_identity_confidence_passed_through(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.confidence == GUARDIAN_PAYLOAD_FIXTURE["confidence"]

    def test_normalize_guardian_identity_flags_passed_through(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert len(result.flags) == 1
        assert result.flags[0]["type"] == "low_confidence"

    def test_normalize_guardian_identity_raw_reference(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=GUARDIAN_PAYLOAD_FIXTURE,
        )

        assert result.raw_reference["provider"] == "tiny_idp"
        assert result.raw_reference["provider_version"] == "tiny-idp-v2.1.0"


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

    def test_normalize_member_identity_empty_flags(self):
        result = normalize_tiny_idp_response(
            kind="member_identity",
            payload=MEMBER_PAYLOAD_FIXTURE,
        )

        assert result.flags == []


# ---------------------------------------------------------------------------
# Unit B — tiny-IDP normalization: missing optional fields
# ---------------------------------------------------------------------------


class TestNormalizeMinimalPayload:
    """Normalizer must not crash when optional fields are missing."""

    def test_minimal_payload_no_issuer(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.person_fields["first_name"] == "Minimal"
        assert result.document_metadata["document_number"] == "ZZ0000001"
        # issuer is missing — should be None or absent
        assert result.document_metadata.get("issuer") is None

    def test_minimal_payload_no_confidence(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.confidence == {}

    def test_minimal_payload_no_flags_key(self):
        result = normalize_tiny_idp_response(
            kind="guardian_identity",
            payload=MINIMAL_PAYLOAD_FIXTURE,
        )

        assert result.flags == []

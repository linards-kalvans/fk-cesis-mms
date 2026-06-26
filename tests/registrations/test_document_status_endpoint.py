"""OCR status polling endpoint tests.

P3.5 Phase 3 — GET /applications/<id>/documents/<doc_id>/status/.
"""

from __future__ import annotations

import json

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.documents.models import Document, DocumentExtraction
from apps.documents.ocr import encrypt_json
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


_FERNET_KEY_FIXTURE = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="


def _verified_client(account: ParentAccount) -> Client:
    client = Client()
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.id
    session.save()
    return client


def _make_application(account: ParentAccount) -> RegistrationApplication:
    app: RegistrationApplication = RegistrationApplication.objects.create(
        parent_account=account,
        member_birth_date="2025-01-01",
    )
    return app


def _make_document(
    app: RegistrationApplication,
    kind: str = "guardian_identity",
    ocr_status: str = "pending",
    ocr_error_code: str = "",
) -> Document:
    doc: Document = Document.objects.create(
        application=app,
        kind=kind,
        file=ContentFile(b"x", name="x.png"),
        original_filename="x.png",
        content_type="image/png",
        file_size=1,
        ocr_status=ocr_status,
        ocr_error_code=ocr_error_code,
    )
    return doc


def _url(app_id: int, doc_id: int) -> str:
    url: str = reverse(
        "registrations:document-ocr-status",
        kwargs={"application_id": app_id, "document_id": doc_id},
    )
    return url


def test_status_returns_pending_state(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="pending@example.com", phone="+37120000001"
    )
    app = _make_application(account)
    doc = _make_document(app)
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload == {
        "ocr_status": "pending",
        "extracted_fields": {},
    }


def test_status_returns_failed_with_error_code(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="failed@example.com", phone="+37120000002"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        ocr_status=Document.OcrStatus.FAILED,
        ocr_error_code="auth_failed",
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "failed"
    assert payload["ocr_error_code"] == "auth_failed"


def test_status_returns_extracted_fields_on_completed_guardian(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="done-g@example.com", phone="+37120000003"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        kind="guardian_identity",
        ocr_status=Document.OcrStatus.COMPLETED,
    )
    encrypted_payload = encrypt_json(
        {
            "subject": "guardian",
            "person_fields": {
                "first_name": "Anna",
                "last_name": "Bērziņa",
                "personal_id": "010180-12345",
            },
            "document_metadata": {"document_number": "LV1234567"},
            "confidence": {},
            "flags": [],
            "raw_reference": {"provider": "tiny_idp"},
        }
    )
    encrypted_summary = encrypt_json("first_name: Anna")
    DocumentExtraction.objects.create(
        document=doc,
        subject_role="guardian",
        provider="tiny_idp",
        extraction_schema_version="v1",
        encrypted_payload=encrypted_payload,
        encrypted_summary=encrypted_summary,
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "completed"
    assert payload["extracted_fields"] == {
        "guardian_full_name": "Anna Bērziņa",
        "guardian_personal_id": "010180-12345",
    }


def test_status_returns_extracted_fields_on_completed_member(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="done-m@example.com", phone="+37120000004"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        kind="member_identity",
        ocr_status=Document.OcrStatus.COMPLETED,
    )
    encrypted_payload = encrypt_json(
        {
            "subject": "member",
            "person_fields": {
                "first_name": "Janis",
                "last_name": "Kalvāns",
                "personal_id": "010125-99999",
            },
            "document_metadata": {},
            "confidence": {},
            "flags": [],
            "raw_reference": {"provider": "tiny_idp"},
        }
    )
    DocumentExtraction.objects.create(
        document=doc,
        subject_role="member",
        provider="tiny_idp",
        extraction_schema_version="v1",
        encrypted_payload=encrypted_payload,
        encrypted_summary=encrypt_json(""),
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "completed"
    assert payload["extracted_fields"] == {
        "member_full_name": "Janis Kalvāns",
        "member_personal_id": "010125-99999",
    }


def test_status_returns_404_for_non_owner():
    owner = ParentAccount.objects.create(
        email="o@example.com", phone="+37120000005"
    )
    intruder = ParentAccount.objects.create(
        email="i@example.com", phone="+37120000006"
    )
    app = _make_application(owner)
    doc = _make_document(app)
    client = _verified_client(intruder)

    response = client.get(_url(app.id, doc.id))
    assert response.status_code in {403, 404}


def test_status_returns_404_when_document_belongs_to_other_application():
    account = ParentAccount.objects.create(
        email="other-app@example.com", phone="+37120000007"
    )
    app1 = _make_application(account)
    app2 = RegistrationApplication.objects.create(
        parent_account=account,
        member_birth_date="2025-01-01",
    )
    doc = _make_document(app1)
    client = _verified_client(account)

    response = client.get(_url(app2.id, doc.id))
    assert response.status_code in {403, 404}


def test_status_returns_latvian_error_message_when_failed(settings):
    """FAILED status response must carry ocr_error_message in Latvian."""
    from apps.integrations.ocr_messages import OCR_ERROR_MESSAGES_LV

    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="failed-message@example.com", phone="+37120000010"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        ocr_status=Document.OcrStatus.FAILED,
        ocr_error_code="auth_failed",
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))

    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "failed"
    assert payload["ocr_error_code"] == "auth_failed"
    assert payload["ocr_error_message"] == OCR_ERROR_MESSAGES_LV["auth_failed"]


def test_status_emits_fallback_message_for_unknown_failure_code(settings):
    """Unknown error code still produces a usable Latvian fallback message."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="failed-fallback@example.com", phone="+37120000011"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        ocr_status=Document.OcrStatus.FAILED,
        ocr_error_code="totally_bogus_value_not_in_mapping",
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))

    payload = json.loads(response.content)
    assert "ocr_error_message" in payload
    assert "manuāli" in payload["ocr_error_message"].lower()


def test_status_emits_message_when_failed_without_error_code(settings):
    """A FAILED document with no recorded code still gets the fallback message."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="failed-no-code@example.com", phone="+37120000012"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        ocr_status=Document.OcrStatus.FAILED,
        ocr_error_code="",  # worker crashed before classifying
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))

    payload = json.loads(response.content)
    assert "ocr_error_message" in payload
    assert payload["ocr_error_message"]
    # ocr_error_code should be absent because the existing payload only adds it
    # when truthy.
    assert "ocr_error_code" not in payload


def test_status_omits_error_message_when_pending(settings):
    """ocr_error_message must NOT appear on pending payloads."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="pending-message@example.com", phone="+37120000013"
    )
    app = _make_application(account)
    doc = _make_document(app, ocr_status=Document.OcrStatus.PENDING)
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))

    payload = json.loads(response.content)
    assert payload["ocr_status"] == "pending"
    assert "ocr_error_message" not in payload


def test_status_omits_error_message_when_completed(settings):
    """ocr_error_message must NOT appear on completed payloads."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="completed-message@example.com", phone="+37120000014"
    )
    app = _make_application(account)
    # Re-use the same pattern as the existing completed test — no extraction
    # is needed because we only care about the absence of the message field.
    doc = _make_document(app, ocr_status=Document.OcrStatus.COMPLETED)
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))

    payload = json.loads(response.content)
    assert payload["ocr_status"] == "completed"
    assert "ocr_error_message" not in payload


def test_status_normalizes_uppercase_guardian_name(settings):
    """Guardian identity COMPLETED: raw uppercase OCR payload → normalized name.

    The endpoint reads person_fields first_name / last_name from the
    encrypted payload. Without normalization, the toast / prefill receives
    ``"JOHN SMITH"`` instead of ``"John Smith"``.  This test pins the
    Latvian title-case contract.
    """
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="uppercase-g@example.com", phone="+37120000020"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        kind="guardian_identity",
        ocr_status=Document.OcrStatus.COMPLETED,
    )
    encrypted_payload = encrypt_json(
        {
            "subject": "guardian",
            "person_fields": {
                "first_name": "JOHN",
                "last_name": "SMITH",
                "personal_id": "010180-12345",
            },
            "document_metadata": {},
            "confidence": {},
            "flags": [],
            "raw_reference": {"provider": "tiny_idp"},
        }
    )
    DocumentExtraction.objects.create(
        document=doc,
        subject_role="guardian",
        provider="tiny_idp",
        extraction_schema_version="v1",
        encrypted_payload=encrypted_payload,
        encrypted_summary=encrypt_json("first_name: JOHN"),
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "completed"
    assert payload["extracted_fields"]["guardian_full_name"] == "John Smith"
    assert payload["extracted_fields"]["guardian_personal_id"] == "010180-12345"


def test_status_normalizes_uppercase_member_name(settings):
    """Member identity COMPLETED: raw uppercase OCR payload → normalized name.

    Ensures the shared code path covers member documents too.
    """
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    account = ParentAccount.objects.create(
        email="uppercase-m@example.com", phone="+37120000021"
    )
    app = _make_application(account)
    doc = _make_document(
        app,
        kind="member_identity",
        ocr_status=Document.OcrStatus.COMPLETED,
    )
    encrypted_payload = encrypt_json(
        {
            "subject": "member",
            "person_fields": {
                "first_name": "JANE",
                "last_name": "DOE",
                "personal_id": "010125-99999",
            },
            "document_metadata": {},
            "confidence": {},
            "flags": [],
            "raw_reference": {"provider": "tiny_idp"},
        }
    )
    DocumentExtraction.objects.create(
        document=doc,
        subject_role="member",
        provider="tiny_idp",
        extraction_schema_version="v1",
        encrypted_payload=encrypted_payload,
        encrypted_summary=encrypt_json("first_name: JANE"),
    )
    client = _verified_client(account)

    response = client.get(_url(app.id, doc.id))
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "completed"
    assert payload["extracted_fields"]["member_full_name"] == "Jane Doe"
    assert payload["extracted_fields"]["member_personal_id"] == "010125-99999"

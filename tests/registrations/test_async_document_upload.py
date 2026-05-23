"""Async document upload endpoint tests.

P3.5 Phase 2 — POST /applications/<id>/documents/ creates the Document
record, enqueues the OCR job, and returns a JSON payload immediately.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


_FERNET_KEY_FIXTURE = "Y14NJYvOnvr0FLs41cks5xUkk8j95dwHcT3xsp-LkbY="


def _png_bytes(size: int = 64) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * size


def _verified_client(account: ParentAccount) -> Client:
    client = Client()
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.id
    session.save()
    return client


def _make_application(account: ParentAccount) -> RegistrationApplication:
    app: RegistrationApplication = RegistrationApplication.objects.create(
        parent_account=account,
        guardian_email=account.email,
        guardian_full_name="Test Parent",
        guardian_personal_id="010101-12345",
        guardian_phone="+37120000001",
        guardian_declared_address="Riga 1",
        member_full_name="Test Child",
        member_personal_id="010125-12345",
        member_birth_date="2025-01-01",
    )
    return app


def test_post_creates_document_and_enqueues_ocr(settings):
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = ParentAccount.objects.create(
        email="upload@example.com", phone="+37120000001"
    )
    app = _make_application(account)
    client = _verified_client(account)

    enqueued: list[int] = []

    def _spy(document_id: int) -> None:
        enqueued.append(document_id)

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )

    with patch(
        "apps.registrations.views.enqueue_ocr_job",
        side_effect=_spy,
    ):
        response = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={"kind": "guardian_identity", "file": upload},
        )

    assert response.status_code == 201
    payload = json.loads(response.content)
    assert payload["kind"] == "guardian_identity"
    assert payload["ocr_status"] == "pending"
    assert isinstance(payload["document_id"], int)

    doc = Document.objects.get(pk=payload["document_id"])
    assert doc.application_id == app.id
    assert doc.kind == "guardian_identity"
    assert doc.ocr_status == Document.OcrStatus.PENDING
    assert enqueued == [doc.id]


def test_post_rejects_unverified_session():
    account = ParentAccount.objects.create(
        email="anon@example.com", phone="+37120000002"
    )
    app = _make_application(account)
    client = Client()  # no verified session

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code in {302, 401, 403, 404}


def test_post_rejects_non_owner():
    owner = ParentAccount.objects.create(
        email="owner@example.com", phone="+37120000003"
    )
    intruder = ParentAccount.objects.create(
        email="intruder@example.com", phone="+37120000004"
    )
    app = _make_application(owner)
    client = _verified_client(intruder)

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code in {403, 404}
    assert not Document.objects.filter(application=app).exists()


def test_post_rejects_invalid_kind():
    account = ParentAccount.objects.create(
        email="kind@example.com", phone="+37120000005"
    )
    app = _make_application(account)
    client = _verified_client(account)

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "not_a_real_kind", "file": upload},
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert payload["error"] == "invalid_kind"


def test_post_rejects_missing_file():
    account = ParentAccount.objects.create(
        email="missing@example.com", phone="+37120000006"
    )
    app = _make_application(account)
    client = _verified_client(account)

    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity"},
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert payload["error"] == "missing_file"


def test_post_rejects_oversized_file(settings):
    settings.DOCUMENT_UPLOAD_MAX_BYTES = 1024

    account = ParentAccount.objects.create(
        email="big@example.com", phone="+37120000007"
    )
    app = _make_application(account)
    client = _verified_client(account)

    upload = SimpleUploadedFile(
        "big.png", _png_bytes(size=2048), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code == 413
    payload = json.loads(response.content)
    assert payload["error"] == "file_too_large"


def test_post_rejects_disallowed_content_type():
    account = ParentAccount.objects.create(
        email="ct@example.com", phone="+37120000008"
    )
    app = _make_application(account)
    client = _verified_client(account)

    upload = SimpleUploadedFile(
        "doc.exe", b"\x00\x01\x02", content_type="application/x-msdownload"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code == 400
    payload = json.loads(response.content)
    assert payload["error"] == "invalid_content_type"


def test_post_rejects_missing_csrf_when_enforced():
    """With CSRF enforcement, a token-less POST must be rejected."""
    account = ParentAccount.objects.create(
        email="csrf@example.com", phone="+37120000009"
    )
    app = _make_application(account)
    client = Client(enforce_csrf_checks=True)
    session = client.session
    session[PARENT_ACCOUNT_SESSION_KEY] = account.id
    session.save()

    upload = SimpleUploadedFile(
        "id.png", _png_bytes(), content_type="image/png"
    )
    response = client.post(
        reverse(
            "registrations:async-document-upload",
            kwargs={"application_id": app.id},
        ),
        data={"kind": "guardian_identity", "file": upload},
    )
    assert response.status_code == 403


def test_post_replaces_prior_active_document_of_same_kind(settings):
    """Re-upload soft-deletes the prior active doc of the same kind."""
    settings.OCR_ENCRYPTION_KEY = _FERNET_KEY_FIXTURE
    settings.OCR_PROVIDER_MODE = "tiny_idp"

    account = ParentAccount.objects.create(
        email="replace@example.com", phone="+37120000010"
    )
    app = _make_application(account)
    client = _verified_client(account)

    # First upload
    with patch("apps.registrations.views.enqueue_ocr_job"):
        first = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={
                "kind": "guardian_identity",
                "file": SimpleUploadedFile(
                    "a.png", _png_bytes(), content_type="image/png"
                ),
            },
        )
    assert first.status_code == 201
    first_id = json.loads(first.content)["document_id"]

    # Second upload of the same kind
    with patch("apps.registrations.views.enqueue_ocr_job"):
        second = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={
                "kind": "guardian_identity",
                "file": SimpleUploadedFile(
                    "b.png", _png_bytes(), content_type="image/png"
                ),
            },
        )
    assert second.status_code == 201
    second_id = json.loads(second.content)["document_id"]
    assert second_id != first_id

    # Prior should be soft-deleted
    prior = Document.objects.get(pk=first_id)
    assert prior.deleted_at is not None
    current = Document.objects.get(pk=second_id)
    assert current.deleted_at is None


def test_post_member_portrait_does_not_enqueue_ocr():
    account = ParentAccount.objects.create(
        email="portrait@example.com", phone="+37120000011"
    )
    app = _make_application(account)
    client = _verified_client(account)

    enqueued: list[int] = []

    upload = SimpleUploadedFile(
        "portrait.png", _png_bytes(), content_type="image/png"
    )
    with patch(
        "apps.registrations.views.enqueue_ocr_job",
        side_effect=lambda did: enqueued.append(did),
    ):
        response = client.post(
            reverse(
                "registrations:async-document-upload",
                kwargs={"application_id": app.id},
            ),
            data={"kind": "member_portrait", "file": upload},
        )

    assert response.status_code == 201
    payload = json.loads(response.content)
    assert payload["ocr_status"] == "not_requested"
    assert enqueued == []


# ---------------------------------------------------------------------------
# Source-level contract checks on static/js/async_upload.js
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402  (import after pytestmark is fine here)

JS_PATH = Path(__file__).resolve().parents[2] / "static" / "js" / "async_upload.js"


def _read_async_upload_js() -> str:
    return JS_PATH.read_text(encoding="utf-8")


class TestAsyncUploadJsContract:
    """Source-level contract checks on static/js/async_upload.js.

    The file ships unbundled and there is no JS test runner; substring
    sniffs are the simplest stable assertion for "this hook exists".
    """

    def test_polling_checks_document_hidden(self):
        source = _read_async_upload_js()
        assert "document.hidden" in source, (
            "Polling must check document.hidden so it can pause when the tab "
            "is in the background (P4 Slice B requirement)."
        )

    def test_polling_resumes_on_visibilitychange(self):
        source = _read_async_upload_js()
        assert "visibilitychange" in source, (
            "Polling must register a visibilitychange listener so a paused "
            "poll resumes when the tab becomes visible again."
        )

    def test_polling_listener_uses_once_semantics(self):
        """The visibilitychange listener must remove itself after firing once."""
        source = _read_async_upload_js()
        assert "{ once: true }" in source or "removeEventListener" in source, (
            "Visibilitychange listener must be one-shot — use `{ once: true }` "
            "or call removeEventListener inside the handler."
        )

    def test_pending_state_renders_branded_spinner_markup(self):
        source = _read_async_upload_js()
        # The spinner markup the JS injects must carry the same DOM hook the
        # parent_ui/includes/spinner.html partial uses, so future CSS and JS
        # controllers can attach to a single selector.
        assert "fk-spinner" in source
        assert "data-spinner" in source

    def test_completed_state_renders_branded_toast_markup(self):
        source = _read_async_upload_js()
        assert "fk-toast" in source
        assert "data-toast" in source
        # The success copy must be Latvian and reference the recognized person.
        assert "Persona atpazīta" in source
        assert "Dokumenta apstrāde pabeigta" in source

    def test_failed_state_consumes_server_supplied_latvian_message(self):
        source = _read_async_upload_js()
        # The JS must read the new ocr_error_message field instead of
        # synthesizing an English-free template inline.
        assert "ocr_error_message" in source
        # The pre-Slice-B raw-text path must be gone.
        assert "'OCR neizdevās ('" not in source

    def test_toast_auto_dismisses(self):
        source = _read_async_upload_js()
        # Auto-dismiss happens via a setTimeout that removes the toast DOM
        # node. We don't pin the exact duration, just that auto-dismiss exists.
        assert "TOAST_AUTO_DISMISS_MS" in source or "auto-dismiss" in source.lower()

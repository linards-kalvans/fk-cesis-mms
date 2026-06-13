"""P7 audit baseline — AuditEvents for document preview/download/delete.

Covers:
1. Admin download emits DOCUMENT_DOWNLOADED with ip_address set.
2. Admin preview emits DOCUMENT_PREVIEWED.
3. Soft-delete-on-replace emits DOCUMENT_DELETED (parent actor → null user).
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.core.models import AuditEvent
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import _handle_document_upload

pytestmark = pytest.mark.django_db


def _make_admin_user():
    return get_user_model().objects.create_user(
        username="admin",
        email="admin@example.com",
        password="password123",
        is_staff=True,
        is_superuser=True,
    )


def _make_document():
    application = RegistrationApplication.objects.create(
        claimed_email="guardian@example.com",
    )
    return Document.objects.create(
        application=application,
        kind=Document.Kind.GUARDIAN_IDENTITY,
        file=SimpleUploadedFile("id.png", b"file-bytes", content_type="image/png"),
        original_filename="id.png",
        content_type="image/png",
        file_size=10,
    )


class TestDownloadAudit:
    def test_download_emits_audit_event_with_ip(self):
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_document()

        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk]),
            HTTP_X_FORWARDED_FOR="203.0.113.7",
        )

        assert response.status_code == 200
        events = AuditEvent.objects.filter(
            action=str(AuditEvent.Action.DOCUMENT_DOWNLOADED),
            target_id=str(document.pk),
        )
        assert events.count() == 1
        assert events.first().ip_address == "203.0.113.7"


class TestPreviewAudit:
    def test_preview_emits_audit_event(self):
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_document()

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk]),
        )

        assert response.status_code == 200
        assert AuditEvent.objects.filter(
            action=str(AuditEvent.Action.DOCUMENT_PREVIEWED),
            target_id=str(document.pk),
        ).count() == 1


class TestSoftDeleteOnReplaceAudit:
    def test_replace_emits_document_deleted(self):
        application = RegistrationApplication.objects.create(
            claimed_email="guardian@example.com",
        )
        existing = Document.objects.create(
            application=application,
            kind=Document.Kind.GUARDIAN_IDENTITY,
            file=SimpleUploadedFile("old.png", b"old-bytes", content_type="image/png"),
            original_filename="old.png",
            content_type="image/png",
            file_size=9,
        )

        _handle_document_upload(
            application,
            SimpleUploadedFile("new.png", b"new-bytes", content_type="image/png"),
            "guardian_identity",
        )

        events = AuditEvent.objects.filter(
            action=str(AuditEvent.Action.DOCUMENT_DELETED),
            target_id=str(existing.pk),
        )
        assert events.count() == 1
        event = events.first()
        assert event.actor_id is None
        assert event.actor_label.startswith("parent:")
        assert event.metadata.get("reason") == "replaced"

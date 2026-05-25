"""Test that document_card.html emits the data-uploaded-document marker correctly.

This marker is read by wizard.js::isFileFieldFilled to enable the step gate
when a draft is resumed with already-uploaded documents.
"""

import pytest
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link
from apps.registrations.services import create_or_update_draft

pytestmark = pytest.mark.django_db

_PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _login(client: Client, account: ParentAccount) -> None:
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


def _png(name: str):
    from django.core.files.uploadedfile import SimpleUploadedFile
    return SimpleUploadedFile(name=name, content=_PNG, content_type="image/png")


class TestDocumentCardUploadStateMarker:
    """data-uploaded-document must be present iff document is already uploaded."""

    def test_marker_present_when_document_exists(self, settings):
        """Workspace HTML must include data-uploaded-document for an uploaded document."""
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        account = ParentAccount.objects.create(
            email="marker-present@example.com",
            phone="+37120000080",
        )
        app = create_or_update_draft(
            data={"guardian_email": account.email},
            files={"guardian_identity_document": _png("gid.png")},
            verified_account=account,
        )

        client = Client()
        _login(client, account)
        resp = client.get(f"/applications/{app.id}/")

        assert resp.status_code == 200
        assert b'data-uploaded-document' in resp.content, (
            "Workspace must render data-uploaded-document for an already-uploaded doc."
        )

    def test_marker_absent_when_no_document(self, settings):
        """Workspace HTML must NOT include data-uploaded-document when no doc uploaded."""
        settings.OCR_ENCRYPTION_KEY = "SRsUd5lcWomTf9Bh9PwqxSp9zB7qq7PbyOwspQGZBrw="

        account = ParentAccount.objects.create(
            email="marker-absent@example.com",
            phone="+37120000081",
        )
        app = create_or_update_draft(
            data={"guardian_email": account.email},
            files={},
            verified_account=account,
        )

        client = Client()
        _login(client, account)
        resp = client.get(f"/applications/{app.id}/")

        assert resp.status_code == 200
        assert b'data-uploaded-document' not in resp.content, (
            "Workspace must not render data-uploaded-document when no doc is present."
        )

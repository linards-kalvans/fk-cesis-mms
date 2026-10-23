"""P1 — Private registration document access tests (RED phase).

Covers:
1. Document files save under PRIVATE_DOCUMENTS_ROOT.
2. Anonymous preview request redirects to admin login.
3. Logged-in non-admin preview request returns 404.
4. Admin preview returns 200 with inline disposition.
5. Admin download returns 200 with attachment disposition.
6. Admin change page shows preview/download links.
7. Soft-deleted document returns 404.
8. Admin download streams file without storage redirect.
9. Saved file name keeps relative path starting with private/documents/.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin_user():
    return get_user_model().objects.create_user(
        username="admin",
        email="admin@example.com",
        password="password123",
        is_staff=True,
        is_superuser=True,
    )


def _make_non_admin_user():
    return get_user_model().objects.create_user(
        username="user",
        email="user@example.com",
        password="password123",
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


def _make_pdf_document():
    application = RegistrationApplication.objects.create(
        claimed_email="guardian@example.com",
    )
    return Document.objects.create(
        application=application,
        kind=Document.Kind.GUARDIAN_IDENTITY,
        file=SimpleUploadedFile(
            "id.pdf", b"%PDF-1.4\n%%EOF\n", content_type="application/pdf"
        ),
        original_filename="id.pdf",
        content_type="application/pdf",
        file_size=15,
    )


def _make_document_with(filename, content_type):
    """A document whose filename and declared MIME type may disagree."""
    application = RegistrationApplication.objects.create(
        claimed_email="guardian@example.com",
    )
    return Document.objects.create(
        application=application,
        kind=Document.Kind.GUARDIAN_IDENTITY,
        file=SimpleUploadedFile(filename, b"file-bytes", content_type=content_type),
        original_filename=filename,
        content_type=content_type,
        file_size=10,
    )


# ---------------------------------------------------------------------------
# Storage root and endpoint auth
# ---------------------------------------------------------------------------


class TestPrivateStorageRoot:
    """Document files must save under PRIVATE_DOCUMENTS_ROOT."""

    @override_settings(PRIVATE_DOCUMENTS_ROOT="/tmp/test-private-uploads")
    def test_document_file_uses_private_storage_root(self):
        """New document file path must contain the private storage root."""
        document = _make_document()
        assert "/test-private-uploads/" in document.file.path

    @override_settings(PRIVATE_DOCUMENTS_ROOT="/tmp/test-private-uploads")
    def test_document_keeps_relative_name_under_private_storage_root(self):
        """Saved file name must keep relative path starting with private/documents/."""
        document = _make_document()
        assert document.file.name.startswith("private/documents/")


# ---------------------------------------------------------------------------
# Anonymous preview redirect
# ---------------------------------------------------------------------------


class TestAnonymousPreviewRedirect:
    """Anonymous requests to preview/download must redirect to admin login."""

    def test_preview_redirects_anonymous_user_to_admin_login(self):
        """Anonymous GET to preview endpoint redirects to admin:login."""
        client = Client()
        document = _make_document()
        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )
        assert response.status_code == 302
        assert reverse("admin:login") in response["Location"]

    def test_download_redirects_anonymous_user_to_admin_login(self):
        """Anonymous GET to download endpoint redirects to admin:login."""
        client = Client()
        document = _make_document()
        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk])
        )
        assert response.status_code == 302
        assert reverse("admin:login") in response["Location"]


# ---------------------------------------------------------------------------
# Non-admin 404
# ---------------------------------------------------------------------------


class TestNonAdminAccess:
    """Authenticated non-admin users must receive 404."""

    def test_preview_returns_404_for_logged_in_non_admin(self):
        """Logged-in non-admin GET to preview returns 404."""
        client = Client()
        user = _make_non_admin_user()
        client.force_login(user)
        document = _make_document()
        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )
        assert response.status_code == 404

    def test_download_returns_404_for_logged_in_non_admin(self):
        """Logged-in non-admin GET to download returns 404."""
        client = Client()
        user = _make_non_admin_user()
        client.force_login(user)
        document = _make_document()
        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk])
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin preview success
# ---------------------------------------------------------------------------


class TestAdminPreview:
    """Admin users must be able to preview documents."""

    def test_preview_returns_inline_response_for_admin(self):
        """Admin GET to preview returns 200 with inline Content-Disposition."""
        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.status_code == 200
        disposition = response.get("Content-Disposition", "")
        assert disposition.startswith("inline")


# ---------------------------------------------------------------------------
# Admin download success
# ---------------------------------------------------------------------------


class TestAdminDownload:
    """Admin users must be able to download documents."""

    def test_download_returns_attachment_response_for_admin(self):
        """Admin GET to download returns 200 with attachment Content-Disposition."""
        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()

        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk])
        )

        assert response.status_code == 200
        disposition = response.get("Content-Disposition", "")
        assert disposition.startswith("attachment")


# ---------------------------------------------------------------------------
# Admin streams file without storage redirect
# ---------------------------------------------------------------------------


class TestAdminDownloadStreamsFile:
    """Download must stream file content through Django, not redirect to storage."""

    def test_admin_download_streams_file_without_storage_redirect(self):
        """Download response must be streaming, no Location header, correct bytes."""
        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()

        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk])
        )

        assert response.status_code == 200
        assert response.get("Location") is None, (
            "Download must not redirect to a storage URL."
        )
        assert response.streaming is True, (
            "Download response must be streaming."
        )
        assert b"".join(response.streaming_content) == b"file-bytes", (
            "Downloaded bytes must match uploaded content."
        )


# ---------------------------------------------------------------------------
# Soft-deleted document returns 404
# ---------------------------------------------------------------------------


class TestSoftDeletedDocument:
    """Soft-deleted documents must return 404 even for admins."""

    def test_soft_deleted_document_returns_404_for_admin(self):
        """Admin GET to preview of soft-deleted document returns 404."""
        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()
        document.deleted_at = timezone.now()
        document.save(update_fields=["deleted_at"])

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.status_code == 404

    def test_soft_deleted_document_returns_404_for_admin_download(self):
        """Admin GET to download of soft-deleted document returns 404."""
        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()
        document.deleted_at = timezone.now()
        document.save(update_fields=["deleted_at"])

        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk])
        )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Missing storage file returns 404
# ---------------------------------------------------------------------------


class TestMissingStorageFileReturns404:
    """When DB row exists but physical file is missing, return 404 not 500."""

    def test_preview_missing_file_returns_404(self):
        """Admin GET preview of document with missing storage file returns 404."""
        from unittest.mock import patch

        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()

        # Patch the storage file's open to raise FileNotFoundError
        with patch.object(type(document.file), "open", side_effect=FileNotFoundError("file missing")):
            response = client.get(
                reverse("documents:admin-document-preview", args=[document.pk])
            )

        assert response.status_code == 404

    def test_download_missing_file_returns_404(self):
        """Admin GET download of document with missing storage file returns 404."""
        from unittest.mock import patch

        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()

        with patch.object(type(document.file), "open", side_effect=FileNotFoundError("file missing")):
            response = client.get(
                reverse("documents:admin-document-download", args=[document.pk])
            )

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Django admin change page shows preview/download links
# ---------------------------------------------------------------------------


class TestAdminChangePageLinks:
    """Django admin Document change page must show Preview/Download links."""

    def test_document_admin_change_page_shows_preview_and_download_links(self):
        """Admin change page must contain preview and download URL slugs."""
        client = Client()
        admin = _make_admin_user()
        client.force_login(admin)
        document = _make_document()

        response = client.get(
            reverse("admin:documents_document_change", args=[document.pk])
        )

        assert response.status_code == 200
        content = response.content.decode()
        preview_url = reverse("documents:admin-document-preview", args=[document.pk])
        download_url = reverse("documents:admin-document-download", args=[document.pk])
        assert preview_url in content, (
            f"Admin change page must contain preview link ({preview_url})."
        )
        assert download_url in content, (
            f"Admin change page must contain download link ({download_url})."
        )


# ---------------------------------------------------------------------------
# Slice 2 — trusted PDF responses can be embedded same-origin
# ---------------------------------------------------------------------------


class TestPdfPreviewResponse:
    """The Admin Hub embeds trusted PDFs natively. The response must carry the
    real MIME type, inline disposition, and a frame policy that does not forbid
    the same-origin cockpit from framing it. Authorization and auditing are
    unchanged."""

    def test_pdf_preview_is_inline_application_pdf(self):
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_pdf_document()

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/pdf")
        assert response["Content-Disposition"].startswith("inline")

    def test_pdf_preview_frame_policy_allows_same_origin_embedding(self):
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_pdf_document()

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        frame_options = response.get("X-Frame-Options", "")
        assert frame_options.upper() != "DENY", (
            "X-Frame-Options: DENY blocks the Hub's same-origin <iframe>/<object>; "
            f"got {frame_options!r}"
        )
        # SAMEORIGIN (or an absent header) both permit the same-origin cockpit.
        assert frame_options.upper() in {"", "SAMEORIGIN"}

        csp = response.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" not in csp.lower(), (
            f"CSP frame-ancestors 'none' blocks same-origin embedding: {csp!r}"
        )

    def test_non_pdf_preview_keeps_the_default_frame_denial(self):
        """The fix must be narrow: arbitrary uploaded content stays unframed."""
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_document()

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.get("X-Frame-Options", "").upper() == "DENY"

    def test_pdf_extension_with_non_pdf_mime_keeps_the_default_frame_denial(self):
        """A .pdf name alone is not enough: both signals must agree."""
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_document_with("disguised.pdf", "image/png")

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.get("X-Frame-Options", "").upper() == "DENY"

    def test_pdf_mime_with_non_pdf_extension_keeps_the_default_frame_denial(self):
        """A PDF MIME type alone is not enough either."""
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_document_with("disguised.png", "application/pdf")

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.get("X-Frame-Options", "").upper() == "DENY"

    def test_pdf_download_keeps_the_default_frame_denial(self):
        """Attachments are never framed, even for a trusted PDF."""
        client = Client()
        client.force_login(_make_admin_user())
        document = _make_pdf_document()

        response = client.get(
            reverse("documents:admin-document-download", args=[document.pk])
        )

        assert response.get("X-Frame-Options", "").upper() == "DENY"

    def test_pdf_preview_still_audits_and_rejects_non_staff(self):
        from apps.core.models import AuditEvent

        client = Client()
        client.force_login(_make_admin_user())
        document = _make_pdf_document()

        response = client.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        )

        assert response.status_code == 200
        assert AuditEvent.objects.filter(
            action=str(AuditEvent.Action.DOCUMENT_PREVIEWED),
            target_id=str(document.pk),
        ).count() == 1

        other = Client()
        other.force_login(_make_non_admin_user())
        assert other.get(
            reverse("documents:admin-document-preview", args=[document.pk])
        ).status_code == 404

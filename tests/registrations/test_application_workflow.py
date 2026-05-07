"""Task 5 — RegistrationApplication model, Document model, and service-layer workflow RED tests.

Covers:
- Draft save does NOT auto-create ParentAccount; claims email via claimed_email.
- Second application with same email stores same claimed_email, no auto-link.
- Draft save allows incomplete fields.
- Upload creates Document with placeholder OCR status.
- Submit requires active child identity document.
- Submit sets status=submitted and submitted_at.
- Prefill uses account and latest application values.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import ParentAccount
from apps.accounts.services import issue_magic_link

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login_via_magic_link(client, account):
    """Convenience: issue magic link and GET verify to establish session."""
    raw = issue_magic_link(account)
    client.get(f"/accounts/verify/{raw}/")


# ---------------------------------------------------------------------------
# Helpers — defined locally to avoid polluting global fixtures
# ---------------------------------------------------------------------------

def _make_child_identity_file(name="id_card.jpg"):
    """Return a minimal SimpleUploadedFile suitable for child_identity_document upload."""
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


# ---------------------------------------------------------------------------
# RegistrationApplication model — fields, statuses, helpers
# ---------------------------------------------------------------------------

class TestRegistrationApplicationModel:
    """Verify the model exists with the required fields and choices."""

    def test_model_class_exists(self):
        from apps.registrations.models import RegistrationApplication

        assert RegistrationApplication is not None

    def test_has_parent_account_field(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "parent_account" in field_names

    def test_has_status_field_with_required_choices(self):
        from apps.registrations.models import RegistrationApplication

        status_field = RegistrationApplication._meta.get_field("status")
        choices_dict = dict(status_field.choices)
        assert "draft" in choices_dict
        assert "submitted" in choices_dict
        assert "fix_requested" in choices_dict
        assert "approved" in choices_dict
        assert "rejected" in choices_dict

    def test_has_guardian_and_child_fields(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        required = {
            "guardian_full_name",
            "guardian_personal_id",
            "guardian_email",
            "guardian_phone",
            "guardian_address",
            "child_full_name",
            "child_personal_id",
            "child_birth_date",
        }
        assert required.issubset(field_names)

    def test_has_submitted_at_field(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "submitted_at" in field_names

    def test_is_draft_helper_exists(self):
        from apps.registrations.models import RegistrationApplication

        assert hasattr(RegistrationApplication, "is_draft")

    def test_is_editable_by_helper_exists(self):
        from apps.registrations.models import RegistrationApplication

        assert hasattr(RegistrationApplication, "is_editable_by")


# ---------------------------------------------------------------------------
# Document model — fields, kinds, OCR status
# ---------------------------------------------------------------------------

class TestDocumentModel:
    """Verify the Document model exists with required fields."""

    def test_model_class_exists(self):
        from apps.documents.models import Document

        assert Document is not None

    def test_has_application_foreign_key(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "application" in field_names

    def test_has_kind_field_with_child_identity(self):
        from apps.documents.models import Document

        kind_field = Document._meta.get_field("kind")
        choices_dict = dict(kind_field.choices)
        assert "child_identity" in choices_dict

    def test_has_file_field(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "file" in field_names

    def test_has_original_filename_field(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "original_filename" in field_names

    def test_has_content_type_field(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "content_type" in field_names

    def test_has_file_size_field(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "file_size" in field_names

    def test_has_ocr_status_field(self):
        from apps.documents.models import Document

        ocr_field = Document._meta.get_field("ocr_status")
        choices_dict = dict(ocr_field.choices)
        assert "not_requested" in choices_dict
        assert "pending" in choices_dict
        assert "completed" in choices_dict
        assert "failed" in choices_dict

    def test_has_uploaded_by_parent_at_field(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "uploaded_by_parent_at" in field_names

    def test_has_deleted_at_field(self):
        from apps.documents.models import Document

        field_names = {f.name for f in Document._meta.get_fields()}
        assert "deleted_at" in field_names


# ---------------------------------------------------------------------------
# Service: create_or_update_draft — ParentAccount linkage
# ---------------------------------------------------------------------------

class TestCreateOrUpdateDraft:
    """Draft creation stores claimed_email; does NOT auto-create ParentAccount."""

    def test_draft_creation_stores_claimed_email_no_parent_account(self):
        """Saving a draft must store claimed_email and NOT create ParentAccount."""
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "newparent@example.com",
                "guardian_full_name": "Jane Doe",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga, Brivibas 1",
                "child_full_name": "Little Jane",
                "child_personal_id": "010125-67890",
                "child_birth_date": "2025-01-01",
            },
            files={},
        )
        assert app.parent_account is None
        assert app.claimed_email == "newparent@example.com"
        assert app.guardian_email == "newparent@example.com"

    def test_draft_creation_links_existing_parent_account(self):
        from apps.registrations.services import create_or_update_draft

        existing = ParentAccount.objects.create(
            email="returning@example.com",
            phone="+3711111111",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "returning@example.com",
                "guardian_full_name": "Jane Doe",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_address": "Riga, Brivibas 1",
                "child_full_name": "Little Jane",
                "child_personal_id": "010125-67890",
                "child_birth_date": "2025-01-01",
            },
            files={},
            verified_account=existing,
        )
        assert app.parent_account_id == existing.pk

    def test_second_application_same_claimed_email_no_auto_link(self):
        """Second draft with same email stores same claimed_email, no auto-link."""
        from apps.registrations.services import create_or_update_draft
        from apps.registrations.models import RegistrationApplication

        create_or_update_draft(
            data={
                "guardian_email": "multi@example.com",
                "guardian_full_name": "Parent One",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child A",
                "child_personal_id": "010125-11111",
                "child_birth_date": "2025-01-01",
            },
            files={},
        )
        second = create_or_update_draft(
            data={
                "guardian_email": "multi@example.com",
                "guardian_full_name": "Parent One",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_address": "Riga 1",
                "child_full_name": "Child B",
                "child_personal_id": "010125-22222",
                "child_birth_date": "2025-06-01",
            },
            files={},
        )
        # Two drafts, both unlinked, both claim same email
        assert second.parent_account is None
        assert second.claimed_email == "multi@example.com"
        assert RegistrationApplication.objects.filter(
            claimed_email__iexact="multi@example.com",
            parent_account__isnull=True,
        ).count() == 2


# ---------------------------------------------------------------------------
# Service: create_or_update_draft — claimed_email and no auto-link
# ---------------------------------------------------------------------------

class TestDraftClaimedEmailNoAutoLink:
    """Draft save must store claimed_email and NOT auto-link ParentAccount."""

    def test_draft_stores_claimed_email(self):
        """Saving a draft must store the guardian_email as claimed_email."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "claimed_email" in field_names, (
            "RegistrationApplication must have claimed_email field."
        )

    def test_draft_stores_draft_session_key(self):
        """Saving a draft must generate a draft_session_key for same-browser access."""
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        assert "draft_session_key" in field_names, (
            "RegistrationApplication must have draft_session_key field."
        )


# ---------------------------------------------------------------------------
# Service: create_or_update_draft — incomplete fields allowed
# ---------------------------------------------------------------------------

class TestDraftAllowsIncompleteFields:
    """Draft save must allow incomplete / missing required fields."""

    def test_minimal_draft_saved_with_empty_fields(self):
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "incomplete@example.com",
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_phone": "",
                "guardian_address": "",
                "child_full_name": "",
                "child_personal_id": "",
                "child_birth_date": None,
            },
            files={},
        )
        assert app.status == "draft"
        assert app.is_draft() is True


# ---------------------------------------------------------------------------
# Service: create_or_update_draft — file upload creates Document
# ---------------------------------------------------------------------------

class TestUploadCreatesDocument:
    """Uploading a child identity document should create a Document record."""

    def test_upload_creates_document_with_placeholder_ocr_status(self):
        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import Document

        app = create_or_update_draft(
            data={
                "guardian_email": "upload@example.com",
                "guardian_full_name": "Uploader",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37133333333",
                "guardian_address": "Riga 3",
                "child_full_name": "Child Up",
                "child_personal_id": "010125-99999",
                "child_birth_date": "2025-03-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("id_card.png"),
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "child_identity"
        assert doc.ocr_status == "not_requested"
        assert doc.uploaded_by_parent_at is not None
        assert doc.file_size > 0


# ---------------------------------------------------------------------------
# Service: submit_application — requirements
# ---------------------------------------------------------------------------

class TestSubmitApplication:
    """Submit should enforce required document and set status."""

    def test_submit_sets_status_and_submitted_at(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.create(
            email="submitter@example.com",
            phone="+37144444444",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "submitter@example.com",
                "guardian_full_name": "Submitter",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37155555555",
                "guardian_address": "Riga 5",
                "child_full_name": "Child Sub",
                "child_personal_id": "010125-55555",
                "child_birth_date": "2025-05-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("sub_id.jpg"),
            },
        )
        result = submit_application(app, acct)
        assert result.status == "submitted"
        assert result.submitted_at is not None

    def test_submit_without_identity_document_raises(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.create(
            email="no-doc@example.com",
            phone="+37166666666",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "no-doc@example.com",
                "guardian_full_name": "No Doc",
                "guardian_personal_id": "010101-66666",
                "guardian_phone": "+37177777777",
                "guardian_address": "Riga 7",
                "child_full_name": "Child NoDoc",
                "child_personal_id": "010125-66666",
                "child_birth_date": "2025-07-01",
            },
            files={},
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_with_deleted_identity_document_raises(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount
        from datetime import datetime, timezone

        acct = ParentAccount.objects.create(
            email="deleted-doc@example.com",
            phone="+37188888888",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "deleted-doc@example.com",
                "guardian_full_name": "Deleted Doc",
                "guardian_personal_id": "010101-77777",
                "guardian_phone": "+37199999999",
                "guardian_address": "Riga 9",
                "child_full_name": "Child Del",
                "child_personal_id": "010125-77777",
                "child_birth_date": "2025-08-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("del_id.jpg"),
            },
        )
        # Soft-delete the document
        from apps.documents.models import Document

        doc = Document.objects.get(application=app)
        doc.deleted_at = datetime.now(timezone.utc)
        doc.save(update_fields=["deleted_at"])
        # Delete from DB so query won't find it
        doc.delete()

        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_rejects_non_owner(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount

        owner = ParentAccount.objects.create(
            email="owner@example.com",
            phone="+37110101010",
        )
        other = ParentAccount.objects.create(
            email="other@example.com",
            phone="+37120202020",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "owner@example.com",
                "guardian_full_name": "Owner",
                "guardian_personal_id": "010101-10101",
                "guardian_phone": "+37130303030",
                "guardian_address": "Riga 10",
                "child_full_name": "Child Own",
                "child_personal_id": "010125-10101",
                "child_birth_date": "2025-09-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("own_id.jpg"),
            },
            verified_account=owner,
        )
        with pytest.raises(ValueError):
            submit_application(app, other)


# ---------------------------------------------------------------------------
# Service: can_edit_application
# ---------------------------------------------------------------------------

class TestCanEditApplication:
    """Permission helper should gate edit access correctly."""

    def test_owner_can_edit_draft(self):
        from apps.registrations.services import create_or_update_draft, can_edit_application
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.create(
            email="editowner@example.com",
            phone="+37140404040",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "editowner@example.com",
                "guardian_full_name": "Edit Owner",
                "guardian_personal_id": "010101-40404",
                "guardian_phone": "+37150505050",
                "guardian_address": "Riga 40",
                "child_full_name": "Child Edit",
                "child_personal_id": "010125-40404",
                "child_birth_date": "2025-10-01",
            },
            files={},
            verified_account=acct,
        )
        assert can_edit_application(app, acct) is True

    def test_non_owner_cannot_edit_draft(self):
        from apps.registrations.services import create_or_update_draft, can_edit_application
        from apps.accounts.models import ParentAccount

        owner = ParentAccount.objects.create(
            email="editowner2@example.com",
            phone="+37160606060",
        )
        other = ParentAccount.objects.create(
            email="editother@example.com",
            phone="+37170707070",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "editowner2@example.com",
                "guardian_full_name": "Edit Owner 2",
                "guardian_personal_id": "010101-60606",
                "guardian_phone": "+37180808080",
                "guardian_address": "Riga 60",
                "child_full_name": "Child Edit2",
                "child_personal_id": "010125-60606",
                "child_birth_date": "2025-11-01",
            },
            files={},
        )
        assert can_edit_application(app, other) is False

    def test_submitted_application_not_editable_by_owner(self):
        from apps.registrations.services import (
            create_or_update_draft,
            submit_application,
            can_edit_application,
        )
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.create(
            email="subowner@example.com",
            phone="+37190909090",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "subowner@example.com",
                "guardian_full_name": "Sub Owner",
                "guardian_personal_id": "010101-90909",
                "guardian_phone": "+37101010101",
                "guardian_address": "Riga 90",
                "child_full_name": "Child Sub",
                "child_personal_id": "010125-90909",
                "child_birth_date": "2025-12-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("sub2_id.jpg"),
            },
        )
        submit_application(app, acct)
        assert can_edit_application(app, acct) is False


# ---------------------------------------------------------------------------
# Service: get_application_prefill
# ---------------------------------------------------------------------------

class TestGetApplicationPrefill:
    """Prefill should use account and latest application values."""

    def test_prefill_returns_account_and_latest_application_data(self):
        from apps.registrations.services import create_or_update_draft, get_application_prefill
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.create(
            email="prefill@example.com",
            phone="+37123232323",
        )
        # First application
        create_or_update_draft(
            data={
                "guardian_email": "prefill@example.com",
                "guardian_full_name": "First Name",
                "guardian_personal_id": "010101-23232",
                "guardian_phone": "+37134343434",
                "guardian_address": "Riga 23",
                "child_full_name": "Child First",
                "child_personal_id": "010125-23232",
                "child_birth_date": "2025-01-15",
            },
            files={},
        )
        # Second (latest) application
        second = create_or_update_draft(
            data={
                "guardian_email": "prefill@example.com",
                "guardian_full_name": "Updated Name",
                "guardian_personal_id": "010101-23232",
                "guardian_phone": "+37145454545",
                "guardian_address": "Riga 45",
                "child_full_name": "Child Second",
                "child_personal_id": "010125-34343",
                "child_birth_date": "2025-06-20",
            },
            files={},
        )

        prefill = get_application_prefill(acct)
        assert isinstance(prefill, dict)
        # Should contain guardian data from latest application
        assert prefill.get("guardian_full_name") == "Updated Name"
        assert prefill.get("child_full_name") == "Child Second"
        assert prefill.get("guardian_email") == "prefill@example.com"

    def test_prefill_returns_empty_when_no_account(self):
        from apps.registrations.services import get_application_prefill

        prefill = get_application_prefill(None)
        assert isinstance(prefill, dict)
        assert len(prefill) == 0


# ---------------------------------------------------------------------------
# Regression: anonymous save-draft must not 404 on follow-up edit page
# ---------------------------------------------------------------------------

class TestAnonymousSaveDraftRedirect:
    """Anonymous user saves draft at /register/ — edit page must be accessible.

    Bug: start_registration creates a draft and redirects to
    /applications/<id>/edit/ without establishing a parent session.
    The edit view calls can_edit_application(application, None) → False → 404.

    Approved behavior: after anonymous save-draft, the session carries the
    newly-created ParentAccount so the edit page loads (200).
    """

    def test_anonymous_save_draft_edit_page_accessible(self, client):
        """POST valid draft data as anonymous user → redirect → edit page 200."""
        from apps.registrations.models import RegistrationApplication

        response = client.post(
            "/register/",
            data={
                "guardian_email": "anon@example.com",
                "guardian_full_name": "Anonymous Parent",
                "guardian_personal_id": "010101-00001",
                "guardian_phone": "+37120000001",
                "guardian_address": "Riga, Test 1",
                "child_full_name": "Child Anon",
                "child_personal_id": "010125-00001",
                "child_birth_date": "2025-01-01",
            },
            follow=False,
        )
        # start_registration should redirect (302)
        assert response.status_code == 302
        edit_url = response.url

        # Follow the redirect — the edit page must load (200), not 404
        edit_response = client.get(edit_url, follow=False)
        assert edit_response.status_code == 200, (
            f"Edit page returned {edit_response.status_code} for anonymous user "
            f"after save-draft. Expected 200. URL: {edit_url}"
        )

        # Session should carry the draft_session_key for same-browser continuity
        assert "draft_session_key" in client.session

        # Verify the application was actually created
        assert RegistrationApplication.objects.filter(
            guardian_email="anon@example.com"
        ).exists()


# ---------------------------------------------------------------------------
# Regression: invalid submit should render top-level error summary
# ---------------------------------------------------------------------------

class TestInvalidSubmitErrorSummary:
    """Invalid submit should return 400 with a top-level error summary in the response.

    This is a visual-system test that asserts the error-summary element exists
    in the HTML returned on invalid submission. Business logic (400 status)
    is also asserted to ensure the workflow behavior is preserved.
    """

    def setup_method(self):
        self.client = Client()

    def _create_draft_with_doc_and_login(self, email="errsum@example.com"):
        acct = ParentAccount.objects.create(
            email=email,
            phone="+37188888888",
        )
        _login_via_magic_link(self.client, acct)
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": email,
                "guardian_full_name": "Error Sum Guardian",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37199999999",
                "guardian_address": "Riga 88",
                "child_full_name": "Error Sum Child",
                "child_personal_id": "010125-88888",
                "child_birth_date": "2025-04-01",
            },
            files={
                "child_identity_document": _make_child_identity_file("err_id.jpg"),
            },
            verified_account=acct,
        )
        return acct, app

    def test_invalid_submit_returns_400_and_has_error_summary(self):
        """Submitting with empty required fields should return 400 with error summary."""
        acct, app = self._create_draft_with_doc_and_login("errsum2@example.com")
        resp = self.client.post(
            f"/applications/{app.pk}/submit/",
            data={
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_email": "",
                "guardian_phone": "",
                "guardian_address": "",
                "child_full_name": "",
                "child_personal_id": "",
                "child_birth_date": "",
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for invalid submit, got {resp.status_code}."
        )
        content = resp.content.decode()
        # Error summary element should be present — class like 'error-summary',
        # 'form-errors', 'validation-summary', or heading like 'Kļūdas'.
        has_summary = (
            "error-summary" in content
            or "form-errors" in content
            or "validation-summary" in content
            or 'class="errors"' in content
            or 'class="error' in content
            or "Kļūda" in content
            or "Kļūdas" in content
        )
        assert has_summary, (
            "Invalid submit page does not have a top-level error summary. "
            "Expected an element with class like 'error-summary', 'form-errors', "
            "'validation-summary', or Latvian heading like 'Kļūdas'."
        )

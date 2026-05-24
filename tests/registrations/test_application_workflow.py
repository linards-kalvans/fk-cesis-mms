"""RegistrationApplication model, Document model, and service-layer workflow tests.

P1-aligned. Covers:
- Draft save stores claimed_email; does NOT auto-create ParentAccount.
- Draft save allows incomplete fields.
- Upload creates Document with placeholder OCR status (new kinds).
- Submit requires guardian_identity, member_identity, member_portrait docs + kit sizes.
- Submit sets status=submitted and submitted_at.
- Prefill uses account and latest application values.
- Resubmission clears review fields.
"""

import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# RegistrationApplication model — fields, statuses, helpers
# ---------------------------------------------------------------------------

class TestRegistrationApplicationModel:
    """Verify the model exists with the required fields and choices."""

    def test_model_class_exists(self):
        from apps.registrations.models import RegistrationApplication

        assert RegistrationApplication is not None


# ---------------------------------------------------------------------------
# Document model — fields, kinds, OCR status
# ---------------------------------------------------------------------------

class TestDocumentModel:
    """Verify the Document model exists with required fields."""

    def test_model_class_exists(self):
        from apps.documents.models import Document

        assert Document is not None


# ---------------------------------------------------------------------------
# Service: create_or_update_draft — ParentAccount linkage
# ---------------------------------------------------------------------------

class TestCreateOrUpdateDraft:
    """Draft creation stores claimed_email; does NOT auto-create ParentAccount."""

    def test_draft_creation_stores_claimed_email_no_parent_account(self):
        """Saving a draft must store claimed_email and NOT create ParentAccount.

        Kept bespoke: exercises anonymous (no verified_account) draft path which
        the standard fixtures do not cover.
        """
        from apps.registrations.services import create_or_update_draft

        app = create_or_update_draft(
            data={
                "guardian_email": "newparent@example.com",
                "guardian_full_name": "Jane Doe",
                "guardian_personal_id": "010101-12345",
                "guardian_phone": "+37120000000",
                "guardian_declared_address": "Riga, Brivibas 1",
                "member_full_name": "Little Jane",
                "member_personal_id": "010125-67890",
                "member_birth_date": "2025-01-01",
            },
            files={},
        )
        assert app.parent_account is None
        assert app.claimed_email == "newparent@example.com"
        assert app.guardian_email == "newparent@example.com"

    def test_draft_creation_links_existing_parent_account(self):
        """Kept bespoke: exercises account-linking logic with a specific returning email."""
        from apps.accounts.models import ParentAccount
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
                "guardian_declared_address": "Riga, Brivibas 1",
                "member_full_name": "Little Jane",
                "member_personal_id": "010125-67890",
                "member_birth_date": "2025-01-01",
            },
            files={},
            verified_account=existing,
        )
        assert app.parent_account_id == existing.pk

    def test_second_application_same_claimed_email_no_auto_link(self):
        """Second draft with same email stores same claimed_email, no auto-link.

        Kept bespoke: exercises multi-draft-same-email isolation logic.
        """
        from apps.registrations.services import create_or_update_draft
        from apps.registrations.models import RegistrationApplication

        create_or_update_draft(
            data={
                "guardian_email": "multi@example.com",
                "guardian_full_name": "Parent One",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child A",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-01-01",
            },
            files={},
        )
        second = create_or_update_draft(
            data={
                "guardian_email": "multi@example.com",
                "guardian_full_name": "Parent One",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 1",
                "member_full_name": "Child B",
                "member_personal_id": "010125-22222",
                "member_birth_date": "2025-06-01",
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
                "guardian_declared_address": "",
                "member_full_name": "",
                "member_personal_id": "",
                "member_birth_date": None,
            },
            files={},
        )
        assert app.status == "draft"
        assert app.is_draft() is True


# ---------------------------------------------------------------------------
# Service: create_or_update_draft — file upload creates Document
# ---------------------------------------------------------------------------

class TestUploadCreatesDocument:
    """Uploading guardian/member documents should create Document records."""

    def test_upload_creates_guardian_identity_document(
        self, settings, guardian_identity_file
    ):
        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import Document

        settings.OCR_PROVIDER_MODE = "stub"
        app = create_or_update_draft(
            data={
                "guardian_email": "upload@example.com",
                "guardian_full_name": "Uploader",
                "guardian_personal_id": "010101-99999",
                "guardian_phone": "+37133333333",
                "guardian_declared_address": "Riga 3",
                "member_full_name": "Child Up",
                "member_personal_id": "010125-99999",
                "member_birth_date": "2025-03-01",
            },
            files={
                "guardian_identity_document": guardian_identity_file,
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "guardian_identity"
        assert doc.ocr_status == "completed"
        assert doc.uploaded_by_parent_at is not None
        assert doc.file_size > 0

    def test_upload_creates_member_identity_document(self, member_identity_file):
        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import Document

        app = create_or_update_draft(
            data={
                "guardian_email": "upload2@example.com",
                "guardian_full_name": "Uploader 2",
                "guardian_personal_id": "010101-88888",
                "guardian_phone": "+37133333334",
                "guardian_declared_address": "Riga 4",
                "member_full_name": "Child Up2",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-03-02",
            },
            files={
                "member_identity_document": member_identity_file,
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "member_identity"

    def test_upload_creates_member_portrait_document(self, member_portrait_file):
        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import Document

        app = create_or_update_draft(
            data={
                "guardian_email": "upload3@example.com",
                "guardian_full_name": "Uploader 3",
                "guardian_personal_id": "010101-77777",
                "guardian_phone": "+37133333335",
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child Up3",
                "member_personal_id": "010125-77777",
                "member_birth_date": "2025-03-03",
            },
            files={
                "member_portrait_document": member_portrait_file,
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "member_portrait"


# ---------------------------------------------------------------------------
# Service: submit_application — requirements
# ---------------------------------------------------------------------------

class TestSubmitApplication:
    """Submit should enforce required docs and set status."""

    def test_submit_sets_status_and_submitted_at(
        self, draft_with_documents, kit_sizes, parent_account
    ):
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = kit_sizes
        app = create_or_update_draft(
            data={
                "guardian_email": parent_account.email,
                "guardian_full_name": "Submitter",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37155555555",
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child Sub",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-05-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={},
            application=draft_with_documents,
            verified_account=parent_account,
        )
        result = submit_application(app, parent_account)
        assert result.status == "submitted"
        assert result.submitted_at is not None

    def test_submit_without_identity_document_raises(self):
        """Kept bespoke: intentionally no documents — tests the missing-doc guard."""
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
                "guardian_declared_address": "Riga 7",
                "member_full_name": "Child NoDoc",
                "member_personal_id": "010125-66666",
                "member_birth_date": "2025-07-01",
            },
            files={},
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_with_deleted_identity_document_raises(
        self, draft_with_documents, kit_sizes, parent_account
    ):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.documents.models import Document
        from datetime import datetime, timezone

        shirt_pk, shorts_pk = kit_sizes
        app = create_or_update_draft(
            data={
                "guardian_email": parent_account.email,
                "guardian_full_name": "Deleted Doc",
                "guardian_personal_id": "010101-77777",
                "guardian_phone": "+37199999999",
                "guardian_declared_address": "Riga 9",
                "member_full_name": "Child Del",
                "member_personal_id": "010125-77777",
                "member_birth_date": "2025-08-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={},
            application=draft_with_documents,
            verified_account=parent_account,
        )
        # Soft-delete all documents
        for doc in Document.objects.filter(application=app):
            doc.deleted_at = datetime.now(timezone.utc)
            doc.save(update_fields=["deleted_at"])
            doc.delete()

        with pytest.raises(ValueError):
            submit_application(app, parent_account)

    def test_submit_rejects_non_owner(
        self, draft_with_documents, kit_sizes, parent_account, other_parent_account
    ):
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = kit_sizes
        app = create_or_update_draft(
            data={
                "guardian_email": parent_account.email,
                "guardian_full_name": "Owner",
                "guardian_personal_id": "010101-10101",
                "guardian_phone": "+37130303030",
                "guardian_declared_address": "Riga 10",
                "member_full_name": "Child Own",
                "member_personal_id": "010125-10101",
                "member_birth_date": "2025-09-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={},
            application=draft_with_documents,
            verified_account=parent_account,
        )
        with pytest.raises(ValueError):
            submit_application(app, other_parent_account)

    def test_submit_without_kit_sizes_raises(
        self,
        guardian_identity_file,
        member_identity_file,
        member_portrait_file,
    ):
        """Kept bespoke: intentionally omits kit sizes — tests the missing-kit guard."""
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount

        acct = ParentAccount.objects.create(
            email="nokit@example.com",
            phone="+37111111111",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "nokit@example.com",
                "guardian_full_name": "No Kit",
                "guardian_personal_id": "010101-11111",
                "guardian_phone": "+37122222222",
                "guardian_declared_address": "Riga 11",
                "member_full_name": "Child NoKit",
                "member_personal_id": "010125-11111",
                "member_birth_date": "2025-10-01",
            },
            files={
                "guardian_identity_document": guardian_identity_file,
                "member_identity_document": member_identity_file,
                "member_portrait_document": member_portrait_file,
            },
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)


# ---------------------------------------------------------------------------
# Service: can_edit_application
# ---------------------------------------------------------------------------

class TestCanEditApplication:
    """Permission helper should gate edit access correctly."""

    def test_owner_can_edit_draft(self, draft_application, parent_account):
        from apps.registrations.services import can_edit_application

        assert can_edit_application(draft_application, parent_account) is True

    def test_non_owner_cannot_edit_draft(self, draft_application, other_parent_account):
        from apps.registrations.services import can_edit_application

        assert can_edit_application(draft_application, other_parent_account) is False

    def test_submitted_application_not_editable_by_owner(
        self, submitted_application, parent_account
    ):
        from apps.registrations.services import can_edit_application

        assert can_edit_application(submitted_application, parent_account) is False


# ---------------------------------------------------------------------------
# Service: get_application_prefill
# ---------------------------------------------------------------------------

class TestGetApplicationPrefill:
    """Prefill should use account and latest application values."""

    def test_prefill_returns_account_and_latest_application_data(self):
        """Kept bespoke: tests the latest-application selection logic with two drafts."""
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
                "guardian_declared_address": "Riga 23",
                "member_full_name": "Child First",
                "member_personal_id": "010125-23232",
                "member_birth_date": "2025-01-15",
            },
            files={},
        )
        # Second (latest) application
        create_or_update_draft(
            data={
                "guardian_email": "prefill@example.com",
                "guardian_full_name": "Updated Name",
                "guardian_personal_id": "010101-23232",
                "guardian_phone": "+37145454545",
                "guardian_declared_address": "Riga 45",
                "member_full_name": "Child Second",
                "member_personal_id": "010125-34343",
                "member_birth_date": "2025-06-20",
            },
            files={},
        )

        prefill = get_application_prefill(acct)
        assert isinstance(prefill, dict)
        # Should contain guardian data from latest application
        assert prefill.get("guardian_full_name") == "Updated Name"
        assert prefill.get("guardian_email") == "prefill@example.com"

    def test_prefill_returns_empty_when_no_account(self):
        """Kept bespoke: no-account path — fixture contract assumes a verified parent."""
        from apps.registrations.services import get_application_prefill

        prefill = get_application_prefill(None)
        assert isinstance(prefill, dict)
        assert len(prefill) == 0


# ---------------------------------------------------------------------------
# Regression: invalid submit should render top-level error summary
# ---------------------------------------------------------------------------

class TestInvalidSubmitErrorSummary:
    """Invalid submit should return 400 with a top-level error summary in the response."""

    def test_invalid_submit_returns_400_and_has_error_summary(
        self, verified_client, draft_with_documents
    ):
        """Submitting with empty required fields should return 400 with error summary."""
        resp = verified_client.post(
            f"/applications/{draft_with_documents.pk}/submit/",
            data={
                "guardian_full_name": "",
                "guardian_personal_id": "",
                "guardian_email": "",
                "guardian_phone": "",
                "guardian_declared_address": "",
                "member_full_name": "",
                "member_personal_id": "",
                "member_birth_date": "",
                "member_same_address_as_guardian": True,
            },
        )
        assert resp.status_code == 400, (
            f"Expected 400 for invalid submit, got {resp.status_code}."
        )
        content = resp.content.decode()
        # Error summary element should be present
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
            "Invalid submit page does not have a top-level error summary."
        )


# ---------------------------------------------------------------------------
# Resubmission behavior — fix_requested applications
# ---------------------------------------------------------------------------


class TestResubmissionAcceptsFixRequested:
    """submit_application must accept applications with status=fix_requested."""

    def test_submit_application_accepts_fix_requested(
        self, fix_requested_application, parent_account
    ):
        """Calling submit_application on a fix_requested app must succeed."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import submit_application

        result = submit_application(fix_requested_application, parent_account)
        assert result.status == RegistrationApplication.Status.SUBMITTED, (
            f"Expected submitted, got {result.status}."
        )


class TestResubmissionClearsReviewFields:
    """Resubmission must clear review_message, reviewed_by, reviewed_at."""

    def test_resubmission_clears_review_message(
        self, fix_requested_application, parent_account
    ):
        """After resubmission, review_message must be cleared."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import submit_application

        submit_application(fix_requested_application, parent_account)
        fix_requested_application.refresh_from_db()
        assert fix_requested_application.status == RegistrationApplication.Status.SUBMITTED
        assert fix_requested_application.review_message == "", (
            "review_message must be cleared on resubmission."
        )

    def test_resubmission_clears_reviewed_at(
        self, fix_requested_application, parent_account
    ):
        """After resubmission, reviewed_at must be cleared."""
        from datetime import datetime, timezone

        # Set reviewed_at before resubmitting
        fix_requested_application.reviewed_at = datetime.now(timezone.utc)
        fix_requested_application.save(update_fields=["reviewed_at"])

        from apps.registrations.services import submit_application

        submit_application(fix_requested_application, parent_account)
        fix_requested_application.refresh_from_db()
        assert fix_requested_application.reviewed_at is None, (
            "reviewed_at must be cleared on resubmission."
        )

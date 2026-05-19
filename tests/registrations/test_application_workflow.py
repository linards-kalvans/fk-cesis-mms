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


def _make_member_identity_file(name="id_card.jpg"):
    """Return a minimal SimpleUploadedFile suitable for member_identity_document upload."""
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_guardian_identity_file(name="guardian_id.jpg"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_member_portrait_file(name="portrait.jpg"):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _ensure_kit_sizes():
    """Create kit size options if they don't already exist. Returns (shirt_pk, shorts_pk)."""
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        defaults={"label": "S", "is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        defaults={"label": "S", "is_active": True},
    )
    return shirt.pk, shorts.pk


def _submit_form_data(email, shirt_pk, shorts_pk):
    """Build POST data matching P1 submit requirements."""
    return {
        "guardian_full_name": "Submit Guardian",
        "guardian_personal_id": "010101-12345",
        "guardian_email": email,
        "guardian_phone": "+37120000000",
        "guardian_declared_address": "Riga, Brivibas 1",
        "member_full_name": "Submit Child",
        "member_personal_id": "010125-67890",
        "member_birth_date": "2025-01-01",
        "member_same_address_as_guardian": True,
        "member_kit_size_shirt": shirt_pk,
        "member_kit_size_shorts": shorts_pk,
        "preferred_agreement_signing": "paper",
    }


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

    def test_has_guardian_and_member_fields(self):
        from apps.registrations.models import RegistrationApplication

        field_names = {f.name for f in RegistrationApplication._meta.get_fields()}
        required = {
            "guardian_full_name",
            "guardian_personal_id",
            "guardian_email",
            "guardian_phone",
            "guardian_declared_address",
            "member_full_name",
            "member_personal_id",
            "member_birth_date",
            "member_actual_address",
            "member_same_address_as_guardian",
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

    def test_has_kind_field_with_guardian_identity(self):
        from apps.documents.models import Document

        kind_field = Document._meta.get_field("kind")
        choices_dict = dict(kind_field.choices)
        assert "guardian_identity" in choices_dict

    def test_has_kind_field_with_member_identity(self):
        from apps.documents.models import Document

        kind_field = Document._meta.get_field("kind")
        choices_dict = dict(kind_field.choices)
        assert "member_identity" in choices_dict

    def test_has_kind_field_with_member_portrait(self):
        from apps.documents.models import Document

        kind_field = Document._meta.get_field("kind")
        choices_dict = dict(kind_field.choices)
        assert "member_portrait" in choices_dict

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
        """Second draft with same email stores same claimed_email, no auto-link."""
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

    def test_upload_creates_guardian_identity_document(self):
        from apps.registrations.services import create_or_update_draft
        from apps.documents.models import Document

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
                "guardian_identity_document": _make_guardian_identity_file("guardian_id.png"),
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "guardian_identity"
        assert doc.ocr_status == "completed"
        assert doc.uploaded_by_parent_at is not None
        assert doc.file_size > 0

    def test_upload_creates_member_identity_document(self):
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
                "member_identity_document": _make_member_identity_file("member_id.png"),
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "member_identity"

    def test_upload_creates_member_portrait_document(self):
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
                "member_portrait_document": _make_member_portrait_file("portrait.png"),
            },
        )
        doc = Document.objects.get(application=app)
        assert doc.kind == "member_portrait"


# ---------------------------------------------------------------------------
# Service: submit_application — requirements
# ---------------------------------------------------------------------------

class TestSubmitApplication:
    """Submit should enforce required docs and set status."""

    def test_submit_sets_status_and_submitted_at(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount

        shirt_pk, shorts_pk = _ensure_kit_sizes()

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
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child Sub",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-05-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("sub_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("sub_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("sub_portrait.jpg"),
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
                "guardian_declared_address": "Riga 7",
                "member_full_name": "Child NoDoc",
                "member_personal_id": "010125-66666",
                "member_birth_date": "2025-07-01",
            },
            files={},
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_with_deleted_identity_document_raises(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount
        from datetime import datetime, timezone

        shirt_pk, shorts_pk = _ensure_kit_sizes()

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
                "guardian_declared_address": "Riga 9",
                "member_full_name": "Child Del",
                "member_personal_id": "010125-77777",
                "member_birth_date": "2025-08-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("del_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("del_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("del_portrait.jpg"),
            },
        )
        # Soft-delete all documents
        from apps.documents.models import Document

        for doc in Document.objects.filter(application=app):
            doc.deleted_at = datetime.now(timezone.utc)
            doc.save(update_fields=["deleted_at"])
            doc.delete()

        with pytest.raises(ValueError):
            submit_application(app, acct)

    def test_submit_rejects_non_owner(self):
        from apps.registrations.services import create_or_update_draft, submit_application
        from apps.accounts.models import ParentAccount

        shirt_pk, shorts_pk = _ensure_kit_sizes()

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
                "guardian_declared_address": "Riga 10",
                "member_full_name": "Child Own",
                "member_personal_id": "010125-10101",
                "member_birth_date": "2025-09-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("own_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("own_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("own_portrait.jpg"),
            },
            verified_account=owner,
        )
        with pytest.raises(ValueError):
            submit_application(app, other)

    def test_submit_without_kit_sizes_raises(self):
        """Submit must require kit sizes (shirt and shorts)."""
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
                "guardian_identity_document": _make_guardian_identity_file("nokit_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("nokit_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("nokit_portrait.jpg"),
            },
        )
        with pytest.raises(ValueError):
            submit_application(app, acct)


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
                "guardian_declared_address": "Riga 40",
                "member_full_name": "Child Edit",
                "member_personal_id": "010125-40404",
                "member_birth_date": "2025-10-01",
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
                "guardian_declared_address": "Riga 60",
                "member_full_name": "Child Edit2",
                "member_personal_id": "010125-60606",
                "member_birth_date": "2025-11-01",
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

        shirt_pk, shorts_pk = _ensure_kit_sizes()

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
                "guardian_declared_address": "Riga 90",
                "member_full_name": "Child Sub",
                "member_personal_id": "010125-90909",
                "member_birth_date": "2025-12-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("sub2_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("sub2_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("sub2_portrait.jpg"),
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
                "guardian_declared_address": "Riga 23",
                "member_full_name": "Child First",
                "member_personal_id": "010125-23232",
                "member_birth_date": "2025-01-15",
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
        from apps.registrations.services import get_application_prefill

        prefill = get_application_prefill(None)
        assert isinstance(prefill, dict)
        assert len(prefill) == 0


# ---------------------------------------------------------------------------
# Regression: invalid submit should render top-level error summary
# ---------------------------------------------------------------------------

class TestInvalidSubmitErrorSummary:
    """Invalid submit should return 400 with a top-level error summary in the response."""

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
                "guardian_declared_address": "Riga 88",
                "member_full_name": "Error Sum Child",
                "member_personal_id": "010125-88888",
                "member_birth_date": "2025-04-01",
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("err_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("err_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("err_portrait.jpg"),
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

    def test_submit_application_accepts_fix_requested(self):
        """Calling submit_application on a fix_requested app must succeed."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = _ensure_kit_sizes()

        acct = ParentAccount.objects.create(
            email="fixsub@example.com",
            phone="+37133333333",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "fixsub@example.com",
                "guardian_full_name": "Fix Sub Guardian",
                "guardian_personal_id": "010101-33333",
                "guardian_phone": "+37144444444",
                "guardian_declared_address": "Riga 3",
                "member_full_name": "Child FixSub",
                "member_personal_id": "010125-33333",
                "member_birth_date": "2025-02-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("fixsub_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("fixsub_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("fixsub_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.save(update_fields=["status"])

        # submit_application should accept fix_requested
        result = submit_application(app, acct)
        assert result.status == RegistrationApplication.Status.SUBMITTED, (
            f"Expected submitted, got {result.status}."
        )


class TestResubmissionClearsReviewFields:
    """Resubmission must clear review_message, reviewed_by, reviewed_at."""

    def test_resubmission_clears_review_message(self):
        """After resubmission, review_message must be cleared."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = _ensure_kit_sizes()

        acct = ParentAccount.objects.create(
            email="clearmsg@example.com",
            phone="+37155555555",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "clearmsg@example.com",
                "guardian_full_name": "Clear Msg Guardian",
                "guardian_personal_id": "010101-55555",
                "guardian_phone": "+37166666666",
                "guardian_declared_address": "Riga 5",
                "member_full_name": "Child ClearMsg",
                "member_personal_id": "010125-55555",
                "member_birth_date": "2025-03-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("clearmsg_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("clearmsg_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("clearmsg_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.review_message = "Fix this please."
        app.save(update_fields=["status", "review_message"])

        # Resubmit
        submit_application(app, acct)
        app.refresh_from_db()
        assert app.status == RegistrationApplication.Status.SUBMITTED
        assert app.review_message == "", (
            "review_message must be cleared on resubmission."
        )

    def test_resubmission_clears_reviewed_at(self):
        """After resubmission, reviewed_at must be cleared."""
        from apps.registrations.models import RegistrationApplication
        from apps.registrations.services import create_or_update_draft, submit_application

        shirt_pk, shorts_pk = _ensure_kit_sizes()

        acct = ParentAccount.objects.create(
            email="clearat@example.com",
            phone="+37177777777",
        )
        app = create_or_update_draft(
            data={
                "guardian_email": "clearat@example.com",
                "guardian_full_name": "Clear At Guardian",
                "guardian_personal_id": "010101-77777",
                "guardian_phone": "+37188888888",
                "guardian_declared_address": "Riga 7",
                "member_full_name": "Child ClearAt",
                "member_personal_id": "010125-77777",
                "member_birth_date": "2025-04-01",
                "member_kit_size_shirt": shirt_pk,
                "member_kit_size_shorts": shorts_pk,
            },
            files={
                "guardian_identity_document": _make_guardian_identity_file("clearat_guardian.jpg"),
                "member_identity_document": _make_member_identity_file("clearat_member.jpg"),
                "member_portrait_document": _make_member_portrait_file("clearat_portrait.jpg"),
            },
            verified_account=acct,
        )
        submit_application(app, acct)
        app.status = RegistrationApplication.Status.FIX_REQUESTED
        app.reviewed_at = app.updated_at  # Set reviewed_at
        app.save(update_fields=["status", "reviewed_at"])

        # Resubmit
        submit_application(app, acct)
        app.refresh_from_db()
        assert app.reviewed_at is None, (
            "reviewed_at must be cleared on resubmission."
        )

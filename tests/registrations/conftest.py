"""Shared fixtures for tests/registrations/.

Centralizes the per-test bootstrap that was repeated 60+ times across
test_application_workflow.py, test_parent_edit_permissions.py, and
test_registration_form_contract.py:
  - kit size option creation
  - file uploads for the three required document kinds
  - draft application creation
  - draft + all-documents-uploaded application (ready to submit)

Parent-account / verified-client fixtures live in tests/conftest.py.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def _png(name: str) -> SimpleUploadedFile:
    return SimpleUploadedFile(name=name, content=_PNG_BYTES, content_type="image/png")


@pytest.fixture
def guardian_identity_file():
    return _png("guardian_id.png")


@pytest.fixture
def member_identity_file():
    return _png("member_id.png")


@pytest.fixture
def member_portrait_file():
    return _png("portrait.png")


@pytest.fixture
def kit_sizes(db):
    """Return (shirt_pk, shorts_pk). Idempotent.

    Looks up by (kind, label) so it is safe when other fixtures or autouse
    fixtures have already created multiple labels for the same kind.
    """
    from apps.members.models import KitSizeOption

    shirt, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHIRT,
        label="S",
        defaults={"is_active": True},
    )
    shorts, _ = KitSizeOption.objects.get_or_create(
        kind=KitSizeOption.Kind.SHORTS,
        label="S",
        defaults={"is_active": True},
    )
    return shirt.pk, shorts.pk


@pytest.fixture
def submit_payload(kit_sizes, parent_account):
    """POST payload that passes RegistrationApplicationForm submit validation."""
    shirt_pk, shorts_pk = kit_sizes
    return {
        "guardian_full_name": "Submit Guardian",
        "guardian_personal_id": "010101-12345",
        "guardian_email": parent_account.email,
        "guardian_phone": "+37120000000",
        "guardian_declared_address": "Riga, Brivibas 1",
        "member_full_name": "Submit Child",
        "member_personal_id": "010125-67890",
        "member_birth_date": "2025-01-01",
        "member_same_address_as_guardian": True,
        "member_kit_size_shirt": shirt_pk,
        "preferred_agreement_signing": "paper",
    }


@pytest.fixture
def draft_application(parent_account):
    """A minimal draft application owned by parent_account."""
    from apps.registrations.services import create_or_update_draft

    return create_or_update_draft(
        data={"guardian_email": parent_account.email},
        files={},
        verified_account=parent_account,
    )


@pytest.fixture
def draft_with_documents(
    draft_application,
    guardian_identity_file,
    member_identity_file,
    member_portrait_file,
):
    """draft_application plus the three required documents attached."""
    from apps.documents.models import Document

    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.GUARDIAN_IDENTITY,
        file=guardian_identity_file,
        original_filename=guardian_identity_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.MEMBER_IDENTITY,
        file=member_identity_file,
        original_filename=member_identity_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    Document.objects.create(
        application=draft_application,
        kind=Document.Kind.MEMBER_PORTRAIT,
        file=member_portrait_file,
        original_filename=member_portrait_file.name,
        content_type="image/png",
        file_size=len(_PNG_BYTES),
    )
    return draft_application


@pytest.fixture
def submitted_application(draft_with_documents, parent_account, submit_payload):
    """A draft_with_documents that has been promoted to status='submitted'.

    Suitable for admin-review tests which need a queue-visible application
    owned by parent_account.

    The draft is first updated with the full submit_payload (all required
    fields + kit sizes), then submitted via the service layer.
    """
    from apps.registrations.services import create_or_update_draft, submit_application

    # Update the minimal draft with the full set of required fields and kit sizes.
    # Documents are already attached by draft_with_documents; pass files={} to
    # avoid re-uploading them (create_or_update_draft only uploads when files are
    # present in the mapping).
    app = create_or_update_draft(
        data=submit_payload,
        files={},
        application=draft_with_documents,
        verified_account=parent_account,
    )
    return submit_application(app, parent_account)


@pytest.fixture
def fix_requested_application(submitted_application):
    """A submitted application that the admin has set to fix_requested.

    review_message is set to a stable sentinel string used by portal-visibility
    and save-preserves-status tests.
    """
    from apps.registrations.models import RegistrationApplication

    submitted_application.status = RegistrationApplication.Status.FIX_REQUESTED
    submitted_application.review_message = "Please correct the personal ID format."
    submitted_application.save(update_fields=["status", "review_message"])
    return submitted_application


@pytest.fixture
def rejected_application(submitted_application):
    """A submitted application that the admin has set to rejected.

    review_message is set to a stable sentinel string used by portal-visibility
    and editability tests.
    """
    from apps.registrations.models import RegistrationApplication

    submitted_application.status = RegistrationApplication.Status.REJECTED
    submitted_application.review_message = "Application does not meet requirements."
    submitted_application.save(update_fields=["status", "review_message"])
    return submitted_application

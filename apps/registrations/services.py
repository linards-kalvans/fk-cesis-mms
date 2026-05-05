"""Service functions for registration workflow."""

from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from apps.accounts.models import ParentAccount
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication

REQUIRED_SUBMIT_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_email",
    "guardian_phone",
    "guardian_address",
    "child_full_name",
    "child_personal_id",
    "child_birth_date",
)


# ---------------------------------------------------------------------------
# Prefill helpers
# ---------------------------------------------------------------------------


def _latest_application(account: ParentAccount) -> RegistrationApplication | None:
    result: RegistrationApplication | None = account.applications.order_by("-created_at").first()
    return result


def get_application_prefill(account: ParentAccount | None) -> dict[str, object]:
    """Return prefilled field values for a new registration form."""
    if account is None:
        return {}

    latest = _latest_application(account)
    prefill: dict[str, object] = {
        "guardian_email": account.email,
        "guardian_phone": account.phone,
    }
    if latest is not None:
        prefill.update(
            {
                "guardian_full_name": latest.guardian_full_name,
                "guardian_personal_id": latest.guardian_personal_id,
                "guardian_address": latest.guardian_address,
                "child_full_name": latest.child_full_name,
                "child_personal_id": latest.child_personal_id,
                "child_birth_date": latest.child_birth_date,
            }
        )
    return prefill


def can_edit_application(application: RegistrationApplication, actor_account: ParentAccount | None) -> bool:
    """Return True if the actor may edit the application."""
    result: bool = application.is_editable_by(actor_account)
    return result


# ---------------------------------------------------------------------------
# Draft creation / update
# ---------------------------------------------------------------------------


def _get_or_create_parent_account(email: str, phone: str) -> ParentAccount:
    # Case-insensitive lookup to handle mixed-case email inputs
    existing = ParentAccount.objects.filter(email__iexact=email).first()
    if existing is not None:
        if phone and existing.phone != phone:
            existing.phone = phone
            existing.save(update_fields=["phone", "updated_at"])
        result: ParentAccount = existing
        return result

    account, _ = ParentAccount.objects.get_or_create(
        email=email,
        defaults={"phone": phone or ""},
    )
    acct: ParentAccount = account
    return acct


def _replace_child_identity_document(application: RegistrationApplication, upload) -> None:
    existing = application.documents.filter(
        kind=Document.Kind.CHILD_IDENTITY,
        deleted_at__isnull=True,
    ).first()
    if existing is not None:
        existing.deleted_at = timezone.now()
        existing.save(update_fields=["deleted_at", "updated_at"])

    Document.objects.create(
        application=application,
        kind=Document.Kind.CHILD_IDENTITY,
        file=upload,
        original_filename=upload.name,
        content_type=getattr(upload, "content_type", "application/octet-stream"),
        file_size=upload.size,
        ocr_status=Document.OcrStatus.NOT_REQUESTED,
    )


def create_or_update_draft(
    *,
    data: Mapping[str, Any],
    files: Mapping[str, Any],
    application: RegistrationApplication | None = None,
) -> RegistrationApplication:
    """Create or update a draft registration application."""
    email = str(data.get("guardian_email", "")).strip().lower()
    if not email:
        raise ValueError("guardian_email is required to save draft")

    phone = str(data.get("guardian_phone", "")).strip()
    account = _get_or_create_parent_account(email, phone)

    if application is None:
        application = RegistrationApplication(parent_account=account)
    elif application.parent_account_id != account.id:
        raise ValueError("application email cannot change owner")

    application.parent_account = account
    application.guardian_full_name = str(data.get("guardian_full_name", "")).strip()
    application.guardian_personal_id = str(data.get("guardian_personal_id", "")).strip()
    application.guardian_email = email
    application.guardian_phone = phone
    application.guardian_address = str(data.get("guardian_address", "")).strip()
    application.child_full_name = str(data.get("child_full_name", "")).strip()
    application.child_personal_id = str(data.get("child_personal_id", "")).strip()
    application.child_birth_date = data.get("child_birth_date") or None
    application.status = RegistrationApplication.Status.DRAFT
    application.save()

    upload = files.get("child_identity_document")
    if upload is not None:
        _replace_child_identity_document(application, upload)

    return application


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def _require_complete_application(application: RegistrationApplication) -> None:
    missing = [field for field in REQUIRED_SUBMIT_FIELDS if not getattr(application, field)]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def _require_active_child_identity_document(application: RegistrationApplication) -> None:
    exists = application.documents.filter(
        kind=Document.Kind.CHILD_IDENTITY,
        deleted_at__isnull=True,
    ).exists()
    if not exists:
        raise ValueError("child identity document is required before submit")


def submit_application(
    application: RegistrationApplication,
    actor_account: ParentAccount,
) -> RegistrationApplication:
    """Submit a draft application. Raises ValueError on validation failure."""
    if application.parent_account_id != actor_account.id:
        raise ValueError("not allowed to submit this application")
    if application.status != RegistrationApplication.Status.DRAFT:
        raise ValueError("only draft applications can be submitted")

    _require_complete_application(application)
    _require_active_child_identity_document(application)

    application.status = RegistrationApplication.Status.SUBMITTED
    application.submitted_at = timezone.now()
    application.save(update_fields=["status", "submitted_at", "updated_at"])
    return application

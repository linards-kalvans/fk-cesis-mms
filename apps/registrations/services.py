"""Service functions for registration workflow."""

from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from apps.accounts.models import ParentAccount
from apps.documents.models import Document
from apps.members.models import Guardian, KitSizeOption, Member
from apps.registrations.models import RegistrationApplication

REQUIRED_SUBMIT_FIELDS = (
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
    "preferred_agreement_signing",
)

# All manual P1 form fields that map to model columns (excl. guardian_email = derived)
MANUAL_P1_FIELDS = (
    "guardian_full_name",
    "guardian_personal_id",
    "guardian_phone",
    "guardian_declared_address",
    "member_full_name",
    "member_personal_id",
    "member_birth_date",
    "member_actual_address",
    "member_same_address_as_guardian",
    "preferred_agreement_signing",
    "support_club_instead_of_multi_child_discount",
)


# ---------------------------------------------------------------------------
# Prefill helpers
# ---------------------------------------------------------------------------


def _latest_application(account: ParentAccount) -> RegistrationApplication | None:
    # Consider both linked applications and unlinked drafts with matching
    # claimed_email, so prefill works even before verification.
    linked = account.applications.order_by("-created_at")
    unlinked = RegistrationApplication.objects.filter(
        claimed_email__iexact=account.email,
        parent_account__isnull=True,
    ).order_by("-created_at")
    # Merge and pick the most recent
    combined = list(linked) + list(unlinked)
    if not combined:
        return None
    result: RegistrationApplication | None = max(combined, key=lambda a: a.created_at)
    return result


def get_application_prefill(account: ParentAccount | None) -> dict[str, object]:
    """Return prefilled field values for a new registration form.

    Guardian fields are prefilled from the verified account / latest
    application. Member/child fields are NOT prefilled — the user
    enters a new child each time.
    """
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
                "guardian_declared_address": latest.guardian_declared_address,
            }
        )
    return prefill


def can_edit_application(application: RegistrationApplication, actor_account: ParentAccount | None) -> bool:
    """Return True if the actor may edit the application.

    Allows editing for status `draft` and `fix_requested` only.
    """
    result: bool = application.is_editable_by(actor_account)
    return result


# ---------------------------------------------------------------------------
# Draft creation / update
# ---------------------------------------------------------------------------


def _handle_document_upload(application: RegistrationApplication, upload, kind: str) -> None:
    """Soft-delete existing active docs of the same kind, then create new one."""
    existing = application.documents.filter(
        kind=kind,
        deleted_at__isnull=True,
    ).first()
    if existing is not None:
        existing.deleted_at = timezone.now()
        existing.save(update_fields=["deleted_at", "updated_at"])

    Document.objects.create(
        application=application,
        kind=kind,
        file=upload,
        original_filename=upload.name,
        content_type=getattr(upload, "content_type", "application/octet-stream"),
        file_size=upload.size,
        ocr_status=Document.OcrStatus.NOT_REQUESTED,
    )


def _apply_same_address_logic(application: RegistrationApplication, data: Mapping[str, Any]) -> None:
    """Apply same-address toggle: copy guardian address to member address."""
    same_address = data.get("member_same_address_as_guardian", False)
    sources = dict(application.field_sources) if application.field_sources else {}
    if same_address:
        application.member_actual_address = str(data.get("guardian_declared_address", "")).strip()
        sources["member_actual_address"] = "derived_system_filled"
    else:
        member_addr = str(data.get("member_actual_address", "")).strip()
        if not member_addr:
            member_addr = str(data.get("guardian_declared_address", "")).strip()
        application.member_actual_address = member_addr
        sources["member_actual_address"] = "manual_only"
    application.field_sources = sources


def _apply_field_sources_for_guardian_email(application: RegistrationApplication) -> None:
    """Mark guardian_email as derived_system_filled and all other manual P1
    fields as manual_only."""
    sources = dict(application.field_sources) if application.field_sources else {}
    sources["guardian_email"] = "derived_system_filled"
    for field_name in MANUAL_P1_FIELDS:
        if field_name not in sources:
            sources[field_name] = "manual_only"
    application.field_sources = sources


def create_or_update_draft(
    *,
    data: Mapping[str, Any],
    files: Mapping[str, Any],
    application: RegistrationApplication | None = None,
    verified_account: ParentAccount | None = None,
) -> RegistrationApplication:
    """Create or update a draft registration application.

    Drafts store the typed email as claimed_email. A draft_session_key is
    assigned for same-browser access. Typed email is a claim only, so no
    ParentAccount lookup or linking happens here.
    """
    email = str(data.get("guardian_email", "")).strip().lower()
    if not email:
        raise ValueError("guardian_email is required to save draft")

    if application is None:
        application = RegistrationApplication()
        application.claimed_email = email
    else:
        if application.parent_account_id is not None and application.claimed_email.lower() != email:
            raise ValueError("application email cannot change verified owner")
        if application.parent_account_id is None:
            application.claimed_email = email

    if verified_account is not None:
        if verified_account.email.lower() != email:
            raise ValueError("verified account email must match claimed email")
        application.parent_account = verified_account

    # Backward-compat aliases for old field names
    _alias = {
        "guardian_address": "guardian_declared_address",
        "child_full_name": "member_full_name",
        "child_personal_id": "member_personal_id",
        "child_birth_date": "member_birth_date",
    }
    for old, new in _alias.items():
        if old in data and new not in data:
            data = dict(data)
            data[new] = data[old]

    application.guardian_full_name = str(data.get("guardian_full_name", "")).strip()
    application.guardian_personal_id = str(data.get("guardian_personal_id", "")).strip()
    application.guardian_email = email
    application.guardian_phone = str(data.get("guardian_phone", "")).strip()
    application.guardian_declared_address = str(data.get("guardian_declared_address", "")).strip()
    application.member_full_name = str(data.get("member_full_name", "")).strip()
    application.member_personal_id = str(data.get("member_personal_id", "")).strip()
    application.member_birth_date = data.get("member_birth_date") or None
    application.member_same_address_as_guardian = bool(data.get("member_same_address_as_guardian", False))
    preferred = str(data.get("preferred_agreement_signing", "")).strip()
    if not preferred:
        preferred = "paper"
    application.preferred_agreement_signing = preferred
    if "support_club_instead_of_multi_child_discount" in data:
        raw = data["support_club_instead_of_multi_child_discount"]
        application.support_club_instead_of_multi_child_discount = bool(raw) if raw is not None else None
    else:
        application.support_club_instead_of_multi_child_discount = None

    # Kit sizes — FK to KitSizeOption
    shirt_id = data.get("member_kit_size_shirt")
    if shirt_id is not None:
        try:
            application.member_kit_size_shirt = KitSizeOption.objects.get(pk=shirt_id)
        except (KitSizeOption.DoesNotExist, ValueError, TypeError):
            application.member_kit_size_shirt = None
    else:
        application.member_kit_size_shirt = None

    shorts_id = data.get("member_kit_size_shorts")
    if shorts_id is not None:
        try:
            application.member_kit_size_shorts = KitSizeOption.objects.get(pk=shorts_id)
        except (KitSizeOption.DoesNotExist, ValueError, TypeError):
            application.member_kit_size_shorts = None
    else:
        application.member_kit_size_shorts = None

    # Same-address logic
    _apply_same_address_logic(application, data)

    # Field source for guardian_email
    _apply_field_sources_for_guardian_email(application)

    application.status = RegistrationApplication.Status.DRAFT
    application.save()

    # Handle document uploads
    guardian_doc = files.get("guardian_identity_document")
    if guardian_doc is not None:
        _handle_document_upload(application, guardian_doc, "guardian_identity")

    # Backward-compat: child_identity_document → member_identity_document
    member_doc = files.get("member_identity_document") or files.get("child_identity_document")
    if member_doc is not None:
        _handle_document_upload(application, member_doc, "member_identity")

    portrait_doc = files.get("member_portrait_document")
    if portrait_doc is not None:
        _handle_document_upload(application, portrait_doc, "member_portrait")

    return application


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


def _has_prior_non_rejected_application(application: RegistrationApplication) -> bool:
    """Return True when the guardian has a prior non-rejected application."""
    acct = application.parent_account
    if acct is not None:
        has = RegistrationApplication.objects.filter(
            parent_account=acct,
        ).exclude(
            status=RegistrationApplication.Status.REJECTED,
        ).exclude(
            pk=application.pk,
        ).exists()
        return bool(has)

    email = application.claimed_email
    if email:
        has = RegistrationApplication.objects.filter(
            claimed_email__iexact=email,
            parent_account__isnull=True,
        ).exclude(
            status=RegistrationApplication.Status.REJECTED,
        ).exclude(
            pk=application.pk,
        ).exists()
        return bool(has)

    return False


def _require_complete_application(application: RegistrationApplication) -> None:
    boolean_fields = {
        "member_same_address_as_guardian",
        "support_club_instead_of_multi_child_discount",
    }
    missing = []
    for field in REQUIRED_SUBMIT_FIELDS:
        val = getattr(application, field)
        if field in boolean_fields:
            if val is None:
                missing.append(field)
        elif not val:
            missing.append(field)
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")


def _require_active_guardian_identity_document(application: RegistrationApplication) -> None:
    exists = application.documents.filter(
        kind=Document.Kind.GUARDIAN_IDENTITY,
        deleted_at__isnull=True,
    ).exists()
    if not exists:
        raise ValueError("guardian identity document is required before submit")


def _require_active_member_identity_document(application: RegistrationApplication) -> None:
    exists = application.documents.filter(
        kind=Document.Kind.MEMBER_IDENTITY,
        deleted_at__isnull=True,
    ).exists()
    if not exists:
        raise ValueError("member identity document is required before submit")


def _require_active_member_portrait_document(application: RegistrationApplication) -> None:
    exists = application.documents.filter(
        kind=Document.Kind.MEMBER_PORTRAIT,
        deleted_at__isnull=True,
    ).exists()
    if not exists:
        raise ValueError("member portrait document is required before submit")


def _require_valid_kit_sizes(application: RegistrationApplication) -> None:
    if application.member_kit_size_shirt_id is None:
        raise ValueError("member kit size shirt is required before submit")
    if application.member_kit_size_shorts_id is None:
        raise ValueError("member kit size shorts is required before submit")


def submit_application(
    application: RegistrationApplication,
    actor_account: ParentAccount | None,
) -> RegistrationApplication:
    """Submit a draft or fix_requested application. Raises ValueError on validation failure."""
    if application.parent_account_id is not None and (
        actor_account is None or application.parent_account_id != actor_account.id
    ):
        raise ValueError("not allowed to submit this application")
    if application.status not in (
        RegistrationApplication.Status.DRAFT,
        RegistrationApplication.Status.FIX_REQUESTED,
    ):
        raise ValueError("only draft or fix_requested applications can be submitted")

    _require_complete_application(application)

    if _has_prior_non_rejected_application(application):
        val = application.support_club_instead_of_multi_child_discount
        if val is None:
            raise ValueError(
                "support_club_instead_of_multi_child_discount is required "
                "when guardian has prior non-rejected applications"
            )

    _require_active_guardian_identity_document(application)
    _require_active_member_identity_document(application)
    _require_active_member_portrait_document(application)
    _require_valid_kit_sizes(application)

    application.status = RegistrationApplication.Status.SUBMITTED
    application.submitted_at = timezone.now()
    # Clear review metadata on resubmission
    application.review_message = ""
    application.reviewed_by = None
    application.reviewed_at = None
    application.save(update_fields=["status", "submitted_at", "updated_at", "review_message", "reviewed_by_id", "reviewed_at"])
    return application


# ---------------------------------------------------------------------------
# Post-verification: attach unverified applications to verified parent
# ---------------------------------------------------------------------------


def attach_claimed_email_apps_to_parent(email: str, parent_account: ParentAccount) -> int:
    """Attach drafts with matching claimed_email to the verified parent.

    Returns the number of applications attached.
    """
    count: int = RegistrationApplication.objects.filter(
        claimed_email__iexact=email,
        parent_account__isnull=True,
    ).update(parent_account=parent_account)
    return count


# ---------------------------------------------------------------------------
# Review actions
# ---------------------------------------------------------------------------


def request_application_fix(
    application: RegistrationApplication,
    reviewer: settings.AUTH_USER_MODEL,
    message: str,
) -> RegistrationApplication:
    """Request fixes from the parent. Only allowed from submitted status."""
    if application.status != RegistrationApplication.Status.SUBMITTED:
        raise ValueError("can only request fix on submitted application")

    if not message or not message.strip():
        raise ValueError("fix message is required")

    application.status = RegistrationApplication.Status.FIX_REQUESTED
    application.review_message = message.strip()
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "review_message", "reviewed_by_id", "reviewed_at", "updated_at"])

    _send_notification(
        application,
        subject="Jūsu pieteikums ir jālabo",
        message=f"Pieteikuma labojuma pieprasījums:\n\n{message.strip()}\n\nLūdzu, labojiet pieteikumu un iesniedziet to vēlreiz.",
    )
    return application


def reject_application(
    application: RegistrationApplication,
    reviewer: settings.AUTH_USER_MODEL,
    message: str,
) -> RegistrationApplication:
    """Reject an application. Only allowed from submitted status."""
    if application.status != RegistrationApplication.Status.SUBMITTED:
        raise ValueError("can only reject submitted application")

    if not message or not message.strip():
        raise ValueError("reject message is required")

    application.status = RegistrationApplication.Status.REJECTED
    application.review_message = message.strip()
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "review_message", "reviewed_by_id", "reviewed_at", "updated_at"])

    _send_notification(
        application,
        subject="Jūsu pieteikums ir noraidīts",
        message=f"Pieteikuma noraidīšanas iemesls:\n\n{message.strip()}",
    )
    return application


def approve_application(
    application: RegistrationApplication,
    reviewer: settings.AUTH_USER_MODEL,
) -> RegistrationApplication:
    """Approve an application, creating Guardian + Member. Idempotent."""
    # Idempotent: if already approved with linked member, return as-is
    if application.approved_member_id is not None:
        return application

    if application.status != RegistrationApplication.Status.SUBMITTED:
        raise ValueError("can only approve submitted application")

    # Create Guardian from application guardian data
    guardian = Guardian.objects.create(
        full_name=application.guardian_full_name,
        personal_id=application.guardian_personal_id,
        email=application.guardian_email,
        phone=application.guardian_phone,
        address=application.guardian_declared_address,
    )

    # Create Member linked to Guardian, no training_group
    member = Member.objects.create(
        full_name=application.member_full_name,
        personal_id=application.member_personal_id,
        birth_date=application.member_birth_date,
        guardian=guardian,
        training_group=None,
    )

    application.status = RegistrationApplication.Status.APPROVED
    application.approved_member = member
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "approved_member_id", "reviewed_by_id", "reviewed_at", "updated_at"])

    _send_notification(
        application,
        subject="Jūsu pieteikums ir apstiprināts",
        message=f"Bija veiksmīgi apstiprināts. Jūsu bērns '{application.member_full_name}' ir pievienots kluba dalībnieku reģistram.",
    )
    return application


def _send_notification(application: RegistrationApplication, subject: str, message: str) -> None:
    """Send an email notification to the parent's email address."""
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[application.guardian_email],
        fail_silently=False,
    )

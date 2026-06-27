"""Service functions for registration workflow."""

from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import ParentAccount
from apps.agreements.models import Agreement
from apps.agreements.services import create_agreement_for_member
from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent
from apps.documents.models import Document, DocumentExtraction
from apps.integrations import ocr as _ocr
from apps.integrations.name_normalization import normalize_latvian_name
from apps.integrations.ocr import OCR_SUPPORTED_KINDS
from apps.integrations.tasks import enqueue_ocr_job
from apps.members.models import KitSizeOption, Member, TrainingGroup
from apps.members.services import resolve_guardian_for_account
from apps.registrations.models import (
    PERSONAL_DATA_CONSENT_VERSION,
    RegistrationApplication,
)

# Module-level wrapper for monkeypatch compatibility.
# Tests patch both apps.registrations.services.extract_document_data and
# apps.integrations.ocr.extract_document_data, so calls must flow through both.
def extract_document_data(*args, **kwargs):
    return _ocr.extract_document_data(*args, **kwargs)


def safe_extract_document_data(*args, **kwargs):
    """Wrapper so monkeypatches on apps.registrations.services intercept."""
    return _ocr.safe_extract_document_data(*args, **kwargs)

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

# Slice B2: guardian fields in REQUIRED_SUBMIT_FIELDS are legacy column names;
# resolve them through the read accessors instead of direct attribute access.
_GUARDIAN_SUBMIT_ACCESSORS = {
    "guardian_full_name": "guardian_name",
    "guardian_personal_id": "guardian_pid",
    "guardian_email": "guardian_contact_email",
    "guardian_phone": "guardian_contact_phone",
    "guardian_declared_address": "guardian_address",
}

# Manual P1 form-field names used as field_sources keys (guardian fields now
# live on the Guardian row; guardian_email is derived from ParentAccount).
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
    "preferred_payment_mode",
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


def _decrypt_extraction_payload(extraction: DocumentExtraction) -> dict[str, Any] | None:
    """Decrypt an extraction payload, returning None on failure."""
    try:
        from apps.documents.ocr import decrypt_json

        payload = decrypt_json(extraction.encrypted_payload)
        if isinstance(payload, dict):
            return payload
        return None
    except Exception:
        return None


def get_application_prefill(account: ParentAccount | None) -> dict[str, object]:
    """Return prefilled field values for a new registration form.

    Guardian fields are prefilled from the verified account / latest
    application. Member/child fields are NOT prefilled — the user
    enters a new child each time.

    OCR extraction data from prior apps is merged into prefill values.
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
                "guardian_full_name": latest.guardian_name,
                "guardian_personal_id": latest.guardian_pid,
                "guardian_declared_address": latest.guardian_address,
            }
        )

    # Merge OCR-extracted values from prior applications
    # OCR values take priority when extraction exists; model values used as fallback.
    ocr_prefill = _merge_ocr_extractions(account)
    for key, value in ocr_prefill.items():
        prefill[key] = value

    return prefill


def _merge_ocr_extractions(account: ParentAccount) -> dict[str, str]:
    """Extract OCR person fields from prior guardian documents and return prefill values.

    Member fields are intentionally excluded — each new registration is for a
    different child so member values must not carry over (see get_application_prefill).
    """
    result: dict[str, str] = {}

    prior_apps = list(account.applications.order_by("-created_at"))

    for prior_app in prior_apps:
        guardian_identity_doc = prior_app.documents.filter(
            kind=Document.Kind.GUARDIAN_IDENTITY,
            deleted_at__isnull=True,
            ocr_status=Document.OcrStatus.COMPLETED,
        ).select_related("extraction").first()
        if guardian_identity_doc is None:
            continue
        extraction = getattr(guardian_identity_doc, "extraction", None)
        payload = _decrypt_extraction_payload(extraction) if extraction is not None else None
        if not payload:
            continue
        person_fields = payload.get("person_fields", {})
        if not isinstance(person_fields, dict):
            continue
        fn = normalize_latvian_name(person_fields.get("first_name", ""))
        ln = normalize_latvian_name(person_fields.get("last_name", ""))
        pid = str(person_fields.get("personal_id", "")).strip()
        full_name = " ".join(part for part in [fn, ln] if part).strip()
        if full_name:
            result["guardian_full_name"] = full_name
        if pid:
            result["guardian_personal_id"] = pid
        break  # Found usable guardian OCR — stop scanning older apps

    return result


def can_edit_application(application: RegistrationApplication, actor_account: ParentAccount | None) -> bool:
    """Return True if the actor may edit the application.

    Allows editing for status `draft` and `fix_requested` only.
    """
    result: bool = application.is_editable_by(actor_account)
    return result


# ---------------------------------------------------------------------------
# Draft creation / update
# ---------------------------------------------------------------------------


def _set_ocr_field_sources(application: RegistrationApplication, kind: str) -> None:
    """Mark person fields as OCR-sourced.

    Used by the guardian-document-reuse path (synchronous copy of prior
    extraction). The OCR job in apps.integrations.tasks does its own
    field-source tagging at the end of a successful extraction.
    """
    sources = dict(application.field_sources) if application.field_sources else {}
    if kind == Document.Kind.GUARDIAN_IDENTITY:
        sources["guardian_full_name"] = "ocr_guardian_identity"
        sources["guardian_personal_id"] = "ocr_guardian_identity"
    elif kind == Document.Kind.MEMBER_IDENTITY:
        sources["member_full_name"] = "ocr_member_identity"
        sources["member_personal_id"] = "ocr_member_identity"
    application.field_sources = sources
    application.save(update_fields=["field_sources", "updated_at"])


def _handle_document_upload(application: RegistrationApplication, upload, kind: str) -> None:
    """Soft-delete existing active docs of the same kind, create the new one, enqueue OCR.

    OCR runs in a django-q2 background job (see apps.integrations.tasks).
    """
    existing = application.documents.filter(
        kind=kind,
        deleted_at__isnull=True,
    ).first()
    if existing is not None:
        existing.deleted_at = timezone.now()
        existing.save(update_fields=["deleted_at", "updated_at"])
        record_audit_event(
            action=str(AuditEvent.Action.DOCUMENT_DELETED),
            actor_label=f"parent: {application.guardian_contact_email or application.claimed_email}",
            target=existing,
            metadata={"kind": kind, "reason": "replaced"},
        )

    from django.core.files.base import ContentFile

    upload_bytes = upload.read()
    initial_status = (
        Document.OcrStatus.PENDING
        if kind in OCR_SUPPORTED_KINDS
        else Document.OcrStatus.NOT_REQUESTED
    )
    document = Document.objects.create(
        application=application,
        kind=kind,
        file=ContentFile(upload_bytes, name=upload.name),
        original_filename=upload.name,
        content_type=getattr(upload, "content_type", "application/octet-stream"),
        file_size=upload.size,
        ocr_status=initial_status,
    )

    if kind in OCR_SUPPORTED_KINDS:
        enqueue_ocr_job(document.id)


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


def _find_reusable_guardian_document(account: ParentAccount | None) -> Document | None:
    """Return most recent active guardian identity document for *account*."""
    if account is None:
        return None
    prior_app = (
        account.applications.exclude(status=RegistrationApplication.Status.REJECTED)
        .filter(
            documents__kind=Document.Kind.GUARDIAN_IDENTITY,
            documents__deleted_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )
    if prior_app is None:
        return None
    doc = prior_app.documents.filter(
        kind=Document.Kind.GUARDIAN_IDENTITY,
        deleted_at__isnull=True,
    ).first()
    return doc if isinstance(doc, Document) else None


def _handle_guardian_doc_reuse(
    application: RegistrationApplication,
    verified_account: ParentAccount | None,
    reusable_guardian_document: Document | None = None,
) -> None:
    """Copy reusable guardian document and extraction onto *application*."""
    if application.pk is None:
        return
    if application.documents.filter(
        kind=Document.Kind.GUARDIAN_IDENTITY,
        deleted_at__isnull=True,
    ).exists():
        return

    prior_doc = reusable_guardian_document or _find_reusable_guardian_document(verified_account)
    if prior_doc is None:
        return

    try:
        import os
        from django.core.files.base import ContentFile
        file_content = prior_doc.file.read()
    except FileNotFoundError:
        return

    # Use only the basename — Document.file has upload_to="private/documents/"
    # which prepends the prefix again. Passing prior_doc.file.name (which
    # already includes the prefix) would double it on every reuse.
    new_doc = Document.objects.create(
        application=application,
        kind=prior_doc.kind,
        file=ContentFile(file_content, name=os.path.basename(prior_doc.original_filename or prior_doc.file.name)),
        original_filename=prior_doc.original_filename,
        content_type=prior_doc.content_type,
        file_size=prior_doc.file_size,
        ocr_status=prior_doc.ocr_status,
        ocr_provider=prior_doc.ocr_provider,
        ocr_last_processed_at=prior_doc.ocr_last_processed_at,
        ocr_error_code=prior_doc.ocr_error_code,
        ocr_error_detail_redacted=prior_doc.ocr_error_detail_redacted,
    )

    extraction = getattr(prior_doc, "extraction", None)
    if extraction is not None:
        DocumentExtraction.objects.create(
            document=new_doc,
            subject_role=extraction.subject_role,
            provider=extraction.provider,
            extraction_schema_version=extraction.extraction_schema_version,
            encrypted_payload=extraction.encrypted_payload,
            encrypted_summary=extraction.encrypted_summary,
        )
        _set_ocr_field_sources(application, prior_doc.kind)
    else:
        sources = dict(application.field_sources) if application.field_sources else {}
        sources["guardian_full_name"] = "manual_only"
        sources["guardian_personal_id"] = "manual_only"
        application.field_sources = sources
        application.save(update_fields=["field_sources", "updated_at"])


def create_or_update_draft(
    *,
    data: Mapping[str, Any],
    files: Mapping[str, Any],
    application: RegistrationApplication | None = None,
    verified_account: ParentAccount | None = None,
    reusable_guardian_document: Document | None = None,
) -> RegistrationApplication:
    """Create or update a draft registration application.

    Drafts store the typed email as claimed_email. A draft_session_key is
    assigned for same-browser access. Typed email is a claim only, so no
    ParentAccount lookup or linking happens here.

    When creating a new application with a reusable guardian document
    from a prior app, the document is copied and field_sources are set
    from the prior OCR extraction.
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
        application.guardian = resolve_guardian_for_account(verified_account)

    # Backward-compat aliases for old field names. "guardian_address" feeds the
    # verified-path Guardian write below; the child_* entries feed member fields.
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

    # Slice B2: when a Guardian is linked, write only the canonical Guardian
    # row; the legacy columns are not written. Unverified drafts hold only
    # claimed_email — no guardian_* column writes.
    if application.guardian_id is not None:
        _guardian = application.guardian
        _guardian.full_name = str(data.get("guardian_full_name", "")).strip()
        _guardian.personal_id = str(data.get("guardian_personal_id", "")).strip()
        _guardian.address = str(data.get("guardian_declared_address", "")).strip()
        _guardian.save(update_fields=["full_name", "personal_id", "address"])
        account = _guardian.parent_account
        new_phone = str(data.get("guardian_phone", "")).strip()
        if account is not None and new_phone and account.phone != new_phone:
            account.phone = new_phone
            account.save(update_fields=["phone", "updated_at"])
    application.member_full_name = str(data.get("member_full_name", "")).strip()
    application.member_personal_id = str(data.get("member_personal_id", "")).strip()
    application.member_birth_date = data.get("member_birth_date") or None
    application.member_same_address_as_guardian = bool(data.get("member_same_address_as_guardian", False))
    preferred = str(data.get("preferred_agreement_signing", "")).strip()
    if not preferred:
        preferred = "electronic"
    application.preferred_agreement_signing = preferred
    if "support_club_instead_of_multi_child_discount" in data:
        raw = data["support_club_instead_of_multi_child_discount"]
        application.support_club_instead_of_multi_child_discount = bool(raw) if raw is not None else None
    else:
        application.support_club_instead_of_multi_child_discount = None
    payment_mode = str(data.get("preferred_payment_mode", "")).strip()
    if not payment_mode:
        payment_mode = "installments"
    application.preferred_payment_mode = payment_mode

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

    if application.status != RegistrationApplication.Status.FIX_REQUESTED:
        application.status = RegistrationApplication.Status.DRAFT

    # Personal-data-consent stamping. Once granted, never cleared by a later
    # save: the server holds the historical record. Re-stamp only when the
    # stored version differs from the current consent text version, so an
    # idempotent re-save does not refresh the timestamp.
    # Strict `is True` — callers must pass cleaned form data (Django BooleanField yields strict bool).
    if data.get("personal_data_consent") is True:
        if (
            application.personal_data_consent_at is None
            or application.personal_data_consent_version != PERSONAL_DATA_CONSENT_VERSION
        ):
            application.personal_data_consent_at = timezone.now()
            application.personal_data_consent_version = PERSONAL_DATA_CONSENT_VERSION

    application.save()

    # Handle reusable guardian document for new applications.
    _handle_guardian_doc_reuse(application, verified_account, reusable_guardian_document)

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

    # The OCR job (when it runs synchronously in tests or completes
    # before this point in dev) writes field_sources directly to the DB,
    # so reload to avoid clobbering its update with the stale in-memory
    # copy.
    if application.pk is not None:
        application.refresh_from_db(fields=["field_sources"])

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
        attr = _GUARDIAN_SUBMIT_ACCESSORS.get(field, field)
        val = getattr(application, attr)
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

    record_audit_event(
        action=str(AuditEvent.Action.APPLICATION_FIX_REQUESTED),
        actor=reviewer,
        target=application,
        metadata={"to_status": application.status, "has_message": bool(message)},
    )

    _render_and_send_notification(
        application,
        template_name="request_fix",
        subject="Jūsu pieteikums ir jālabo",
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

    record_audit_event(
        action=str(AuditEvent.Action.APPLICATION_REJECTED),
        actor=reviewer,
        target=application,
        metadata={"to_status": application.status, "has_message": bool(message)},
    )

    _render_and_send_notification(
        application,
        template_name="reject",
        subject="Jūsu pieteikums ir noraidīts",
    )
    return application


@transaction.atomic
def approve_application(
    application: RegistrationApplication,
    reviewer: settings.AUTH_USER_MODEL,
    training_group: TrainingGroup | None = None,
) -> RegistrationApplication:
    """Approve an application, reusing the resolved Guardian and creating Member + Agreement.
    Idempotent and atomic.

    Optionally assigns the new Member to a TrainingGroup at create-time.
    Idempotent re-approval ignores the training_group argument — assignment
    edits go through apps.members.services.assign_training_group. The
    @transaction.atomic decorator guards against partial-write inconsistency
    across the three cross-table writes (Guardian, Member, Agreement).
    """
    # Idempotent: if already approved with linked member, return as-is
    if application.approved_member_id is not None:
        return application

    if application.status != RegistrationApplication.Status.SUBMITTED:
        raise ValueError("can only approve submitted application")

    if training_group is not None and not training_group.is_active:
        raise ValueError("cannot assign inactive training group at approval time")

    # Guardian is resolved at initiation and its profile is written at draft-save
    # (Slice B1), so approval just reuses it — no snapshot copy. The fallback
    # covers ORM-built applications that never went through create_or_update_draft.
    guardian = application.guardian
    if guardian is None:
        if application.parent_account_id is None:
            raise ValueError("Cannot approve an application without a parent account.")
        guardian = resolve_guardian_for_account(application.parent_account)
        application.guardian = guardian

    # Create Member linked to Guardian, optionally to a TrainingGroup
    member = Member.objects.create(
        full_name=application.member_full_name,
        personal_id=application.member_personal_id,
        birth_date=application.member_birth_date,
        guardian=guardian,
        training_group=training_group,
    )

    create_agreement_for_member(
        member,
        signing_path=(
            application.preferred_agreement_signing
            or str(Agreement.SigningPath.ELECTRONIC)
        ),
    )

    application.status = RegistrationApplication.Status.APPROVED
    application.approved_member = member
    application.reviewed_by = reviewer
    application.reviewed_at = timezone.now()
    application.save(update_fields=["status", "approved_member_id", "guardian", "reviewed_by_id", "reviewed_at", "updated_at"])

    record_audit_event(
        action=str(AuditEvent.Action.APPLICATION_APPROVED),
        actor=reviewer,
        target=application,
        metadata={"to_status": application.status, "member_id": application.approved_member_id},
    )

    _render_and_send_notification(
        application,
        template_name="approve",
        subject="Jūsu pieteikums ir apstiprināts",
    )
    return application


def _render_and_send_notification(
    application: RegistrationApplication,
    template_name: str,
    subject: str,
    extra_context: dict | None = None,
) -> None:
    """Render a plain-text email template and send it to the guardian.

    Templates live under ``templates/emails/registrations/<template_name>.txt``.
    Absolute URLs are built from ``settings.SITE_URL`` so links work outside
    the request cycle (admin review actions run without a live request).
    """
    application_path = reverse(
        "registrations:application-workspace", args=[application.id]
    )
    portal_path = reverse("registrations:parent-portal")
    context: dict[str, Any] = {
        "application": application,
        "member_full_name": application.member_full_name,
        "guardian_full_name": application.guardian_name,
        "review_message": application.review_message or "",
        "application_url": f"{settings.SITE_URL}{application_path}",
        "portal_url": f"{settings.SITE_URL}{portal_path}",
    }
    if extra_context:
        context.update(extra_context)
    body = render_to_string(f"emails/registrations/{template_name}.txt", context)
    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[application.guardian_contact_email],
        fail_silently=False,
    )

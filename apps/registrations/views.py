"""Views for parent registration workflow."""

from typing import cast

from django.conf import settings
from django.core.files.base import ContentFile
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.accounts.services import issue_one_time_code, send_one_time_code_email
from apps.documents.models import Document
from apps.documents.ocr import decrypt_json
from apps.integrations.ocr import OCR_SUPPORTED_KINDS
from apps.integrations.ocr_messages import get_ocr_error_message
from apps.integrations.tasks import enqueue_ocr_job
from apps.members.models import TrainingGroup
from apps.members.services import assign_training_group
from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.messages import (
    CONSENT_REQUIRED,
    SAVE_INDICATOR_ERROR,
    SAVE_INDICATOR_SAVED,
    SAVE_INDICATOR_SAVING,
    STEP_FIELD_FORMAT,
    STEP_FIELD_REQUIRED,
)
from apps.registrations.models import (
    PERSONAL_DATA_CONSENT_VERSION,
    RegistrationApplication,
)
from apps.registrations.presentation import (
    DOCUMENT_FIELD_ID_MAP,
    DOCUMENT_KIND_LABELS,
    FIELD_KIND_LABELS,
    FIELD_NAME_BY_KIND,
    OCR_FIELD_LABELS,
    active_documents_by_kind,
    documents_by_field_name,
    parse_ocr_summary,
    source_label,
    workspace_mode,
)
from apps.registrations.services import (
    approve_application,
    can_edit_application,
    create_or_update_draft,
    get_application_prefill,
    reject_application,
    request_application_fix,
    submit_application,
)


def _has_reusable_guardian_document(account: ParentAccount) -> bool:
    """Return True when the account has a prior non-rejected application
    with an active guardian identity document."""
    has = RegistrationApplication.objects.filter(
        parent_account=account,
    ).exclude(
        status=RegistrationApplication.Status.REJECTED,
    ).exclude(
        status__isnull=True,
    ).filter(
        documents__kind=Document.Kind.GUARDIAN_IDENTITY,
        documents__deleted_at__isnull=True,
    ).exists()
    return bool(has)


def _get_reusable_guardian_document(account: ParentAccount) -> Document | None:
    """Return the active guardian identity document from the most recent
    prior non-rejected application, or None."""
    prior_app = (
        RegistrationApplication.objects.filter(
            parent_account=account,
        )
        .exclude(status=RegistrationApplication.Status.REJECTED)
        .exclude(status__isnull=True)
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
    ).select_related("extraction").first()
    return doc if isinstance(doc, Document) else None


def _current_parent_account(request: HttpRequest) -> ParentAccount | None:
    account_id = request.session.get(PARENT_ACCOUNT_SESSION_KEY)
    if not account_id:
        return None
    result: ParentAccount | None = ParentAccount.objects.filter(pk=account_id).first()
    return result


def _active_guardian_identity_exists(application: RegistrationApplication) -> bool:
    result: bool = application.documents.filter(
        kind=Document.Kind.GUARDIAN_IDENTITY,
        deleted_at__isnull=True,
    ).exists()
    return result


def _parent_can_view_application(
    application: RegistrationApplication,
    parent_account: ParentAccount | None,
) -> bool:
    result: bool = bool(
        parent_account and application.parent_account_id == parent_account.id
    )
    return result


def new_application(request: HttpRequest) -> HttpResponse:
    """GET /applications/new/ — bootstrap a fresh draft + redirect to workspace.

    P3.5: file uploads need an application_id (async endpoint scope), so
    /applications/new/ no longer renders its own form. On GET we always
    create a new blank draft (with guardian prefill from prior apps +
    reusable guardian doc copy) and redirect to /applications/<id>/, where
    async uploads work. Continuing an existing draft is the parent portal's
    job — this route is the explicit "start fresh" action.

    The synchronous POST path is retained as a no-JS fallback for clients
    that POST directly to this route (legacy bookmarks etc.).
    """
    account = _current_parent_account(request)
    if account is None:
        return redirect("registrations:start-registration")

    reusable_doc = _get_reusable_guardian_document(account)
    has_existing = reusable_doc is not None

    if request.method == "POST":
        form = RegistrationApplicationForm(
            request.POST,
            request.FILES,
            is_submit=False,
            has_existing_document=has_existing,
        )
        if form.is_valid():
            application = create_or_update_draft(
                data=form.cleaned_data,
                files=request.FILES,
                verified_account=account,
                reusable_guardian_document=reusable_doc if has_existing else None,
            )
            return redirect("registrations:application-workspace", application_id=application.id)
        return render(
            request,
            "registrations/new_registration.html",
            {
                "form": form,
                "field_source_labels": {},
                "has_reusable_guardian_document": has_existing,
            },
        )

    # GET: always create a fresh blank draft and redirect to its workspace.
    # "New registration" must be unconditional — continuing an existing draft
    # is the parent portal's job, not this route's.
    prefill = get_application_prefill(account)
    application = create_or_update_draft(
        data=prefill,
        files={},
        verified_account=account,
        reusable_guardian_document=reusable_doc if has_existing else None,
    )
    return redirect(
        "registrations:application-workspace", application_id=application.id
    )


# ---------------------------------------------------------------------------
# Canonical application workspace
# ---------------------------------------------------------------------------


def application_workspace(request: HttpRequest, application_id: int) -> HttpResponse:
    """Unified application workspace — editable for draft/fix, read-only otherwise."""
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404

    editable = application.is_editable_by(account)

    if request.method == "POST":
        if not editable:
            raise Http404
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        # AJAX auto-save must never submit, even if the payload includes
        # submit_action=submit. Submission is a deliberate user click.
        submit_requested = (
            request.POST.get("submit_action") == "submit" and not is_ajax
        )
        form = RegistrationApplicationForm(
            request.POST,
            request.FILES,
            is_submit=submit_requested,
            has_existing_document=_active_guardian_identity_exists(application),
        )
        if form.is_valid():
            try:
                application = create_or_update_draft(
                    data=form.cleaned_data,
                    files=request.FILES,
                    application=application,
                    verified_account=account,
                )
            except ValueError as exc:
                if is_ajax:
                    return JsonResponse(
                        {"errors": [{"field": "__all__", "label": "", "message": str(exc)}]},
                        status=400,
                    )
                raise
            if is_ajax:
                saved_at = timezone.now().replace(microsecond=0).isoformat()
                return JsonResponse(
                    {
                        "saved_at": saved_at,
                        "consent_recorded": bool(application.personal_data_consent_at),
                    },
                    status=200,
                )
            if submit_requested:
                submit_application(application, account)
                return redirect("registrations:parent-portal")
            return redirect("registrations:application-workspace", application_id=application.id)
        elif is_ajax:
            return JsonResponse(
                {"errors": form.error_summary_items()},
                status=400,
            )
    else:
        form = RegistrationApplicationForm(
            initial={
                "guardian_full_name": application.guardian_full_name,
                "guardian_personal_id": application.guardian_personal_id,
                "guardian_email": application.guardian_email,
                "guardian_phone": application.guardian_phone,
                "guardian_declared_address": application.guardian_declared_address,
                "member_full_name": application.member_full_name,
                "member_personal_id": application.member_personal_id,
                "member_birth_date": application.member_birth_date,
                "member_actual_address": application.member_actual_address,
                "member_same_address_as_guardian": application.member_same_address_as_guardian,
                "member_kit_size_shirt": application.member_kit_size_shirt_id,
                "member_kit_size_shorts": application.member_kit_size_shorts_id,
                "preferred_agreement_signing": application.preferred_agreement_signing,
                "support_club_instead_of_multi_child_discount": application.support_club_instead_of_multi_child_discount,
            }
        )

    ocr_decrypted_summaries: dict[str, list[tuple[str, str]] | None] = {}
    for doc in application.documents.filter(deleted_at__isnull=True).select_related("extraction"):
        extraction = getattr(doc, "extraction", None)
        if extraction is None or not extraction.encrypted_summary:
            continue
        try:
            summary = decrypt_json(extraction.encrypted_summary)
            ocr_decrypted_summaries[doc.kind] = parse_ocr_summary(str(summary))
        except Exception:
            ocr_decrypted_summaries[doc.kind] = None

    import json as _json

    pending_docs_qs = application.documents.filter(
        deleted_at__isnull=True,
        ocr_status=Document.OcrStatus.PENDING,
    )
    pending_by_kind = {doc.kind: doc.id for doc in pending_docs_qs}
    pending_document_ids_csv = ",".join(str(i) for i in pending_by_kind.values())
    pending_by_kind_json = _json.dumps(pending_by_kind)

    document_bound_fields = {
        kind: form[field_name]
        for kind, field_name in FIELD_NAME_BY_KIND.items()
    }

    return render(
        request,
        "registrations/application_workspace.html",
        {
            "application": application,
            "form": form,
            "workspace_mode": workspace_mode(application, account),
            "document_state": active_documents_by_kind(application),
            "document_by_field": documents_by_field_name(application),
            "field_kind_labels": FIELD_KIND_LABELS,
            "document_field_id_map": DOCUMENT_FIELD_ID_MAP,
            "document_kind_labels": DOCUMENT_KIND_LABELS,
            "document_bound_fields": document_bound_fields,
            "field_source_labels": {
                name: source_label(value)
                for name, value in (application.field_sources or {}).items()
            },
            "ocr_decrypted_summaries": ocr_decrypted_summaries,
            "pending_document_ids_csv": pending_document_ids_csv,
            "pending_by_kind_json": pending_by_kind_json,
            # P4 Slice C — Latvian copy + version constant for the consent
            # gate, step-gating inline errors, and the auto-save indicator.
            # Centralised in `apps.registrations.messages` so no inline
            # English fallback can leak into parent-facing markup.
            "step_field_required_msg": STEP_FIELD_REQUIRED,
            "step_field_format_msg": STEP_FIELD_FORMAT,
            "consent_required_msg": CONSENT_REQUIRED,
            "save_indicator_saving_msg": SAVE_INDICATOR_SAVING,
            "save_indicator_saved_msg": SAVE_INDICATOR_SAVED,
            "save_indicator_error_msg": SAVE_INDICATOR_ERROR,
            "personal_data_consent_version": PERSONAL_DATA_CONSENT_VERSION,
        },
    )


def redirect_to_workspace(request: HttpRequest, application_id: int) -> HttpResponse:
    """Redirect legacy routes to canonical workspace.

    Non-owners get 404. All authorised owners are redirected to the
    canonical workspace regardless of application editability.
    """
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404
    return redirect("registrations:application-workspace", application_id=application.id)


def start_registration(request: HttpRequest) -> HttpResponse:
    """Guardian email entry route.

    GET: shows email entry page.
    POST: issues 6-digit one-time code, stores pending_verification_email
    in session, redirects to /register/verify/.
    """
    account = _current_parent_account(request)

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        if not email:
            return render(
                request,
                "registrations/start_registration.html",
                {"form": None, "error": "Ievadiet e-pasta adresi."},
            )

        try:
            raw_code = issue_one_time_code(email)
        except ValueError:
            return render(
                request,
                "registrations/start_registration.html",
                {"form": None, "error": "Pārāk daudz pieprasījumu. Mēģiniet vēlāk."},
            )
        send_one_time_code_email(email, raw_code)

        # Store pending email in session
        request.session["pending_verification_email"] = email

        return redirect("accounts:verify-one-time-code")

    return render(request, "registrations/start_registration.html", {"form": None})


def edit_registration(request: HttpRequest, application_id: int) -> HttpResponse:
    """Redirect legacy edit route to canonical workspace."""
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404
    return redirect("registrations:application-workspace", application_id=application.id)


def submit_registration(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if request.method != "POST":
        raise Http404

    allowed = can_edit_application(application, account)
    if not allowed:
        raise Http404

    form = RegistrationApplicationForm(
        request.POST,
        request.FILES,
        is_submit=True,
        has_existing_document=_active_guardian_identity_exists(application),
    )
    if form.is_valid():
        application = create_or_update_draft(
            data=form.cleaned_data,
            files=request.FILES,
            application=application,
            verified_account=account,
        )
        submit_application(application, account)
        return redirect("registrations:parent-portal")

    return render(
        request,
        "registrations/application_workspace.html",
        {
            "form": form,
            "application": application,
            "workspace_mode": workspace_mode(application, account),
            "document_state": active_documents_by_kind(application),
            "document_by_field": documents_by_field_name(application),
            "field_kind_labels": FIELD_KIND_LABELS,
            "document_field_id_map": DOCUMENT_FIELD_ID_MAP,
            "document_kind_labels": DOCUMENT_KIND_LABELS,
            "document_bound_fields": {
                kind: form[field_name]
                for kind, field_name in FIELD_NAME_BY_KIND.items()
            },
            "field_source_labels": {
                name: source_label(value)
                for name, value in (application.field_sources or {}).items()
            },
        },
        status=400,
    )


def _portal_primary_application(account: ParentAccount) -> RegistrationApplication | None:
    application = (
        account.applications.filter(
            status__in=(
                RegistrationApplication.Status.DRAFT,
                RegistrationApplication.Status.FIX_REQUESTED,
            )
        )
        .order_by("-updated_at", "-created_at")
        .first()
    )
    return cast(RegistrationApplication | None, application)


def parent_portal(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if account is None:
        return redirect("registrations:start-registration")

    # Handle continue-draft POST action
    if request.method == "POST" and request.POST.get("action") == "continue_draft":
        draft = _portal_primary_application(account)
        if draft:
            return redirect("registrations:application-workspace", application_id=draft.id)

    # Show all applications linked to this verified parent
    applications = account.applications.order_by("-created_at")
    has_draft = applications.filter(
        status__in=(
            RegistrationApplication.Status.DRAFT,
            RegistrationApplication.Status.FIX_REQUESTED,
        )
    ).exists()
    # Annotate each application with an is_editable flag for the template.
    for app in applications:
        app.can_edit = app.is_editable_by(account)
    return render(
        request,
        "registrations/parent_portal.html",
        {
            "account": account,
            "applications": applications,
            "has_draft": has_draft,
            "primary_application": _portal_primary_application(account),
        },
    )


def view_registration_summary(request: HttpRequest, application_id: int) -> HttpResponse:
    """Redirect legacy summary route to canonical workspace."""
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404
    return redirect("registrations:application-workspace", application_id=application.id)


def view_registration_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    """Redirect legacy detail route to canonical workspace."""
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404
    return redirect("registrations:application-workspace", application_id=application.id)


# ---------------------------------------------------------------------------
# Staff review views
# ---------------------------------------------------------------------------


def _require_staff(request: HttpRequest) -> HttpResponse | None:
    """Redirect anonymous to admin login; 404 non-staff."""
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path(), "admin:login")
    if not request.user.is_staff:
        raise Http404
    return None  # type: ignore[return-value]


def admin_review_queue(request: HttpRequest) -> HttpResponse:
    """Staff-only queue of submitted applications."""
    result = _require_staff(request)
    if result is not None:
        return result
    applications = RegistrationApplication.objects.filter(
        status=RegistrationApplication.Status.SUBMITTED
    ).order_by("-submitted_at")
    return render(
        request,
        "registrations/admin_review_queue.html",
        {"applications": applications},
    )


_IMAGE_PREVIEW_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic"})
_PDF_PREVIEW_EXTENSIONS = frozenset({"pdf"})


def _doc_preview_kind(document: object) -> str:
    """Classify a Document by file extension for inline-preview rendering.

    Returns ``"image"`` for image extensions (jpg/jpeg/png/webp/heic),
    ``"pdf"`` for PDF, and ``"other"`` for everything else (including missing
    or empty filenames). Uses ``original_filename`` when present, else
    ``document.file.name``. Comparison is case-insensitive.
    """
    filename = getattr(document, "original_filename", "") or ""
    if not filename:
        file_obj = getattr(document, "file", None)
        filename = getattr(file_obj, "name", "") or ""
    if "." not in filename:
        return "other"
    extension = filename.rsplit(".", 1)[1].lower()
    if extension in _IMAGE_PREVIEW_EXTENSIONS:
        return "image"
    if extension in _PDF_PREVIEW_EXTENSIONS:
        return "pdf"
    return "other"


def _build_doc_panel(
    application: RegistrationApplication, kind: str
) -> dict[str, object]:
    """Build the per-kind panel context dict consumed by _doc_panel.html."""
    documents = application.documents.filter(kind=kind)
    active = (
        documents.filter(deleted_at__isnull=True)
        .select_related("extraction")
        .first()
    )
    replaced = list(
        documents.filter(deleted_at__isnull=False).order_by("-created_at")
    )
    for replaced_doc in replaced:
        replaced_doc.preview_kind = _doc_preview_kind(replaced_doc)

    ocr_summary: list[tuple[str, str]] = []
    ocr_confidence_items: list[tuple[str, object]] = []
    if active is not None and kind != Document.Kind.MEMBER_PORTRAIT:
        extraction = getattr(active, "extraction", None)
        if extraction is not None:
            try:
                summary_value = decrypt_json(extraction.encrypted_summary)
                if isinstance(summary_value, str):
                    ocr_summary = parse_ocr_summary(summary_value)
                payload_value = decrypt_json(extraction.encrypted_payload)
                if isinstance(payload_value, dict):
                    confidence = payload_value.get("confidence")
                    if isinstance(confidence, dict):
                        ocr_confidence_items = [
                            (
                                OCR_FIELD_LABELS.get(
                                    str(key), str(key).replace("_", " ").title()
                                ),
                                value,
                            )
                            for key, value in confidence.items()
                        ]
            except Exception:
                ocr_summary = []
                ocr_confidence_items = []

    return {
        "kind": kind,
        "panel_title": DOCUMENT_KIND_LABELS.get(kind, kind),
        "active": active,
        "replaced": replaced,
        "ocr_summary": ocr_summary,
        "ocr_confidence_items": ocr_confidence_items,
        "preview_kind": _doc_preview_kind(active) if active is not None else "",
    }


def admin_review_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    """Staff-only detail page with review actions."""
    result = _require_staff(request)
    if result is not None:
        return result
    application = get_object_or_404(RegistrationApplication, pk=application_id)

    guardian_panel = _build_doc_panel(application, str(Document.Kind.GUARDIAN_IDENTITY))
    member_panel = _build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY))
    portrait_panel = _build_doc_panel(application, str(Document.Kind.MEMBER_PORTRAIT))

    active_training_groups = list(
        TrainingGroup.objects.filter(is_active=True).order_by("name")
    )

    current_inactive_group = None
    if application.approved_member_id is not None:
        assigned = application.approved_member.training_group
        if assigned is not None and not assigned.is_active:
            current_inactive_group = assigned

    context: dict[str, object] = {
        "application": application,
        "guardian_panel": guardian_panel,
        "member_panel": member_panel,
        "portrait_panel": portrait_panel,
        "active_training_groups": active_training_groups,
        "current_inactive_group": current_inactive_group,
    }

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "request_fix":
            message = request.POST.get("review_message", "").strip()
            try:
                request_application_fix(application, request.user, message)
            except ValueError:
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": "Labojuma ziņojums ir obligāts."},
                    status=400,
                )
            return redirect("registrations:admin-review-detail", application_id=application.id)

        elif action == "reject":
            message = request.POST.get("review_message", "").strip()
            try:
                reject_application(application, request.user, message)
            except ValueError:
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": "Noraidīšanas ziņojums ir obligāts."},
                    status=400,
                )
            return redirect("registrations:admin-review-queue")

        elif action == "approve":
            raw_group = request.POST.get("training_group", "").strip()
            selected_group = None
            if raw_group:
                try:
                    selected_group = TrainingGroup.objects.get(pk=int(raw_group))
                except (TrainingGroup.DoesNotExist, ValueError):
                    return render(
                        request,
                        "registrations/admin_review_detail.html",
                        {**context, "error": "Nezināma treniņu grupa."},
                        status=400,
                    )
            try:
                approve_application(
                    application, request.user, training_group=selected_group
                )
            except ValueError as exc:
                message = str(exc)
                if "inactive" in message:
                    latvian = "Nevar piešķirt neaktīvu treniņu grupu apstiprināšanas brīdī."
                elif "submitted" in message:
                    latvian = "Var apstiprināt tikai iesniegtus pieteikumus."
                else:
                    latvian = "Pieteikumu nevarēja apstiprināt."
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": latvian},
                    status=400,
                )
            return redirect("registrations:admin-review-queue")

        elif action == "assign_training_group":
            if application.approved_member_id is None:
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": "Var piešķirt grupu tikai apstiprinātam pieteikumam."},
                    status=400,
                )
            raw_group = request.POST.get("training_group", "").strip()
            selected_group = None
            if raw_group:
                try:
                    selected_group = TrainingGroup.objects.get(pk=int(raw_group))
                except (TrainingGroup.DoesNotExist, ValueError):
                    return render(
                        request,
                        "registrations/admin_review_detail.html",
                        {**context, "error": "Nezināma treniņu grupa."},
                        status=400,
                    )
            assign_training_group(
                application.approved_member, selected_group, request.user
            )
            return redirect(
                "registrations:admin-review-detail", application_id=application.id
            )

    return render(request, "registrations/admin_review_detail.html", context)


# ---------------------------------------------------------------------------
# Async document upload + status polling (P3.5)
# ---------------------------------------------------------------------------


_VALID_DOCUMENT_KINDS = frozenset(value for value, _label in Document.Kind.choices)


def _ocr_extracted_fields(document: Document) -> dict[str, str]:
    """Map a completed Document's extraction to form-field-keyed values."""
    extraction = getattr(document, "extraction", None)
    if extraction is None:
        return {}
    try:
        payload = decrypt_json(extraction.encrypted_payload)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    person_fields = payload.get("person_fields") or {}
    if not isinstance(person_fields, dict):
        return {}

    first = str(person_fields.get("first_name", "")).strip()
    last = str(person_fields.get("last_name", "")).strip()
    pid = str(person_fields.get("personal_id", "")).strip()
    full_name = " ".join(part for part in (first, last) if part)

    fields: dict[str, str] = {}
    if document.kind == Document.Kind.GUARDIAN_IDENTITY:
        if full_name:
            fields["guardian_full_name"] = full_name
        if pid:
            fields["guardian_personal_id"] = pid
    elif document.kind == Document.Kind.MEMBER_IDENTITY:
        if full_name:
            fields["member_full_name"] = full_name
        if pid:
            fields["member_personal_id"] = pid
        dob = str(person_fields.get("date_of_birth", "")).strip()
        if dob:
            fields["member_birth_date"] = dob
    return fields


def _json_error(code: str, status: int, **extra: object) -> JsonResponse:
    payload: dict[str, object] = {"error": code, **extra}
    return JsonResponse(payload, status=status)


@require_POST
def async_document_upload(
    request: HttpRequest, application_id: int
) -> HttpResponse:
    """POST /applications/<id>/documents/ — async upload + enqueue OCR.

    Returns 201 with JSON {document_id, kind, ocr_status} on success.
    """
    account = _current_parent_account(request)
    if account is None:
        return _json_error("not_authenticated", status=401)

    application = RegistrationApplication.objects.filter(pk=application_id).first()
    if application is None or application.parent_account_id != account.id:
        return _json_error("not_found", status=404)

    kind = request.POST.get("kind", "").strip()
    if kind not in _VALID_DOCUMENT_KINDS:
        return _json_error("invalid_kind", status=400)

    upload = request.FILES.get("file")
    if upload is None:
        return _json_error("missing_file", status=400)

    max_bytes = getattr(settings, "DOCUMENT_UPLOAD_MAX_BYTES", 8 * 1024 * 1024)
    if upload.size > max_bytes:
        return _json_error("file_too_large", status=413, max_bytes=max_bytes)

    allowed_types = getattr(
        settings,
        "DOCUMENT_UPLOAD_ALLOWED_CONTENT_TYPES",
        ("image/jpeg", "image/png", "image/webp", "application/pdf"),
    )
    content_type = getattr(upload, "content_type", "") or ""
    if content_type not in allowed_types:
        return _json_error("invalid_content_type", status=400)

    # Soft-delete prior active doc of the same kind.
    prior = application.documents.filter(
        kind=kind, deleted_at__isnull=True
    ).first()
    if prior is not None:
        prior.deleted_at = timezone.now()
        prior.save(update_fields=["deleted_at", "updated_at"])

    initial_status = (
        Document.OcrStatus.PENDING
        if kind in OCR_SUPPORTED_KINDS
        else Document.OcrStatus.NOT_REQUESTED
    )
    upload_bytes = upload.read()
    document = Document.objects.create(
        application=application,
        kind=kind,
        file=ContentFile(upload_bytes, name=upload.name),
        original_filename=upload.name,
        content_type=content_type,
        file_size=upload.size,
        ocr_status=initial_status,
    )

    if kind in OCR_SUPPORTED_KINDS:
        enqueue_ocr_job(document.id)

    return JsonResponse(
        {
            "document_id": document.id,
            "kind": document.kind,
            "ocr_status": document.ocr_status,
        },
        status=201,
    )


def document_ocr_status(
    request: HttpRequest, application_id: int, document_id: int
) -> HttpResponse:
    """GET /applications/<id>/documents/<doc_id>/status/ — polling endpoint."""
    account = _current_parent_account(request)
    if account is None:
        return _json_error("not_authenticated", status=401)

    document = (
        Document.objects.select_related("application", "extraction")
        .filter(pk=document_id, application_id=application_id)
        .first()
    )
    if document is None or document.application.parent_account_id != account.id:
        return _json_error("not_found", status=404)

    payload: dict[str, object] = {
        "ocr_status": document.ocr_status,
        "extracted_fields": _ocr_extracted_fields(document)
        if document.ocr_status == Document.OcrStatus.COMPLETED
        else {},
    }
    if document.ocr_status == Document.OcrStatus.FAILED:
        if document.ocr_error_code:
            payload["ocr_error_code"] = document.ocr_error_code
        payload["ocr_error_message"] = get_ocr_error_message(document.ocr_error_code)
    return JsonResponse(payload)

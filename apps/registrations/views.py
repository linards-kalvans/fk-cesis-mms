"""Views for parent registration workflow."""

from typing import cast

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.accounts.services import issue_one_time_code, send_one_time_code_email
from apps.documents.models import Document
from apps.documents.ocr import decrypt_json
from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.models import RegistrationApplication
from apps.registrations.presentation import (
    DOCUMENT_FIELD_ID_MAP,
    DOCUMENT_KIND_LABELS,
    FIELD_KIND_LABELS,
    active_documents_by_kind,
    documents_by_field_name,
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
    """GET /applications/new/ — requires verified parent account.

    Guardian fields are prefilled from the verified account / latest
    application. Member/child fields are NOT prefilled.
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

    prefill = get_application_prefill(account)
    form = RegistrationApplicationForm(initial=prefill)
    return render(
        request,
        "registrations/new_registration.html",
        {
            "form": form,
            "field_source_labels": {},
            "has_reusable_guardian_document": has_existing,
        },
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
        form = RegistrationApplicationForm(
            request.POST,
            request.FILES,
            is_submit=request.POST.get("submit_action") == "submit",
            has_existing_document=_active_guardian_identity_exists(application),
        )
        if form.is_valid():
            application = create_or_update_draft(
                data=form.cleaned_data,
                files=request.FILES,
                application=application,
                verified_account=account,
            )
            if request.POST.get("submit_action") == "submit":
                submit_application(application, account)
                return redirect("registrations:parent-portal")
            return redirect("registrations:application-workspace", application_id=application.id)
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

    ocr_decrypted_summaries: dict[str, str | None] = {}
    for doc in application.documents.filter(deleted_at__isnull=True).select_related("extraction"):
        extraction = getattr(doc, "extraction", None)
        if extraction is None or not extraction.encrypted_summary:
            continue
        try:
            summary = decrypt_json(extraction.encrypted_summary)
            ocr_decrypted_summaries[doc.kind] = str(summary)
        except Exception:
            ocr_decrypted_summaries[doc.kind] = None

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
            "field_source_labels": {
                name: source_label(value)
                for name, value in (application.field_sources or {}).items()
            },
            "ocr_decrypted_summaries": ocr_decrypted_summaries,
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


def admin_review_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    """Staff-only detail page with review actions."""
    result = _require_staff(request)
    if result is not None:
        return result
    application = get_object_or_404(RegistrationApplication, pk=application_id)

    active_guardian_doc = application.documents.filter(
        kind=Document.Kind.GUARDIAN_IDENTITY,
        deleted_at__isnull=True,
    ).select_related("extraction").first()
    active_member_doc = application.documents.filter(
        kind=Document.Kind.MEMBER_IDENTITY,
        deleted_at__isnull=True,
    ).select_related("extraction").first()

    ocr_decrypted: dict[str, object | None] = {}
    ocr_confidence: dict[str, dict[str, object]] = {}
    for doc in [active_guardian_doc, active_member_doc]:
        if doc is None:
            continue
        extraction = getattr(doc, "extraction", None)
        if extraction is None:
            continue
        try:
            payload = decrypt_json(extraction.encrypted_payload)
            summary = decrypt_json(extraction.encrypted_summary)
            ocr_decrypted[doc.kind] = payload if isinstance(payload, dict) else None
            ocr_decrypted[f"{doc.kind}_summary"] = summary
            if isinstance(payload, dict) and isinstance(payload.get("confidence"), dict):
                ocr_confidence[doc.kind] = payload["confidence"]
        except Exception:
            ocr_decrypted[doc.kind] = None
            ocr_decrypted[f"{doc.kind}_summary"] = None
            ocr_confidence[doc.kind] = {}

    context = {
        "application": application,
        "active_guardian_doc": active_guardian_doc,
        "active_member_doc": active_member_doc,
        "ocr_decrypted": ocr_decrypted,
        "ocr_confidence": ocr_confidence,
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
            try:
                approve_application(application, request.user)
            except ValueError:
                return render(
                    request,
                    "registrations/admin_review_detail.html",
                    {**context, "error": "Var apstiprināt tikai iesniegtus pieteikumus."},
                    status=400,
                )
            return redirect("registrations:admin-review-queue")

    return render(request, "registrations/admin_review_detail.html", context)

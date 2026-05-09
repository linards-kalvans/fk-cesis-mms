"""Views for parent registration workflow."""

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.accounts.services import issue_one_time_code, send_one_time_code_email
from apps.documents.models import Document
from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    can_edit_application,
    create_or_update_draft,
    get_application_prefill,
    reject_application,
    request_application_fix,
    submit_application,
)


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

    if request.method == "POST":
        form = RegistrationApplicationForm(
            request.POST,
            request.FILES,
            is_submit=False,
            has_existing_document=False,
        )
        if form.is_valid():
            application = create_or_update_draft(
                data=form.cleaned_data,
                files=request.FILES,
                verified_account=account,
            )
            return redirect("registrations:edit-registration", application_id=application.id)
        return render(
            request,
            "registrations/new_registration.html",
            {"form": form},
        )

    prefill = get_application_prefill(account)
    form = RegistrationApplicationForm(initial=prefill)
    return render(
        request,
        "registrations/new_registration.html",
        {"form": form},
    )


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
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)

    # Verified-parent gate only
    if not can_edit_application(application, account):
        raise Http404

    if request.method == "POST":
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
            return redirect("registrations:edit-registration", application_id=application.id)
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
    return render(
        request,
        "registrations/edit_registration.html",
        {"form": form, "application": application},
    )


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
        "registrations/edit_registration.html",
        {"form": form, "application": application},
        status=400,
    )


def parent_portal(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if account is None:
        return redirect("registrations:start-registration")

    # Handle continue-draft POST action
    if request.method == "POST" and request.POST.get("action") == "continue_draft":
        draft = (
            account.applications.filter(status=RegistrationApplication.Status.DRAFT)
            .order_by("-created_at")
            .first()
        )
        if draft:
            return redirect("registrations:edit-registration", application_id=draft.id)

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
        },
    )


def view_registration_summary(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404

    return render(
        request,
        "registrations/view_registration_summary.html",
        {"application": application},
    )


def view_registration_detail(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not _parent_can_view_application(application, account):
        raise Http404

    return render(
        request,
        "registrations/view_registration_detail.html",
        {"application": application},
    )


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

    # Determine active guardian identity document for preview link
    active_doc = application.documents.filter(
        kind=Document.Kind.GUARDIAN_IDENTITY,
        deleted_at__isnull=True,
    ).first()

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
                    {
                        "application": application,
                        "active_doc": active_doc,
                        "error": "Labojuma ziņojums ir obligāts.",
                    },
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
                    {
                        "application": application,
                        "active_doc": active_doc,
                        "error": "Noraidīšanas ziņojums ir obligāts.",
                    },
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
                    {
                        "application": application,
                        "active_doc": active_doc,
                        "error": "Var apstiprināt tikai iesniegtus pieteikumus.",
                    },
                    status=400,
                )
            return redirect("registrations:admin-review-queue")

    return render(
        request,
        "registrations/admin_review_detail.html",
        {
            "application": application,
            "active_doc": active_doc,
        },
    )

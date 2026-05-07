"""Views for parent registration workflow."""

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.documents.models import Document
from apps.registrations.forms import RegistrationApplicationForm
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    can_edit_application,
    create_or_update_draft,
    get_application_prefill,
    submit_application,
)


def _current_parent_account(request: HttpRequest) -> ParentAccount | None:
    account_id = request.session.get(PARENT_ACCOUNT_SESSION_KEY)
    if not account_id:
        return None
    result: ParentAccount | None = ParentAccount.objects.filter(pk=account_id).first()
    return result


def _active_document_exists(application: RegistrationApplication) -> bool:
    result: bool = application.documents.filter(
        kind=Document.Kind.CHILD_IDENTITY,
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


def start_registration(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if request.method == "POST":
        form = RegistrationApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = create_or_update_draft(
                data=form.cleaned_data,
                files=request.FILES,
                verified_account=account,
            )
            # Store session key for same-browser draft continuity
            request.session["draft_session_key"] = str(application.draft_session_key)
            # If there's a verified parent account, store that too.
            if application.parent_account_id:
                request.session[PARENT_ACCOUNT_SESSION_KEY] = application.parent_account_id
            return redirect("registrations:edit-registration", application_id=application.id)
    else:
        form = RegistrationApplicationForm(initial=get_application_prefill(account))
    return render(request, "registrations/start_registration.html", {"form": form})


def edit_registration(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)

    # Check ownership: either verified parent or same-browser session key
    if not can_edit_application(application, account):
        # Same-browser check via draft_session_key stored in session
        session_key = request.session.get("draft_session_key")
        if session_key and str(application.draft_session_key) == session_key:
            # Grant access for same-browser continuity
            pass
        else:
            raise Http404

    if request.method == "POST":
        form = RegistrationApplicationForm(
            request.POST,
            request.FILES,
            is_submit=request.POST.get("submit_action") == "submit",
            has_existing_document=_active_document_exists(application),
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
                "guardian_address": application.guardian_address,
                "child_full_name": application.child_full_name,
                "child_personal_id": application.child_personal_id,
                "child_birth_date": application.child_birth_date,
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
        session_key = request.session.get("draft_session_key")
        allowed = bool(session_key and str(application.draft_session_key) == session_key)
    if not allowed:
        raise Http404

    form = RegistrationApplicationForm(
        request.POST,
        request.FILES,
        is_submit=True,
        has_existing_document=_active_document_exists(application),
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
        return redirect("accounts:request-magic-link")
    # Only show applications linked to this verified parent (parent_account FK)
    applications = account.applications.filter(parent_account=account).order_by("-created_at")
    # Annotate each application with an is_editable flag for the template.
    for app in applications:
        app.can_edit = app.is_editable_by(account)
    return render(
        request,
        "registrations/parent_portal.html",
        {"account": account, "applications": applications},
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

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


def start_registration(request: HttpRequest) -> HttpResponse:
    account = _current_parent_account(request)
    if request.method == "POST":
        form = RegistrationApplicationForm(request.POST, request.FILES)
        if form.is_valid():
            application = create_or_update_draft(data=form.cleaned_data, files=request.FILES)
            request.session[PARENT_ACCOUNT_SESSION_KEY] = application.parent_account_id
            return redirect("registrations:edit-registration", application_id=application.id)
    else:
        form = RegistrationApplicationForm(initial=get_application_prefill(account))
    return render(request, "registrations/start_registration.html", {"form": form})


def edit_registration(request: HttpRequest, application_id: int) -> HttpResponse:
    application = get_object_or_404(RegistrationApplication, pk=application_id)
    account = _current_parent_account(request)
    if not can_edit_application(application, account):
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
            )
            if request.POST.get("submit_action") == "submit":
                assert account is not None
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
    if request.method != "POST" or account is None or not can_edit_application(application, account):
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
    applications = account.applications.order_by("-created_at")
    return render(
        request,
        "registrations/parent_portal.html",
        {"account": account, "applications": applications},
    )

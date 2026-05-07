"""Views for magic-link auth flow."""

from typing import cast

from django.urls import reverse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django.conf import settings

from apps.accounts.forms import MagicLinkRequestForm
from apps.accounts.models import ParentAccount
from apps.accounts.services import (
    consume_magic_link,
    issue_magic_link,
    issue_magic_link_for_email,
    send_magic_link,
    send_magic_link_for_claimed_email,
)
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY


def _debug_verify_url_for_request(request, raw_token: str) -> str:
    path = reverse("accounts:verify-magic-link", args=[raw_token])
    return cast(str, request.build_absolute_uri(path))


def request_magic_link(request):
    """POST /accounts/request-magic-link/ — issue and send a magic link."""
    if request.method == "POST":
        form = MagicLinkRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            account = ParentAccount.objects.filter(email=email).first()
            show_debug_preview = settings.DEBUG or getattr(
                settings,
                "EMAIL_BACKEND",
                "",
            ) != "django.core.mail.backends.smtp.EmailBackend"

            if account is not None:
                raw = issue_magic_link(account)
                send_magic_link(account, raw)
                context = {}
                if show_debug_preview:
                    context["debug_verify_url"] = _debug_verify_url_for_request(request, raw)
                return render(request, "accounts/magic_link_sent.html", context)
            else:
                # Claimed-email flow: no ParentAccount yet
                raw = issue_magic_link_for_email(email)
                send_magic_link_for_claimed_email(email, raw)
                context = {}
                if show_debug_preview:
                    context["debug_verify_url"] = _debug_verify_url_for_request(request, raw)
                return render(request, "accounts/magic_link_sent.html", context)
    else:
        form = MagicLinkRequestForm()
    return render(request, "accounts/request_magic_link.html", {"form": form})


def verify_magic_link(request, token):
    """GET /accounts/verify/<token>/ — consume token, log in."""
    try:
        account = consume_magic_link(token)
    except ValueError:
        return render(
            request,
            "accounts/verify_error.html",
            {"status": "invalid"},
            status=400,
        )

    request.session[PARENT_ACCOUNT_SESSION_KEY] = account.pk
    return redirect("registrations:parent-portal")


@require_POST
def logout_view(request):
    """POST /accounts/logout/ — clear session."""
    try:
        del request.session[PARENT_ACCOUNT_SESSION_KEY]
    except KeyError:
        pass
    request.session.flush()
    return redirect("registrations:start-registration")

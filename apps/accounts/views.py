"""Views for magic-link auth flow."""

from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.forms import MagicLinkRequestForm
from apps.accounts.models import ParentAccount
from apps.accounts.services import consume_magic_link, issue_magic_link, send_magic_link
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY


def request_magic_link(request):
    """POST /accounts/request-magic-link/ — issue and send a magic link."""
    if request.method == "POST":
        form = MagicLinkRequestForm(request.POST)
        if form.is_valid():
            account = ParentAccount.objects.get(email=form.cleaned_data["email"])
            raw = issue_magic_link(account)
            send_magic_link(account, raw)
            return render(request, "accounts/magic_link_sent.html")
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
    return redirect("/")


@require_POST
def logout_view(request):
    """POST /accounts/logout/ — clear session."""
    try:
        del request.session[PARENT_ACCOUNT_SESSION_KEY]
    except KeyError:
        pass
    request.session.flush()
    return redirect("/")

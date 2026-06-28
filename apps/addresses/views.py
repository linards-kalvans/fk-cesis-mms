"""JSON autocomplete endpoint for address search."""

from __future__ import annotations

from functools import wraps

from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect

from apps.accounts.models import ParentAccount
from apps.accounts.session import PARENT_ACCOUNT_SESSION_KEY
from apps.addresses.services import search_addresses


def _require_verified_parent(view):
    """Allow only verified parent sessions (mirrors registrations views)."""

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        account_id = request.session.get(PARENT_ACCOUNT_SESSION_KEY)
        if not account_id or not ParentAccount.objects.filter(pk=account_id).exists():
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return HttpResponse(status=403)
            return redirect("registrations:start-registration")
        return view(request, *args, **kwargs)

    return _wrapped


@_require_verified_parent
def autocomplete(request):
    """Return address suggestions for the authenticated user."""
    query = request.GET.get("q", "")
    group_id = request.GET.get("group")
    parsed_group_id: int | None = None
    if group_id is not None:
        try:
            parsed_group_id = int(group_id)
        except ValueError:
            parsed_group_id = None
    results = search_addresses(query, group_id=parsed_group_id)
    return JsonResponse({"results": results})

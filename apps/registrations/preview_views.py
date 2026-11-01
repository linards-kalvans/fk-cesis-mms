"""Verified-parent access to a shared blank template; no PDF download route."""

from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from apps.agreements import template_preview
from apps.registrations.views import _current_parent_account


def _require_parent(request: HttpRequest) -> None:
    account = _current_parent_account(request)
    if account is None or not account.is_active:
        raise Http404


@never_cache
@require_GET
def agreement_template_preview(request: HttpRequest) -> HttpResponse:
    _require_parent(request)
    preview = template_preview.get_preview()
    if preview is None and not template_preview.preview_failed():
        template_preview.enqueue_template_preview()
        preview = template_preview.get_preview()
    if preview is not None:
        return JsonResponse({"pages": [
            reverse("registrations:agreement-template-page", args=[preview["version"], number])
            for number in range(1, len(preview["pages"]) + 1)
        ]})
    if template_preview.preview_failed():
        return JsonResponse({"message": "Līguma priekšskatījums pašlaik nav pieejams. Lūdzu, mēģiniet vēlāk."}, status=503)
    return JsonResponse({"message": "Līguma priekšskatījums tiek sagatavots…"}, status=202)


@never_cache
@require_GET
def agreement_template_page(request: HttpRequest, version: str, page: int) -> HttpResponse:
    _require_parent(request)
    preview = template_preview.get_preview()
    if preview is None or version != preview["version"] or not 1 <= page <= len(preview["pages"]):
        raise Http404
    response = HttpResponse(preview["pages"][page - 1], content_type="image/png")
    response["X-Content-Type-Options"] = "nosniff"
    return response

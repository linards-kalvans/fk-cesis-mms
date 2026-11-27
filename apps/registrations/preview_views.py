"""Verified-parent access to a shared blank template; no PDF download route."""

from urllib.parse import urlencode

from django.core.exceptions import ImproperlyConfigured
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


def _requested_identity(request: HttpRequest) -> tuple[str, str, str]:
    """Resolve the request identity without letting the caller override config.

    The signing path is the parent's choice. The backend and template version
    are deployment configuration: a query value may only *assert* the current
    identity, never replace it.
    """
    backend = template_preview.configured_backend()
    asserted_backend = request.GET.get("backend")
    if asserted_backend is not None and asserted_backend != backend:
        raise ValueError("backend_mismatch")
    signing_path = request.GET.get("signing_path")
    if signing_path is None:
        signing_path = "electronic"
    template_version = request.GET.get("template_version")
    version = template_preview.validate_identity(
        backend, signing_path, template_version
    )
    return backend, signing_path, version


def _page_query(
    backend: str, signing_path: str, template_version: str
) -> str:
    """Identity query carried by raster URLs.

    Local pages always carry backend+path+version; legacy pages keep the
    historic no-query URL for the default electronic path and never leak the
    provider name.
    """
    if backend == template_preview.LOCAL_BACKEND:
        return "?" + urlencode(
            {
                "backend": backend,
                "signing_path": signing_path,
                "template_version": template_version,
            }
        )
    if signing_path != "electronic":
        return "?" + urlencode({"signing_path": signing_path})
    return ""


@never_cache
@require_GET
def agreement_template_preview(request: HttpRequest) -> HttpResponse:
    _require_parent(request)
    try:
        backend, signing_path, template_version = _requested_identity(request)
    except (ValueError, ImproperlyConfigured):
        return JsonResponse(
            {"message": "Līguma priekšskatījuma identitāte nav derīga."},
            status=400,
        )
    preview = template_preview.get_preview(
        backend=backend,
        signing_path=signing_path,
        template_version=template_version,
    )
    if preview is None and not template_preview.preview_failed(
        backend=backend,
        signing_path=signing_path,
        template_version=template_version,
    ):
        template_preview.enqueue_template_preview(
            backend=backend,
            signing_path=signing_path,
            template_version=template_version,
        )
        preview = template_preview.get_preview(
            backend=backend,
            signing_path=signing_path,
            template_version=template_version,
        )
    if preview is not None:
        query = _page_query(backend, signing_path, template_version)
        pages = [
            reverse(
                "registrations:agreement-template-page",
                args=[preview["version"], number],
            )
            + query
            for number in range(1, len(preview["pages"]) + 1)
        ]
        payload: dict[str, object] = {"pages": pages}
        if backend == template_preview.LOCAL_BACKEND:
            payload.update(
                {
                    "backend": backend,
                    "signing_path": signing_path,
                    "template_version": template_version,
                    "version": preview["version"],
                }
            )
        return JsonResponse(payload)
    if template_preview.preview_failed(
        backend=backend,
        signing_path=signing_path,
        template_version=template_version,
    ):
        return JsonResponse(
            {
                "message": (
                    "Līguma priekšskatījums pašlaik nav pieejams. "
                    "Lūdzu, mēģiniet vēlāk."
                )
            },
            status=503,
        )
    return JsonResponse(
        {"message": "Līguma priekšskatījums tiek sagatavots…"}, status=202
    )


@never_cache
@require_GET
def agreement_template_page(
    request: HttpRequest, version: str, page: int
) -> HttpResponse:
    _require_parent(request)
    try:
        backend, signing_path, template_version = _requested_identity(request)
    except (ValueError, ImproperlyConfigured):
        return HttpResponse(status=400)
    preview = template_preview.get_preview(
        backend=backend,
        signing_path=signing_path,
        template_version=template_version,
    )
    if (
        preview is None
        or version != preview["version"]
        or not 1 <= page <= len(preview["pages"])
    ):
        raise Http404
    response = HttpResponse(
        preview["pages"][page - 1], content_type="image/png"
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response

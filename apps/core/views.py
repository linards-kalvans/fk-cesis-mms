"""Cross-cutting views for apps.core."""

from __future__ import annotations

from django.db import DatabaseError, connection
from django.http import HttpRequest, JsonResponse


def healthz(_request: HttpRequest) -> JsonResponse:
    """Liveness + DB-reachability probe.

    Returns 200 with `{"status": "ok"}` when the DB answers `SELECT 1`,
    otherwise 503. Used by the Docker healthcheck and Caddy's `health_uri`.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError as exc:
        return JsonResponse(
            {"status": "error", "detail": str(exc)},
            status=503,
        )
    return JsonResponse({"status": "ok"})

"""Presentation queries for correction-request correspondence.

The sole Hub reader of :class:`ApplicationCorrectionMessage`. Queue rows only
need aggregates (a successful-send count and the latest recorded outcome), so
``correction_summaries`` fetches them for a whole page in two bounded queries
instead of reading history per row. Full subject/body/note content is fetched
only by the dedicated staff GET endpoint.

``awaiting_parent`` is deliberately **not** derived here: it is the
application's current ``fix_requested`` state, which the row/detail assembly
reads independently from the message history.
"""

from __future__ import annotations

from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, Max, OuterRef, Subquery

from apps.registrations.models import ApplicationCorrectionMessage

HISTORY_PAGE_SIZE = 20


def empty_summary() -> dict[str, object]:
    """The truthful "no tracked history" shape.

    There has been no backfill: an application with no rows may still have had
    correction emails before this feature shipped. ``has_history=False`` means
    exactly "nothing tracked", never "nothing was ever sent".
    """
    return {
        "sent_count": 0,
        "latest_status": "",
        "latest_created_at": None,
        "latest_sent_at": None,
        "has_history": False,
    }


def correction_summaries(
    application_ids: list[int],
) -> dict[int, dict[str, object]]:
    """Summaries for one page's applications in two bounded queries.

    ``sent_count`` counts only ``sent`` rows. ``latest_sent_at`` is the most
    recent successful send across all ``sent`` rows, independent of the latest
    attempt, so a later failure never erases the last confirmed acceptance.
    A failed or pending latest attempt is reported through ``latest_status``
    and is never counted as a send. The summary intentionally excludes
    ``subject``, ``body`` and ``review_message`` so a queue page cannot leak
    correspondence.
    """
    ids = [int(pk) for pk in application_ids]
    if not ids:
        return {}

    summaries = {pk: empty_summary() for pk in ids}

    sent_counts = (
        ApplicationCorrectionMessage.objects.filter(
            application_id__in=ids,
            status=ApplicationCorrectionMessage.Status.SENT,
        )
        .values("application_id")
        .annotate(
            sent_count=Count("pk"),
            latest_sent_at=Max("sent_at"),
        )
    )
    for row in sent_counts:
        summary = summaries[int(row["application_id"])]
        summary["sent_count"] = int(row["sent_count"])
        summary["latest_sent_at"] = row["latest_sent_at"]

    latest_id = (
        ApplicationCorrectionMessage.objects.filter(
            application_id=OuterRef("application_id")
        )
        .order_by("-created_at", "-pk")
        .values("pk")[:1]
    )
    latest_rows = ApplicationCorrectionMessage.objects.filter(
        application_id__in=ids,
        pk=Subquery(latest_id),
    ).values("application_id", "status", "created_at")
    for row in latest_rows:
        summary = summaries[int(row["application_id"])]
        summary["latest_status"] = str(row["status"])
        summary["latest_created_at"] = row["created_at"]
        summary["has_history"] = True

    return summaries


def _normalize_page(raw: Any, paginator: Paginator) -> int:
    """Invalid or out-of-range pages fall back to the first page."""
    try:
        return int(paginator.validate_number(raw))
    except (TypeError, ValueError, PageNotAnInteger, EmptyPage):
        return 1


def correction_history_page(
    application, raw_page: Any
) -> tuple[Any, dict[str, object]]:
    """One oldest-first history page plus the application's summary.

    The summary uses the same presenter as the queue, so a detail page cannot
    disagree with its list row. Ordering is the model's deterministic
    ``(created_at, pk)``.
    """
    queryset = ApplicationCorrectionMessage.objects.filter(
        application=application
    ).select_related("actor")
    paginator = Paginator(queryset, HISTORY_PAGE_SIZE)
    page_obj = paginator.page(_normalize_page(raw_page, paginator))
    summary = correction_summaries([application.pk]).get(
        application.pk, empty_summary()
    )
    return page_obj, summary

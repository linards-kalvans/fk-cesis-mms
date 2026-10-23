"""Queryset + row assembly for the Admin Hub list pages.

Kept out of views.py so the row shape is unit-testable and the views stay
thin. Row counts here are club-scale (hundreds), so the per-row pipeline
lookup is deliberate: correctness over a premature join. Pagination bounds
that per-row cost to one page's worth of applications.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Q
from django.utils import timezone

from apps.admin_hub import correction_messages
from apps.admin_hub.pipeline import (
    PipelineStep,
    build_pipeline,
    current_step,
    load_pipeline_objects,
    pipeline_progress,
)
from apps.agreements.models import Agreement
from apps.documents.models import Document
from apps.admin_hub.badges import (
    APPLICATION_STATUS_BADGE_CLASSES,
    FALLBACK_BADGE_CLASS,
)
from apps.registrations.models import RegistrationApplication
from apps.registrations.presentation import active_documents_by_kind

AGING_THRESHOLD = datetime.timedelta(days=3)
PAGE_SIZE = 25
# Long enough for a full name plus a few tokens, short enough that a pasted
# document cannot turn into a 10 kB LIKE pattern.
MAX_SEARCH_LENGTH = 200

QUEUE_TABS: dict[str, str] = {
    "jaizskata": "Jāizskata",
    "jalabo": "Jālabo",
    "procesa": "Procesā",
    "parakstiti": "Parakstīti",
    "noraiditi": "Noraidīti",
    "visi": "Visi",
}
DEFAULT_TAB = "jaizskata"

# Status -> badge class. Defined once in apps/admin_hub/badges.py and aliased
# here for the row assembly below; the cockpit and agreement pages read the
# same module, so a rejected application can never show a green pill on one
# page and a red one on another.
STATUS_BADGE_CLASSES = APPLICATION_STATUS_BADGE_CLASSES

# kind -> (dot letter, tooltip). Derived from the Latvian labels, not from the
# internal enum value: guardian_identity/member_identity/member_portrait all
# collide on their first letter.
DOC_KIND_BADGES: dict[str, tuple[str, str]] = {
    str(Document.Kind.GUARDIAN_IDENTITY): ("V", "Vecāka ID"),
    str(Document.Kind.MEMBER_IDENTITY): ("B", "Bērna ID"),
    str(Document.Kind.MEMBER_PORTRAIT): ("P", "Portrets"),
}


@dataclass(frozen=True)
class QueueRow:
    application: RegistrationApplication
    steps: list[PipelineStep]
    done: int
    total: int
    next_name: str
    documents: list[dict]
    is_aging: bool
    status_badge_class: str
    correction_summary: dict[str, object]
    awaiting_parent: bool


def normalize_tab(raw: str | None) -> str:
    """Never trust the query string: an unknown tab falls back to the default."""
    return raw if raw in QUEUE_TABS else DEFAULT_TAB


def normalize_search(raw: str | None) -> str:
    """Never trust the query string: strip, collapse internal whitespace and
    cap the length before it reaches the database.

    Returns ``""`` (no filtering) for a missing or blank query. Applied in
    the view AND at the query boundary, so a direct caller such as
    ``_tab_queryset(tab, q=...)`` gets exactly the same matching as the page.

    The cap is stripped afterwards: truncating at 200 can land on a separator,
    and a trailing space would make an already-normalized value change shape on
    a second call. Stripping the capped result keeps this idempotent.
    """
    if not raw:
        return ""
    return " ".join(raw.split())[:MAX_SEARCH_LENGTH].strip()


def _search_filter(q: str) -> Q:
    """AND the tokens, OR the fields for each token.

    Child and guardian names are separate columns (``Guardian`` has
    ``first_name``/``family_name``, no ``full_name`` column), so a token may
    match either side independently. ``guardian`` is nullable; a token that
    only matches the child still keeps the row because the OR never requires
    the guardian join to produce a value.
    """
    predicate = Q()
    for token in q.split():
        predicate &= (
            Q(member_full_name__icontains=token)
            | Q(guardian__first_name__icontains=token)
            | Q(guardian__family_name__icontains=token)
        )
    return predicate


def _tab_queryset(tab: str, *, q: str = ""):
    """One tab's applications, optionally restricted to a normalized search.

    Status predicates, ordering and the single signed-agreement subquery are
    unchanged: the search predicate is applied to the shared base queryset
    before the tab branch, so every tab — including the Procesā/Parakstīti
    complement — sees exactly the same search scope, and the counts therefore
    agree with the visible list.
    """
    status = RegistrationApplication.Status
    base = RegistrationApplication.objects.select_related(
        "guardian",
        "parent_account",
        "approved_member",
        "approved_member__training_group",
    )
    search = normalize_search(q)
    if search:
        base = base.filter(_search_filter(search))
    if tab == "jaizskata":
        return base.filter(status=status.SUBMITTED).order_by("-submitted_at")
    if tab == "jalabo":
        return base.filter(status=status.FIX_REQUESTED).order_by("-updated_at")
    if tab in ("procesa", "parakstiti"):
        # One subquery, used both ways, so the two tabs are exact complements
        # by construction. A two-field exclude() would NOT do this: Django
        # compiles multi-valued exclude() into independent EXISTS subqueries,
        # so "is_current" and "signed" would not have to hold on the same row.
        signed_members = Agreement.objects.filter(
            is_current=True, state=Agreement.State.SIGNED
        ).values("member_id")
        approved = base.filter(status=status.APPROVED)
        if tab == "parakstiti":
            return approved.filter(approved_member__in=signed_members).order_by("-reviewed_at")
        return approved.exclude(approved_member__in=signed_members).order_by("-reviewed_at")
    if tab == "noraiditi":
        return base.filter(status=status.REJECTED).order_by("-reviewed_at")
    return base.order_by("-created_at")


def _document_badges(application: RegistrationApplication) -> list[dict]:
    docs = active_documents_by_kind(application)
    return [
        {"letter": letter, "title": title, "present": docs.get(kind) is not None}
        for kind, (letter, title) in DOC_KIND_BADGES.items()
    ]


def _build_row(
    application: RegistrationApplication,
    now: datetime.datetime,
    *,
    correction_summary: dict[str, object] | None = None,
) -> QueueRow:
    steps = build_pipeline(load_pipeline_objects(application))
    done, total = pipeline_progress(steps)
    step = current_step(steps)
    is_aging = bool(
        application.status == RegistrationApplication.Status.SUBMITTED
        and application.submitted_at
        and now - application.submitted_at > AGING_THRESHOLD
    )
    return QueueRow(
        application=application,
        steps=steps,
        done=done,
        total=total,
        next_name=step.name if step else "",
        documents=_document_badges(application),
        is_aging=is_aging,
        status_badge_class=STATUS_BADGE_CLASSES.get(str(application.status), FALLBACK_BADGE_CLASS),
        correction_summary=correction_summary
        or correction_messages.empty_summary(),
        # Deliberately independent of history: an application can await a
        # parent answer with no tracked email (pre-tracking), and a failed
        # send still leaves it awaiting.
        awaiting_parent=(
            application.status == RegistrationApplication.Status.FIX_REQUESTED
        ),
    )


def normalize_page(raw: Any, paginator: Paginator) -> int:
    """Never trust the query string: an invalid or out-of-range page falls
    back to page 1, the same way normalize_tab handles a bad tab."""
    try:
        return int(paginator.validate_number(raw))
    except (TypeError, ValueError, PageNotAnInteger, EmptyPage):
        return 1


def queue_page(
    tab: str, page_number: Any, *, q: str = ""
) -> tuple[list[QueueRow], Any]:
    """Rows for one page plus the Paginator page object. Rows are built only
    for the current page, which is what bounds the per-row query cost.

    ``q`` narrows the tab before pagination, so page size and the
    invalid-page fallback in ``normalize_page`` apply to the filtered set.
    """
    now = timezone.now()
    paginator = Paginator(_tab_queryset(tab, q=q), PAGE_SIZE)
    number = normalize_page(page_number, paginator)
    page_obj = paginator.page(number)
    applications = list(page_obj.object_list)
    # One bounded summary lookup for the whole page. Keeping this out of
    # ``_build_row`` is what prevents history becoming an N+1 query.
    summaries = correction_messages.correction_summaries(
        [application.pk for application in applications]
    )
    rows = [
        _build_row(
            application,
            now,
            correction_summary=summaries.get(application.pk),
        )
        for application in applications
    ]
    return rows, page_obj


def tab_counts(*, q: str = "") -> dict[str, int]:
    """Per-tab totals for the same normalized search the list uses."""
    return {tab: _tab_queryset(tab, q=q).count() for tab in QUEUE_TABS}

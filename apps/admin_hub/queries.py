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
from django.utils import timezone

from apps.admin_hub.pipeline import (
    PipelineStep,
    build_pipeline,
    current_step,
    load_pipeline_objects,
    pipeline_progress,
)
from apps.agreements.models import Agreement
from apps.documents.models import Document
from apps.registrations.models import RegistrationApplication
from apps.registrations.presentation import active_documents_by_kind

AGING_THRESHOLD = datetime.timedelta(days=3)
PAGE_SIZE = 25

QUEUE_TABS: dict[str, str] = {
    "jaizskata": "Jāizskata",
    "jalabo": "Jālabo",
    "procesa": "Procesā",
    "parakstiti": "Parakstīti",
    "noraiditi": "Noraidīti",
    "visi": "Visi",
}
DEFAULT_TAB = "jaizskata"

# Status -> badge class. The mock-up varies the pill colour per status; a
# hardcoded class renders a rejected application in "submitted" green.
STATUS_BADGE_CLASSES: dict[str, str] = {
    str(RegistrationApplication.Status.DRAFT): "badge--draft",
    str(RegistrationApplication.Status.SUBMITTED): "badge--submitted",
    str(RegistrationApplication.Status.FIX_REQUESTED): "badge--fix",
    str(RegistrationApplication.Status.APPROVED): "badge--approved",
    str(RegistrationApplication.Status.REJECTED): "badge--rejected",
}

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


def normalize_tab(raw: str | None) -> str:
    """Never trust the query string: an unknown tab falls back to the default."""
    return raw if raw in QUEUE_TABS else DEFAULT_TAB


def _tab_queryset(tab: str):
    status = RegistrationApplication.Status
    base = RegistrationApplication.objects.select_related(
        "guardian",
        "parent_account",
        "approved_member",
        "approved_member__training_group",
    )
    if tab == "jaizskata":
        return base.filter(status=status.SUBMITTED).order_by("-submitted_at")
    if tab == "jalabo":
        return base.filter(status=status.FIX_REQUESTED).order_by("-updated_at")
    if tab == "procesa":
        return base.filter(status=status.APPROVED).exclude(
            approved_member__agreements__is_current=True,
            approved_member__agreements__state=Agreement.State.SIGNED,
        ).order_by("-reviewed_at")
    if tab == "parakstiti":
        return base.filter(
            status=status.APPROVED,
            approved_member__agreements__is_current=True,
            approved_member__agreements__state=Agreement.State.SIGNED,
        ).order_by("-reviewed_at")
    if tab == "noraiditi":
        return base.filter(status=status.REJECTED).order_by("-reviewed_at")
    return base.order_by("-created_at")


def _document_badges(application: RegistrationApplication) -> list[dict]:
    docs = active_documents_by_kind(application)
    return [
        {"letter": letter, "title": title, "present": docs.get(kind) is not None}
        for kind, (letter, title) in DOC_KIND_BADGES.items()
    ]


def _build_row(application: RegistrationApplication, now: datetime.datetime) -> QueueRow:
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
        status_badge_class=STATUS_BADGE_CLASSES.get(application.status, "badge--neutral"),
    )


def normalize_page(raw: Any, paginator: Paginator) -> int:
    """Never trust the query string: an invalid or out-of-range page falls
    back to page 1, the same way normalize_tab handles a bad tab."""
    try:
        return int(paginator.validate_number(raw))
    except (TypeError, ValueError, PageNotAnInteger, EmptyPage):
        return 1


def queue_page(tab: str, page_number: Any) -> tuple[list[QueueRow], Any]:
    """Rows for one page plus the Paginator page object. Rows are built only
    for the current page, which is what bounds the per-row query cost."""
    now = timezone.now()
    paginator = Paginator(_tab_queryset(tab), PAGE_SIZE)
    number = normalize_page(page_number, paginator)
    page_obj = paginator.page(number)
    rows = [_build_row(application, now) for application in page_obj.object_list]
    return rows, page_obj


def tab_counts() -> dict[str, int]:
    return {tab: _tab_queryset(tab).count() for tab in QUEUE_TABS}

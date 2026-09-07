"""Queryset + row assembly for the Admin Hub list pages.

Kept out of views.py so the row shape is unit-testable and the views stay
thin. Row counts here are club-scale (hundreds), so the per-row pipeline
lookup is deliberate: correctness over a premature join.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.utils import timezone

from apps.admin_hub.pipeline import (
    PipelineStep,
    build_pipeline,
    current_step,
    load_pipeline_objects,
    pipeline_progress,
)
from apps.registrations.models import RegistrationApplication
from apps.registrations.presentation import active_documents_by_kind

AGING_THRESHOLD = datetime.timedelta(days=3)

QUEUE_TABS: dict[str, str] = {
    "jaizskata": "Jāizskata",
    "jalabo": "Jālabo",
    "procesa": "Procesā",
    "pabeigti": "Pabeigti",
    "noraiditi": "Noraidīti",
    "visi": "Visi",
}
DEFAULT_TAB = "jaizskata"


@dataclass(frozen=True)
class QueueRow:
    application: RegistrationApplication
    steps: list[PipelineStep]
    done: int
    total: int
    next_name: str
    documents: dict[str, object]
    is_aging: bool


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
        return base.filter(
            status=status.APPROVED, approved_member__isnull=False
        ).order_by("-reviewed_at")
    if tab == "pabeigti":
        return base.filter(status=status.APPROVED).order_by("-reviewed_at")
    if tab == "noraiditi":
        return base.filter(status=status.REJECTED).order_by("-reviewed_at")
    return base.order_by("-created_at")


def queue_rows(tab: str) -> list[QueueRow]:
    now = timezone.now()
    rows: list[QueueRow] = []
    for application in _tab_queryset(tab):
        steps = build_pipeline(load_pipeline_objects(application))
        done, total = pipeline_progress(steps)
        step = current_step(steps)
        is_aging = bool(
            application.status == RegistrationApplication.Status.SUBMITTED
            and application.submitted_at
            and now - application.submitted_at > AGING_THRESHOLD
        )
        rows.append(
            QueueRow(
                application=application,
                steps=steps,
                done=done,
                total=total,
                next_name=step.name if step else "",
                documents=active_documents_by_kind(application),
                is_aging=is_aging,
            )
        )
    return rows


def tab_counts() -> dict[str, int]:
    return {tab: _tab_queryset(tab).count() for tab in QUEUE_TABS}

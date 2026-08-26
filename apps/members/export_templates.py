"""P17 — configurable member export service.

Builds the filtered member queryset for a :class:`MemberExportTemplate` and
renders it to an in-memory CSV/XLSX attachment. The export never persists —
the response is returned directly for the admin run endpoint to return.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Prefetch, QuerySet
from django.http import HttpResponse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.core.export import csv_response, xlsx_response
from apps.members.exports import COLUMN_REGISTRY, SENSITIVE_KEYS
from apps.members.models import Member, MemberExportTemplate


@dataclass(frozen=True)
class RenderedMemberExport:
    """Result of rendering a member export — direct download payload."""

    response: HttpResponse
    row_count: int
    sensitive: bool


def build_template_member_queryset(template: MemberExportTemplate) -> QuerySet:
    """Build the filtered Member queryset for a template.

    Selects/prefetches the relations the readers need (guardian, parent
    account, training group, current agreements only). When a filter is set
    the corresponding EXISTS subquery narrows by ``is_current=True`` (no
    historical agreements). Empty filter sets leave the queryset unrestricted.
    """
    qs = Member.objects.all()
    qs = qs.select_related(
        "guardian", "guardian__parent_account", "training_group"
    )

    agreement_prefetch = Prefetch(
        "agreements",
        queryset=Agreement.objects.filter(is_current=True).only(
            "id", "member_id", "state", "signed_at"
        ),
        to_attr="_current_export_agreements",
    )
    qs = qs.prefetch_related(agreement_prefetch)

    states = list(template.agreement_status_filters or [])
    if states:
        # OR semantics: ANY state matches. Membership is restricted to the
        # current agreement's state. Member must appear once even if multiple
        # matching agreements exist (which can't happen given is_current=True,
        # but we still distinct defensively).
        qs = qs.filter(
            agreements__is_current=True,
            agreements__state__in=states,
        )

    group_ids = list(template.training_groups.values_list("pk", flat=True))
    if group_ids:
        qs = qs.filter(training_group_id__in=group_ids)

    return qs.distinct()


def render_member_export(
    template: MemberExportTemplate, fmt: str
) -> RenderedMemberExport:
    """Render the export in ``csv`` or ``xlsx`` form.

    Output: rendered rows + a final HttpResponse attachment. The template's
    column keys are read in stored order; ``Member`` rows are read via the
    pure readers in ``apps.members.exports.COLUMN_REGISTRY`` and passed raw
    to the core writers (which apply the format guard exactly once per cell).
    """
    if fmt not in {"csv", "xlsx"}:
        raise ValueError("invalid format")

    column_keys: list[str] = list(template.column_keys or [])
    for key in column_keys:
        if key not in COLUMN_REGISTRY:
            raise ValueError("invalid column key")
    qs = build_template_member_queryset(template)

    rows: list[list[Any]] = []
    for member in qs:
        rows.append([COLUMN_REGISTRY[key].reader(member) for key in column_keys])

    headers = [COLUMN_REGISTRY[key].label for key in column_keys]
    sensitive = any(key in SENSITIVE_KEYS for key in column_keys)

    ts = timezone.localtime().strftime("%Y%m%d-%H%M")
    ext = "xlsx" if fmt == "xlsx" else "csv"
    filename = f"member-export-{template.pk}-{ts}.{ext}"

    if fmt == "xlsx":
        response = xlsx_response(filename=filename, columns=headers, rows=rows)
    else:
        response = csv_response(filename=filename, columns=headers, rows=rows)

    return RenderedMemberExport(
        response=response, row_count=len(rows), sensitive=sensitive
    )

"""Admin Hub views. Every page is staff-only and renders derived state; all
mutations POST to the existing Django admin action endpoints."""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.admin_hub import queries


@staff_member_required
def queue_view(request):
    tab = queries.normalize_tab(request.GET.get("tab"))
    return render(
        request,
        "admin_hub/queue.html",
        {
            "tab": tab,
            "tabs": queries.QUEUE_TABS,
            "tab_counts": queries.tab_counts(),
            "rows": queries.queue_rows(tab),
        },
    )

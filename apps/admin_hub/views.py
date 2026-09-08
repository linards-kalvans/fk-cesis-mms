"""Admin Hub views. Every page is staff-only and renders derived state; all
mutations POST to the existing Django admin action endpoints."""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.admin_hub import queries


@staff_member_required
def queue_view(request):
    tab = queries.normalize_tab(request.GET.get("tab"))
    rows, page_obj = queries.queue_page(tab, request.GET.get("page"))
    return render(
        request,
        "admin_hub/queue.html",
        {
            "hub_section": "queue",
            "tab": tab,
            "tabs": queries.QUEUE_TABS,
            "tab_counts": queries.tab_counts(),
            "rows": rows,
            "page_obj": page_obj,
        },
    )


@staff_member_required
def cockpit_view(request, pk: int):
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.fields import build_field_groups, checkable_keys
    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.documents.models import Document
    from apps.members.models import TrainingGroup
    from apps.registrations.admin_panels import build_doc_panel
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    groups = build_field_groups(application)
    keys = checkable_keys(groups)
    default_checked = [
        field.key
        for group in groups
        for field in group.fields
        if field.default_checked
    ]

    return render(
        request,
        "admin_hub/cockpit.html",
        {
            "hub_section": "queue",
            "application": application,
            "objects": objects,
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            "groups": groups,
            "checkable_total": len(keys),
            "default_checked_count": len(default_checked),
            # Zipped in the view: Django templates cannot walk two parallel
            # lists together, and the label belongs beside its panel.
            "viewer_tabs": list(
                zip(
                    ["Bērna ID", "Vecāka ID", "Portrets"],
                    [
                        build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY)),
                        build_doc_panel(application, str(Document.Kind.GUARDIAN_IDENTITY)),
                        build_doc_panel(application, str(Document.Kind.MEMBER_PORTRAIT)),
                    ],
                )
            ),
            "active_training_groups": list(
                TrainingGroup.objects.filter(is_active=True).order_by("name")
            ),
        },
    )


@staff_member_required
def agreement_view(request, pk: int):
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.admin_hub.timeline import build_agreement_timeline
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    if objects.agreement is None:
        raise Http404("Šim pieteikumam vēl nav līguma.")

    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    agreement = objects.agreement

    return render(
        request,
        "admin_hub/agreement.html",
        {
            "hub_section": "queue",
            "application": application,
            "member": objects.member,
            "agreement": agreement,
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            "has_signed_artifact": bool(agreement.signed_artifact),
            # mark_agreement_signed materialises the BillingRecord from these
            # two values, so step 5 cannot complete before step 6.
            "has_billing_plan": bool(
                agreement.billing_plan_id and agreement.first_billing_month
            ),
            "lifecycle_events": build_agreement_timeline(agreement)[:20],
        },
    )


@staff_member_required
def billing_view(request, pk: int):
    """Minimal stub for the billing-plan step (Task 7 replaces this)."""
    return render(request, "admin_hub/billing.html", {})

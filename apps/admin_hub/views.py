"""Admin Hub views. Every page is staff-only and renders derived state; all
mutations POST to the existing Django admin action endpoints."""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.admin_hub import queries
from apps.admin_hub.badges import agreement_badge_class, application_badge_class


def _billing_change_route(application, record) -> tuple[str, str]:
    """Where the step-6 plan form should POST, and why it cannot.

    Two endpoints own the plan, at different points in the pipeline, and the
    Hub previously only ever used the first:

    * Before signing there is no BillingRecord yet, so the plan is an
      *intent* on the agreement — ``set_billing_setup``, which deliberately
      refuses a signed agreement ("billing is already realised against the
      locked record").
    * After signing the record exists and IS the billing, so changing it
      means reassigning that record — ``billing_billingrecord_reassign``,
      which takes the same ``billing_plan`` + ``first_billing_month`` fields.

    Posting ``set_billing_setup`` after signing therefore surfaced the raw
    English "cannot change billing setup after signing" in a Latvian UI, for
    a change the domain in fact supports. Returns ``(url, blocked_reason)``
    with exactly one populated: reassignment has hard guards (draft only, no
    invoice pushed to Invoice Ninja, none e-mailed to a parent), and where
    they bite the reviewer is told which one rather than being allowed to
    submit into an error.
    """
    from django.urls import reverse

    from apps.billing.models import BillingRecord

    if record is None:
        return (
            reverse(
                "admin:registrations_registrationapplication_review-action",
                args=[application.pk],
            ),
            "",
        )
    if str(record.status) != str(BillingRecord.Status.DRAFT):
        return "", (
            "Maksājumu ieraksts jau ir apstiprināts. Lai mainītu plānu, "
            "vispirms atsauciet ierakstu pilnajā administrācijā."
        )
    if record.invoices.exclude(external_invoice_id="").exists():
        return "", (
            "Rēķini jau ir izrakstīti Invoice Ninja — plānu vairs nevar "
            "mainīt, neatsaucot tos."
        )
    if record.invoices.filter(sent_at__isnull=False).exists():
        return "", (
            "Rēķini jau ir nosūtīti vecākam — plānu vairs nevar mainīt, "
            "neatsaucot tos."
        )
    return (
        reverse("admin:billing_billingrecord_reassign", args=[record.pk]),
        "",
    )


def _step_urls(application, objects) -> dict[str, str]:
    """Which Hub page owns each pipeline step.

    The step rail is the only place the eight steps appear together, so it is
    also the natural way to move between them — an earlier ruling made it a
    non-clickable status display on the grounds that each page's own buttons
    would navigate, and those buttons were never built, leaving steps 3-8
    reachable only by typing a URL. A step with no entry here renders as plain
    text, which is what an unreachable step should look like."""
    from django.urls import reverse

    cockpit = reverse("admin_hub:cockpit", args=[application.pk])
    urls = {"verify": cockpit, "approve": cockpit}
    if objects.agreement is not None:
        agreement = reverse("admin_hub:agreement", args=[application.pk])
        billing = reverse("admin_hub:billing", args=[application.pk])
        for key in ("agreement", "handover", "signed"):
            urls[key] = agreement
        for key in ("plan", "invoices", "next_season"):
            urls[key] = billing
    return urls


def _step_is_done(steps, key: str) -> bool:
    """Whether one pipeline step is complete, by key.

    Pages read a step's state from here rather than recomputing the rule that
    decided it — two copies of one rule is what let the overdue flag and the
    tab filter disagree earlier on this branch."""
    from apps.admin_hub.pipeline import DONE

    return any(step.key == key and step.state == DONE for step in steps)


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
    from django.urls import reverse

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
            "status_badge_class": application_badge_class(application.status),
            "step_urls": _step_urls(application, objects),
            # approve_application itself refuses anything but a submitted
            # application, so the button must not offer it otherwise.
            "can_approve": (
                str(application.status)
                == str(RegistrationApplication.Status.SUBMITTED)
            ),
            # The template must not compare against a domain enum literal.
            "is_approved": (
                str(application.status)
                == str(RegistrationApplication.Status.APPROVED)
            ),
            "agreement_url": (
                reverse("admin_hub:agreement", args=[application.pk])
                if objects.agreement is not None
                else ""
            ),
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
            "state_badge_class": agreement_badge_class(agreement.state),
            "step_urls": _step_urls(application, objects),
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            # DocuSeal writes external_id asynchronously, so it is blank
            # whenever the worker is behind or the submission failed. Without
            # it the download view redirects instead of serving a file.
            "agreement_document_ready": bool(agreement.external_id),
            "has_signed_artifact": bool(agreement.signed_artifact),
            # Read step 6's own state rather than recomputing its rule here.
            # mark_agreement_signed materialises the BillingRecord from the
            # plan + first month, so step 5 cannot complete before step 6 —
            # and pipeline.build_pipeline already decides when that holds.
            "has_billing_plan": _step_is_done(steps, "plan"),
            "lifecycle_events": build_agreement_timeline(agreement)[:20],
        },
    )


@staff_member_required
def billing_view(request, pk: int):
    import datetime
    from decimal import Decimal

    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.admin_hub import invoices as invoice_queries
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.billing.services import derive_installment_schedule
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    if objects.agreement is None:
        raise Http404("Šim pieteikumam vēl nav līguma.")

    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    agreement = objects.agreement
    record = objects.billing_record
    # Computed once: the guards behind it hit the invoice table.
    billing_change_url, billing_change_blocked_reason = _billing_change_route(
        application, record
    )

    # Preview the schedule from whatever is selected now, so the reviewer sees
    # the consequence before saving. Falls back to an empty list when there is
    # no plan yet - never to a guess.
    schedule: list[tuple[datetime.date, Decimal]] = []
    plan = agreement.billing_plan
    if plan is not None:
        total_amount = record.final_amount if record is not None else plan.annual_amount
        schedule = derive_installment_schedule(
            plan,
            total_amount,
            first_billing_month=agreement.first_billing_month,
        )

    return render(
        request,
        "admin_hub/billing.html",
        {
            "hub_section": "queue",
            "application": application,
            "member": objects.member,
            "agreement": agreement,
            "record": record,
            "step_urls": _step_urls(application, objects),
            # Which endpoint owns the plan right now - see _billing_change_route.
            "billing_change_url": billing_change_url,
            "billing_change_blocked_reason": billing_change_blocked_reason,
            # The template must not compare against a domain enum literal.
            "record_confirmed": (
                record is not None
                and str(record.status) == str(BillingRecord.Status.CONFIRMED)
            ),
            "invoices": objects.invoices,
            "payment_badge_classes": invoice_queries.PAYMENT_BADGE_CLASSES,
            "next_season_record": objects.next_season_record,
            "schedule": schedule,
            "steps": steps,
            "steps_done": done,
            "steps_total": total,
            "active_plans": list(
                MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
            ),
        },
    )


@staff_member_required
def invoices_view(request):
    from apps.admin_hub import invoices as invoice_queries

    tab = invoice_queries.normalize_invoice_tab(request.GET.get("tab"))
    queryset = invoice_queries.invoice_queryset(tab)
    # Totals come from the unpaged queryset on purpose: they report money owed,
    # so a figure describing only the current page would understate it.
    totals = invoice_queries.invoice_totals(queryset)
    rows, page_obj = invoice_queries.invoice_page(queryset, request.GET.get("page"))
    return render(
        request,
        "admin_hub/invoices.html",
        {
            "hub_section": "invoices",
            "tab": tab,
            "tabs": invoice_queries.INVOICE_TABS,
            "totals": totals,
            "rows": rows,
            "page_obj": page_obj,
            "payment_badge_classes": invoice_queries.PAYMENT_BADGE_CLASSES,
        },
    )

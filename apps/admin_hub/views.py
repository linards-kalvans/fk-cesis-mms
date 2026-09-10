"""Admin Hub views. Every page is staff-only and renders derived state; all
mutations POST to the existing Django admin action endpoints."""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from apps.admin_hub import queries
from apps.admin_hub.badges import agreement_badge_class, application_badge_class


def _billing_is_locked(agreement) -> bool:
    """Whether the plan has stopped being an intent on the agreement and
    become the BillingRecord's own data.

    The single definition of that boundary. ``set_billing_setup`` refuses
    these states, so both the agreement page (which offers the plan inline,
    because signing cannot happen without one) and the billing page's route
    decision must agree on where the line falls — a second copy of this
    three-state tuple is exactly how the overdue flag and its tab filter
    drifted apart earlier on this branch.
    """
    from apps.agreements.models import Agreement

    return agreement is not None and agreement.state in (
        Agreement.State.SIGNED,
        Agreement.State.SUPERSEDED,
        Agreement.State.DISCONTINUED,
    )


def _plan_preview(agreement, record):
    """The plan, first billing month and installment schedule to display.

    Once a BillingRecord exists it IS the billing, so a preview must reflect
    its own plan and month rather than the agreement's intent. Shared by the
    agreement page (step 5, where the plan must be set before signing can
    materialise the record) and the billing page (step 6) so the two cannot
    show different numbers for the same member.
    """
    import datetime
    from decimal import Decimal

    from apps.billing.services import derive_installment_schedule

    plan = record.plan if record is not None else agreement.billing_plan
    first_billing_month = (
        record.first_billing_month
        if record is not None
        else agreement.first_billing_month
    )
    schedule: list[tuple[datetime.date, Decimal]] = []
    # A blank month is NOT a preview-able state, even though
    # derive_installment_schedule will happily fall back to the plan's own
    # first_installment_month and the season start year. Signing refuses a
    # blank month (P15), so rendering a concrete grid of dates directly above
    # the warning that the month is still missing shows staff invented
    # deadlines for a transition that cannot happen.
    if plan is not None and first_billing_month:
        total_amount = (
            record.final_amount if record is not None else plan.annual_amount
        )
        schedule = derive_installment_schedule(
            plan,
            total_amount,
            first_billing_month=first_billing_month,
        )
    return plan, first_billing_month, schedule


def _billing_change_route(
    application, agreement, member, record, invoices, mismatched_record=None
) -> tuple[str, str, bool]:
    """Where the step-6 plan form should POST, why it cannot, and whether the
    Hub should instead offer the record-recreation remedy.

    Two endpoints own the plan, at different points in the pipeline:

    * Before signing there is no BillingRecord yet, so the plan is an
      *intent* on the agreement — ``set_billing_setup``, which deliberately
      refuses a signed/superseded/discontinued agreement ("billing is
      already realised against the locked record").
    * After signing the record exists and IS the billing, so changing it
      means reassigning that record — ``billing_billingrecord_reassign``,
      which takes the same ``billing_plan`` + ``first_billing_month`` fields.

    Which one applies depends on the *agreement's* state, never merely on
    whether a ``BillingRecord`` was matched — a signed agreement can have no
    matched record (season-matching desync in ``load_pipeline_objects``, now
    fixed going forward but not retroactively, or a record that is
    genuinely missing), and routing that case to ``set_billing_setup``
    surfaced the raw English "cannot change billing setup after signing" in
    a Latvian UI, for a change the domain in fact supports via a third
    route. Returns ``(url, blocked_reason, offer_recreate)``. Four cases:

    1. Agreement not signed/superseded/discontinued → (``set_billing_setup``
       URL, "", False) — the plan is still an intent, unconditionally,
       regardless of whether a record happens to exist.
    2. Agreement signed/superseded/discontinued, record found, reassignable
       (draft, no invoice pushed to Invoice Ninja, none e-mailed to a
       parent) → (``reassign`` URL, "", False).
    3. Same, record found, NOT reassignable → ("", <reason>, False) — the
       reviewer is told which guard bit rather than being allowed to submit
       into it.
    4. Agreement signed/superseded/discontinued, NO record found → neither
       plan endpoint can work. When the agreement is strictly SIGNED (not
       superseded/discontinued), carries a billing plan, and the member is
       ACTIVE — the exact guard ``recreate_missing_billing_record`` (via
       ``_signed_active_agreement`` at the POST) enforces — offering
       ``recreate_current_billing`` will actually succeed:
       ("", <explanatory reason>, True). Otherwise: ("", <blocked reason>,
       False) — the Hub must not dangle a control the POST would refuse.

       ``mismatched_record`` overrides that offer. Both the pipeline's
       season matcher and ``recreate_missing_billing_record``'s
       already-exists guard test the identical value
       (``agreement.billing_plan.season``), so a record whose season
       disagrees with it is invisible to *both*: the recreate does not
       refuse, it succeeds, and the member ends up with two records — the
       unique key is ``(member, season)`` and the seasons differ. The old
       row keeps the invoices and the new one is empty, with nothing on
       screen saying so. Where the domain cannot tell the two apart, the
       Hub refuses the shortcut and names the two seasons instead: the
       repair is re-pointing the link, never a second record.

       Detection is deliberately narrow — a record created for *this*
       agreement. A member's genuinely older seasons also sort below the
       current one, and blocking on those would break the ordinary renewal
       this remedy exists for. The material-amendment variant (record left
       pointing at the superseded agreement) therefore still slips through;
       it is tracked separately.

    ``invoices`` is the already-materialised list for ``record`` (from
    ``load_pipeline_objects``, which prefetches it) — checked in Python
    rather than with two fresh ``record.invoices.exists()`` queries against
    rows the caller already fetched. Pass ``[]`` when ``record`` is None.
    """
    from django.urls import reverse

    from apps.agreements.models import Agreement
    from apps.billing.models import BillingRecord
    from apps.members.models import Member

    review_action_url = reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application.pk],
    )

    if not _billing_is_locked(agreement):
        return (review_action_url, "", False)

    if record is not None:
        if str(record.status) != str(BillingRecord.Status.DRAFT):
            return "", (
                "Maksājumu ieraksts ir apstiprināts, tāpēc plāns tagad ir "
                "fiksēts ierakstā. Lai to mainītu, vispirms atsauciet "
                "ierakstu pilnajā administrācijā."
            ), False
        if any(invoice.external_invoice_id for invoice in invoices):
            return "", (
                "Rēķini jau ir izrakstīti Invoice Ninja — plānu vairs nevar "
                "mainīt, neatsaucot tos."
            ), False
        if any(invoice.sent_at is not None for invoice in invoices):
            return "", (
                "Rēķini jau ir nosūtīti vecākam — plānu vairs nevar mainīt, "
                "neatsaucot tos."
            ), False
        return (
            reverse("admin:billing_billingrecord_reassign", args=[record.pk]),
            "",
            False,
        )

    # No record. set_billing_setup refuses (locked state); there is nothing
    # to reassign. recreate_missing_billing_record can rebuild one, but only
    # under the same guard the POST enforces (_signed_active_agreement) —
    # mirror it exactly rather than offering a control guaranteed to fail.
    if mismatched_record is not None:
        plan_season = (
            agreement.billing_plan.season
            if agreement.billing_plan_id is not None
            else "—"
        )
        return "", (
            f"Līgumam ir piesaistīts norēķinu ieraksts par sezonu "
            f"{mismatched_record.season}, bet līguma plāns ir sezonai "
            f"{plan_season}. Atjaunošana izveidotu otru ierakstu, tāpēc tā "
            f"nav pieejama — vispirms saskaņojiet līguma plāna sezonu ar "
            f"esošo ierakstu pilnajā administrācijā."
        ), False

    if (
        agreement.state == Agreement.State.SIGNED
        and agreement.billing_plan_id is not None
        and member is not None
        and member.status == Member.Status.ACTIVE
    ):
        return "", (
            "Šai sezonai nav norēķinu ieraksta, lai gan līgums ir "
            "parakstīts. To var atjaunot no līguma — apstipriniet zemāk, "
            "ka Invoice Ninja nav atbilstoša rēķina."
        ), True
    return "", (
        "Šai sezonai nav norēķinu ieraksta, un to pašlaik nevar atjaunot no "
        "Admin Hub — pārbaudiet līguma un dalībnieka stāvokli pilnajā "
        "administrācijā."
    ), False


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


def _step_is_actionable(steps, key: str) -> bool:
    """Whether one pipeline step's own transition can be performed right now.

    Distinct from ``_step_is_done``: a step is actionable while its guard
    would accept the POST, and stops being actionable the moment it succeeds.
    ``build_pipeline`` already derives this — step "signed" is available
    exactly for ``GENERATED`` and ``SENT``, which is ``mark_agreement_signed``'s
    own state guard — so reading it here keeps the Hub from offering a button
    the endpoint refuses, without restating the state set."""
    from apps.admin_hub.pipeline import AVAILABLE, CURRENT

    return any(
        step.key == key and step.state in (CURRENT, AVAILABLE) for step in steps
    )


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
    from apps.billing.models import MembershipPlan
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    if objects.agreement is None:
        raise Http404("Šim pieteikumam vēl nav līguma.")

    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    agreement = objects.agreement
    # Step 6's plan is a precondition of step 5's signing, not a successor to
    # it: mark_agreement_signed raises "billing plan required" (P9) and
    # "first billing month required" (P15) before it will move the state. The
    # rail numbering follows the club's own description of the workflow, so
    # the fix is to bring the control to where it is needed rather than to
    # renumber - otherwise the reviewer has to leave for step 6 and come back
    # for every single agreement.
    plan_editable = not _billing_is_locked(agreement)
    plan, first_billing_month, schedule = _plan_preview(
        agreement, objects.billing_record
    )

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
            # mark_agreement_signed refuses any state but GENERATED/SENT, and
            # raises a raw English ValueError the admin has no Latvian mapping
            # for. The artifact clause used to mask that by accident on the
            # already-signed page; dropping it exposed the real gap.
            "can_mark_signed": _step_is_actionable(steps, "signed"),
            # Step 6's controls, surfaced here because signing needs them.
            # Editable only while the plan is still an intent on the
            # agreement; once locked, the BillingRecord owns it and step 6
            # is where it gets reassigned.
            "plan_editable": plan_editable,
            "plan": plan,
            "first_billing_month": first_billing_month,
            "schedule": schedule,
            "active_plans": (
                list(
                    MembershipPlan.objects.filter(is_active=True).order_by(
                        "season", "name"
                    )
                )
                if plan_editable
                else []
            ),
            "lifecycle_events": build_agreement_timeline(agreement)[:20],
        },
    )


@staff_member_required
def billing_view(request, pk: int):
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from apps.admin_hub.pipeline import (
        build_pipeline,
        load_pipeline_objects,
        pipeline_progress,
    )
    from apps.admin_hub import invoices as invoice_queries
    from apps.billing.models import BillingRecord, MembershipPlan
    from apps.registrations.models import RegistrationApplication

    application = get_object_or_404(RegistrationApplication, pk=pk)
    objects = load_pipeline_objects(application)
    if objects.agreement is None:
        raise Http404("Šim pieteikumam vēl nav līguma.")

    steps = build_pipeline(objects)
    done, total = pipeline_progress(steps)
    agreement = objects.agreement
    record = objects.billing_record
    # Uses objects.invoices — already prefetched/materialised by
    # load_pipeline_objects for this same record — instead of two fresh
    # .exists() queries against rows already in memory.
    (
        billing_change_url,
        billing_change_blocked_reason,
        billing_recreate_offer,
    ) = _billing_change_route(
        application,
        agreement,
        objects.member,
        record,
        objects.invoices,
        objects.mismatched_record,
    )

    # Preview the schedule from whatever is selected now, so the reviewer sees
    # the consequence before saving. Shared with the agreement page's step-5
    # plan block - see _plan_preview.
    plan, first_billing_month, schedule = _plan_preview(agreement, record)

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
            # Signed agreement, no matched record, member active: neither
            # plan endpoint applies, but recreate_current_billing would
            # succeed - offer it instead of just refusing.
            "billing_recreate_offer": billing_recreate_offer,
            # The template must not compare against a domain enum literal.
            "record_confirmed": (
                record is not None
                and str(record.status) == str(BillingRecord.Status.CONFIRMED)
            ),
            "invoices": objects.invoices,
            "payment_badge_classes": invoice_queries.PAYMENT_BADGE_CLASSES,
            "next_season_record": objects.next_season_record,
            "schedule": schedule,
            # The read-only display once billing_change_blocked_reason is
            # set (DEFECT 2) — record's own plan/month when a record
            # exists, else the agreement's intent (same row the schedule
            # preview above already reads).
            "plan": plan,
            "first_billing_month": first_billing_month,
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

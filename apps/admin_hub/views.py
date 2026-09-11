"""Admin Hub views. Every page is staff-only and renders derived state; all
mutations POST to the existing Django admin action endpoints."""

from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import redirect, render

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


def hub_index_view(request):
    """/hub/ entry point: permanent redirect to the queue.

    No auth gate here on purpose — the queue view owns its staff-only
    authorization — and query parameters are deliberately dropped."""
    return redirect("admin_hub:queue", permanent=True)


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
            # Approval always lands on the agreement page. A submitted
            # application has no agreement yet, but approve_application
            # creates it before redirecting, so the destination is known
            # unconditionally here — unlike agreement_url above.
            "approval_next_url": reverse("admin_hub:agreement", args=[application.pk]),
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
            # The seven-step pipeline no longer has a standalone plan step;
            # signing still requires this saved plan and first month.
            "has_billing_plan": (
                plan is not None and bool(first_billing_month)
            ),
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

    # Read-only preview of the installments the worker would materialise.
    # Mirrors materialize_installments exactly: zero-value records have no
    # rows, the snapshot count caps the schedule, and upfront collapses to
    # one row for the full total on the first due date. Never persisted —
    # creating rows here would falsely imply invoices exist and interfere
    # with the worker's idempotency contract.
    invoice_preview: list = []
    if record is not None and not objects.invoices and record.final_amount != Decimal("0.00"):
        schedule = derive_installment_schedule(
            record.plan,
            record.final_amount,
            first_billing_month=record.first_billing_month,
            installment_count=record.scheduled_installment_count,
        )
        if record.payment_mode == BillingRecord.PaymentMode.UPFRONT:
            invoice_preview = [(schedule[0][0], record.final_amount)]
        else:
            invoice_preview = schedule

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
            # The template must not compare against a domain enum literal.
            "record_confirmed": (
                record is not None
                and str(record.status) == str(BillingRecord.Status.CONFIRMED)
            ),
            "invoices": objects.invoices,
            "invoice_preview": invoice_preview,
            "payment_badge_classes": invoice_queries.PAYMENT_BADGE_CLASSES,
            "next_season_record": objects.next_season_record,
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


@staff_member_required
def exports_view(request):
    """Run-only member export runner (``/hub/eksporti/``, 2026-09-11).

    One staff-only endpoint over the shared P17 machinery: GET renders the
    template chooser and a selected template's stored filters; POST parses
    ``HubMemberExportRunForm`` and dispatches preview (never audited) versus
    download (exactly one ``MEMBER_EXPORT_RUN`` event with structural-only
    effective-filter metadata). Everything below the form boundary — the
    query, the columns, the writers — is P17 canonical: the Hub passes its
    temporary effective filters as explicit keyword overrides and renders
    preview cells through the same pure readers the download uses, so the
    two can never disagree. The Hub creates, edits, defaults, or persists
    nothing here — no template mutation, no stored output, no jobs.
    """
    from django.conf import settings as django_settings
    from django.core.exceptions import ValidationError
    from django.http import Http404
    from django.shortcuts import get_object_or_404
    from django.urls import reverse

    from apps.admin_hub.forms import HubMemberExportRunForm
    from apps.agreements.models import Agreement
    from apps.core.audit import record_audit_event
    from apps.core.models import AuditEvent
    from apps.members.export_templates import (
        build_template_member_queryset,
        render_member_export,
    )
    from apps.members.exports import COLUMN_REGISTRY, SENSITIVE_KEYS
    from apps.members.models import MemberExportTemplate, TrainingGroup

    def _annotate(template: MemberExportTemplate) -> MemberExportTemplate:
        """Presentation metadata computed once per template in Python — the
        template must not derive sensitivity or column labels itself."""
        keys = list(template.column_keys or [])
        template.column_count = len(keys)
        template.has_sensitive = any(key in SENSITIVE_KEYS for key in keys)
        template.column_labels = [
            COLUMN_REGISTRY[key].label for key in keys if key in COLUMN_REGISTRY
        ]
        return template

    def _resolve_selected(raw_pk: object) -> MemberExportTemplate | None:
        """Best-effort template resolution for re-rendering (chooser page +
        form errors keep the runner visible). Annotated when found — every
        render path must carry the same presentation metadata, an invalid
        POST included. Never 404s here — the strict contract (404 on unknown
        id) runs only for a validated form."""
        try:
            pk = int(str(raw_pk))
        except (TypeError, ValueError):
            return None
        selected: MemberExportTemplate | None = (
            MemberExportTemplate.objects.filter(pk=pk).first()
        )
        return _annotate(selected) if selected is not None else None

    templates = [_annotate(t) for t in MemberExportTemplate.objects.all()]
    context: dict[str, object] = {
        "hub_section": "exports",
        "templates": templates,
        "all_groups": list(TrainingGroup.objects.order_by("name", "pk")),
        "agreement_state_options": Agreement.State.choices,
        "repair_url": reverse(
            "admin:members_memberexporttemplate_changelist"
        ),
        "selected_template": None,
        "selected_agreement_states": [],
        "selected_group_ids": [],
        "fmt": "xlsx",
        "form": None,
        "template_error": "",
        "preview": None,
    }

    def _render_page() -> object:
        return render(request, "admin_hub/exports.html", context)

    if request.method == "POST":
        form = HubMemberExportRunForm(request.POST)
        context["form"] = form
        context["selected_template"] = _resolve_selected(
            form.data.get("template_id")
        )
        # Carry the submitted selections back into the controls so an
        # invalid POST never silently resets staff work.
        context["selected_agreement_states"] = list(
            form.data.getlist("agreement_states")
        )
        context["selected_group_ids"] = [
            int(v) for v in form.data.getlist("group_ids") if str(v).isdigit()
        ]
        raw_fmt = form.data.get("fmt") or ""
        context["fmt"] = raw_fmt if raw_fmt in {"xlsx", "csv"} else "xlsx"
        if not form.is_valid():
            # Errors only: no P17 query, no output, no audit.
            return _render_page()

        selected = _annotate(
            get_object_or_404(
                MemberExportTemplate, pk=form.cleaned_data["template_id"]
            )
        )
        context["selected_template"] = selected
        states: list[str] = list(form.cleaned_data["agreement_states"])
        group_ids: list[int] = form.effective_group_ids
        fmt: str = form.cleaned_data["fmt"]
        context["selected_agreement_states"] = states
        context["selected_group_ids"] = group_ids
        context["fmt"] = fmt

        try:
            selected.full_clean()
        except ValidationError:
            # Persisted-invalid template (validation bypass elsewhere): the
            # Hub refuses to run it and repairs only via Django admin.
            context["template_error"] = (
                "Šablons ir nederīgs — labojiet kolonnas un statusus "
                "pilnajā administrācijā."
            )
            return _render_page()

        if form.cleaned_data["action"] == "preview":
            qs = build_template_member_queryset(
                selected, agreement_states=states, group_ids=group_ids
            )
            limit = int(django_settings.EXPORT_PREVIEW_ROW_LIMIT)
            keys = list(selected.column_keys or [])
            # Exact total count, capped rows — same queryset, same effective
            # filters the download would use. Readers ride the P17
            # select_related/prefetch; the loop below must stay query-free.
            context["preview"] = {
                "count": qs.count(),
                "limit": limit,
                "headers": [COLUMN_REGISTRY[k].label for k in keys],
                "rows": [
                    [COLUMN_REGISTRY[k].reader(member) for k in keys]
                    for member in qs[:limit]
                ],
            }
            return _render_page()

        rendered = render_member_export(
            selected, fmt, agreement_states=states, group_ids=group_ids
        )
        record_audit_event(
            action=str(AuditEvent.Action.MEMBER_EXPORT_RUN),
            actor=request.user,
            request=request,
            target_type="member_export_template",
            target_id=str(selected.pk),
            target_repr="Member export template",
            metadata={
                "template_id": selected.pk,
                "column_keys": list(selected.column_keys or []),
                "agreement_status_filters": states,
                # Deterministic ascending pks: the form carries (name, pk)
                # display order, which a rename could silently reshuffle.
                "training_group_ids": sorted(group_ids),
                "row_count": rendered.row_count,
                "format": fmt,
                "sensitive": rendered.sensitive,
            },
        )
        return rendered.response

    raw = request.GET.get("template")
    if raw is not None:
        selected = _resolve_selected(raw)
        if raw.isdigit() and selected is not None:
            # Annotated inside _resolve_selected — the only strict-id path.
            context["selected_template"] = selected
            context["selected_agreement_states"] = [
                s
                for s in (selected.agreement_status_filters or [])
                if isinstance(s, str)
            ]
            context["selected_group_ids"] = list(
                selected.training_groups.values_list("pk", flat=True)
            )
        else:
            # Non-integer or unknown pk — same 404 contract as the admin run
            # page for a missing template.
            raise Http404("Šablons nav atrasts.")
    return _render_page()

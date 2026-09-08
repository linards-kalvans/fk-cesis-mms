"""Derivation of the eight-step registration pipeline.

The pipeline is *derived*, never stored. ``load_pipeline_objects`` does the
database work; ``build_pipeline`` is pure so every state combination is
testable without fixtures.

Each step's "done" test reads a value the domain actually persists. Step 4
("Izsniegts") keys off ``Agreement.sent_at`` rather than a download count,
because nothing in the domain counts downloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.registrations.models import RegistrationApplication

if TYPE_CHECKING:
    from apps.agreements.models import Agreement
    from apps.billing.models import BillingInvoice, BillingRecord
    from apps.members.models import Member

DONE = "done"
CURRENT = "current"
AVAILABLE = "available"
LOCKED = "locked"

STEP_DEFS: tuple[tuple[int, str, str], ...] = (
    (1, "verify", "Datu pārbaude"),
    (2, "approve", "Apstiprināšana"),
    (3, "agreement", "Līgums"),
    (4, "handover", "Izsniegts"),
    (5, "signed", "Parakstītais"),
    (6, "plan", "Maksas plāns"),
    (7, "invoices", "Rēķini"),
    (8, "next_season", "Nākamā sezona"),
)


@dataclass(frozen=True)
class PipelineStep:
    number: int
    key: str
    name: str
    state: str
    meta: str


@dataclass(frozen=True)
class PipelineObjects:
    application: RegistrationApplication
    member: "Member | None"
    agreement: "Agreement | None"
    billing_record: "BillingRecord | None"
    invoices: list["BillingInvoice"]
    next_season_record: "BillingRecord | None"
    # A record linked to THIS agreement whose season disagrees with the
    # agreement's plan season - i.e. billing that was realised against this
    # agreement but that the season matcher below cannot see. It is not a
    # past season the member legitimately has: those belong to earlier,
    # superseded agreements. See the guard in views._billing_change_route.
    mismatched_record: "BillingRecord | None" = None


def load_pipeline_objects(application: RegistrationApplication) -> PipelineObjects:
    """Fetch every row the pipeline derivation reads, in a bounded number of
    queries. Safe on a draft application, which has no member yet."""
    from apps.billing.models import BillingRecord

    member = application.approved_member
    agreement = None
    billing_record = None
    invoices: list[BillingInvoice] = []
    next_season_record = None
    mismatched_record = None

    if member is not None:
        agreement = (
            member.agreements.filter(is_current=True)
            .select_related("billing_plan")
            .first()
        )
        records = list(
            BillingRecord.objects.filter(member=member)
            .select_related("plan")
            .prefetch_related("invoices")
            .order_by("season")
        )
        current_season = agreement.billing_plan.season if (
            agreement is not None and agreement.billing_plan_id is not None
        ) else ""
        for record in records:
            if current_season and record.season == current_season:
                billing_record = record
            elif current_season and record.season > current_season:
                next_season_record = next_season_record or record
            elif (
                current_season
                and agreement is not None
                and record.agreement_id == agreement.pk
            ):
                # Season below the agreement's plan season, yet created for
                # this very agreement: a desync, not history. Surfacing it
                # keeps the Hub from offering to "recreate" billing that
                # already exists under another season - the unique key is
                # (member, season), so that would succeed and silently
                # leave two records.
                mismatched_record = mismatched_record or record
        if billing_record is None and records and not current_season:
            billing_record = records[0]
        if billing_record is not None:
            invoices = list(billing_record.invoices.all())

    return PipelineObjects(
        application=application,
        member=member,
        agreement=agreement,
        billing_record=billing_record,
        invoices=invoices,
        next_season_record=next_season_record,
        mismatched_record=mismatched_record,
    )


def _fmt_date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def build_pipeline(objects: PipelineObjects) -> list[PipelineStep]:
    """Turn persisted state into eight ordered steps. Pure: no DB access."""
    from apps.agreements.models import Agreement

    status = RegistrationApplication.Status
    application = objects.application
    agreement = objects.agreement

    has_plan = agreement is not None and (
        agreement.billing_plan_id is not None and bool(agreement.first_billing_month)
    )
    pushed = [i for i in objects.invoices if i.external_invoice_id]

    done = {
        "verify": application.status in (status.APPROVED, status.REJECTED),
        "approve": application.status == status.APPROVED,
        "agreement": agreement is not None,
        "handover": agreement is not None and agreement.sent_at is not None,
        "signed": agreement is not None and agreement.state == Agreement.State.SIGNED,
        "plan": has_plan,
        "invoices": bool(objects.invoices) and len(pushed) == len(objects.invoices),
        "next_season": objects.next_season_record is not None,
    }
    available = {
        "verify": application.status in (status.SUBMITTED, status.FIX_REQUESTED),
        "approve": application.status == status.SUBMITTED,
        "agreement": objects.member is not None,
        "handover": agreement is not None,
        "signed": agreement is not None
        and agreement.state in (Agreement.State.GENERATED, Agreement.State.SENT),
        "plan": agreement is not None,
        "invoices": objects.billing_record is not None,
        "next_season": objects.billing_record is not None and done["signed"],
    }
    meta = {
        "verify": "",
        "approve": _fmt_date(application.reviewed_at) if done["approve"] else "",
        "agreement": _fmt_date(getattr(agreement, "generated_at", None)),
        "handover": _fmt_date(getattr(agreement, "sent_at", None)),
        "signed": _fmt_date(getattr(agreement, "signed_at", None)),
        "plan": getattr(agreement, "first_billing_month", "") if has_plan else "",
        "invoices": (
            f"{len(pushed)}/{len(objects.invoices)} izrakstīti"
            if objects.invoices
            else ""
        ),
        "next_season": (
            objects.next_season_record.season if objects.next_season_record else ""
        ),
    }

    steps: list[PipelineStep] = []
    current_claimed = False
    for number, key, name in STEP_DEFS:
        if done[key]:
            state = DONE
        elif available[key] and not current_claimed:
            state = CURRENT
            current_claimed = True
        elif available[key]:
            state = AVAILABLE
        else:
            state = LOCKED
        steps.append(
            PipelineStep(number=number, key=key, name=name, state=state, meta=meta[key])
        )
    return steps


def pipeline_progress(steps: list[PipelineStep]) -> tuple[int, int]:
    return (sum(1 for step in steps if step.state == DONE), len(STEP_DEFS))


def current_step(steps: list[PipelineStep]) -> PipelineStep | None:
    for step in steps:
        if step.state == CURRENT:
            return step
    return None

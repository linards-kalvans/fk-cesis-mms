"""Pure context/status builders for the family admin action hub.

These helpers power both the queue (cross-guardian) and the per-family hub
pages. They are intentionally pure (no request/admin concerns) so the same
shapes can be reused from future server-rendered surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, cast

from django.utils import timezone
from django.utils.html import format_html

from apps.agreements.services import get_current_agreement
from apps.billing.models import BillingRecord
from apps.billing.messages import (
    PAYMENT_STATUS_LABELS,
    get_invoice_error_message,
)
from apps.registrations.models import RegistrationApplication

if TYPE_CHECKING:
    from apps.agreements.models import Agreement
    from apps.billing.models import BillingInvoice
    from apps.members.models import Guardian, Member


@dataclass(frozen=True)
class FamilyLaneStatus:
    """A normalized status row for a single family/child lane.

    ``level`` is one of ok / fail / pending / muted (compatible with
    ``apps.core.admin_badges.status_badge``). ``urgency`` orders lanes in the
    action queue: higher = more urgent.
    """

    key: str
    label: str
    badge: str
    level: str
    icon: str
    next_action: str
    urgency: int


# ---------------------------------------------------------------------------
# Per-object status helpers
# ---------------------------------------------------------------------------


_URGENCY_INFORMATIONAL = 0
_URGENCY_BILLING_PAYMENT_SYNC = 10
_URGENCY_BILLING_PUSH = 30
_URGENCY_BILLING_DRAFT = 40
_URGENCY_AGREEMENT_NEEDS_ACTION = 50
_URGENCY_APPLICATION_SUBMITTED = 80


class _QueueRow(TypedDict):
    guardian: "Guardian"
    statuses: list[FamilyLaneStatus]
    needs_action: bool
    next_action: str
    highest_urgency: int


class _InvoiceRow(TypedDict):
    invoice: "BillingInvoice"
    due_date: object
    amount: object
    external_status: str
    payment_status_label: str
    external_invoice_id: str
    error_message: str


class _BillingGroup(TypedDict):
    record: BillingRecord
    member: "Member"
    season: str
    status: FamilyLaneStatus
    invoices: list[_InvoiceRow]
    error_message: str
    deep_link: str


class _Child(TypedDict):
    member: "Member | None"
    application: "RegistrationApplication | None"
    agreement: "Agreement | None"
    kit_size_label: str
    application_status: FamilyLaneStatus
    agreement_status: FamilyLaneStatus
    membership_status: FamilyLaneStatus
    billing_groups: list[_BillingGroup]
    deep_links: dict[str, str]
    anchor_id: str
    billing_setup_error: str
    document_links: list[dict[str, object]]
    signed_artifact_links: list[dict[str, object]]


def _child_anchor_id(
    application: "RegistrationApplication | None",
    member: "Member | None",
) -> str:
    """Stable per-child DOM id used as URL fragment on the family hub.

    Source application wins when present (an approved application keeps its
    application anchor even though it created a Member). Otherwise the
    member pk is used.
    """
    if application is not None and getattr(application, "pk", None):
        return f"child-application-{application.pk}"
    if member is not None and getattr(member, "pk", None):
        return f"child-member-{member.pk}"
    return ""


def application_lane(application: RegistrationApplication) -> FamilyLaneStatus:
    """Lane status for a registration application."""
    if application.status == RegistrationApplication.Status.SUBMITTED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums gaida apstiprinājumu",
            badge="Iesniegts",
            level="pending",
            icon="📝",
            next_action="Apstiprināt",
            urgency=_URGENCY_APPLICATION_SUBMITTED,
        )
    if application.status == RegistrationApplication.Status.FIX_REQUESTED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums jālabo",
            badge="Jālabo",
            level="fail",
            icon="✏",
            next_action="Skatīt",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if application.status == RegistrationApplication.Status.REJECTED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums noraidīts",
            badge="Noraidīts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if application.status == RegistrationApplication.Status.APPROVED:
        return FamilyLaneStatus(
            key="application",
            label="Pieteikums apstiprināts",
            badge="Apstiprināts",
            level="ok",
            icon="✓",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    return FamilyLaneStatus(
        key="application",
        label="Melnraksts",
        badge="Melnraksts",
        level="muted",
        icon="📄",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def agreement_lane(agreement: "Agreement | None") -> FamilyLaneStatus:
    """Lane status for the member's current agreement (None = none)."""
    if agreement is None:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums nav izveidots",
            badge="—",
            level="muted",
            icon="—",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.external_state == "failed" or agreement.external_error_code:
        return FamilyLaneStatus(
            key="agreement",
            label="Līguma izsūtīšana neizdevās",
            badge="Kļūda",
            level="fail",
            icon="⚠",
            next_action="Mēģināt vēlreiz",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if agreement.state == agreement.State.GENERATED:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums sagatavots",
            badge="Sagatavots",
            level="pending",
            icon="📄",
            next_action="Atzīmēt nosūtītu",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if agreement.state == agreement.State.SENT:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums nosūtīts parakstīšanai",
            badge="Nosūtīts",
            level="pending",
            icon="✉",
            next_action="Atzīmēt parakstītu",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    if agreement.state == agreement.State.SIGNED:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums parakstīts",
            badge="Parakstīts",
            level="ok",
            icon="✓",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.state == agreement.State.VOID:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums atcelts",
            badge="Atcelts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.state == agreement.State.DISCONTINUED:
        return FamilyLaneStatus(
            key="agreement",
            label="Dalība pārtraukta",
            badge="Pārtraukts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if agreement.state == agreement.State.SUPERSEDED:
        return FamilyLaneStatus(
            key="agreement",
            label="Līgums aizvietots",
            badge="Aizvietots",
            level="muted",
            icon="—",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    return FamilyLaneStatus(
        key="agreement",
        label=str(agreement.get_state_display()),
        badge=str(agreement.get_state_display()),
        level="muted",
        icon="—",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def membership_lane(member: "Member | None") -> FamilyLaneStatus:
    """Lane status for a member's participation state."""
    if member is None:
        return FamilyLaneStatus(
            key="membership",
            label="Biedrs nav izveidots",
            badge="—",
            level="muted",
            icon="—",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if member.status == member.Status.DISCONTINUED:
        return FamilyLaneStatus(
            key="membership",
            label="Dalība pārtraukta",
            badge="Pārtraukts",
            level="muted",
            icon="⛔",
            next_action="—",
            urgency=_URGENCY_INFORMATIONAL,
        )
    if member.training_group_id is None:
        return FamilyLaneStatus(
            key="membership",
            label="Biedrs aktīvs (grupa nav piešķirta)",
            badge="Bez grupas",
            level="pending",
            icon="👥",
            next_action="Piešķirt grupu",
            urgency=_URGENCY_AGREEMENT_NEEDS_ACTION,
        )
    return FamilyLaneStatus(
        key="membership",
        label="Biedrs aktīvs",
        badge="Aktīvs",
        level="ok",
        icon="✓",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


def billing_lane(record: BillingRecord) -> FamilyLaneStatus:
    """Lane status for a billing record."""
    if record.external_error_code:
        return FamilyLaneStatus(
            key="billing",
            label="Rēķinu izsūtīšana neizdevās",
            badge="Kļūda",
            level="fail",
            icon="⚠",
            next_action="Mēģināt vēlreiz",
            urgency=_URGENCY_BILLING_PUSH,
        )
    if record.status == BillingRecord.Status.DRAFT:
        return FamilyLaneStatus(
            key="billing",
            label="Norēķini sagatavoti (jāapstiprina)",
            badge="Melnraksts",
            level="pending",
            icon="💳",
            next_action="Apstiprināt",
            urgency=_URGENCY_BILLING_DRAFT,
        )
    if record.status == BillingRecord.Status.CONFIRMED and record.external_status != "synced":
        return FamilyLaneStatus(
            key="billing",
            label="Norēķini gaida izsūtīšanu",
            badge="Gaida izsūtīšanu",
            level="pending",
            icon="📨",
            next_action="Izrakstīt rēķinus",
            urgency=_URGENCY_BILLING_PUSH,
        )
    if record.external_status == "synced":
        if record.payment_status in {"unpaid", "partial", "paid"}:
            return FamilyLaneStatus(
                key="billing",
                label=f"Rēķini izsūtīti ({PAYMENT_STATUS_LABELS.get(record.payment_status, '—')})",
                badge="Sinhronizēts",
                level="ok",
                icon="✓",
                next_action="Pārbaudīt maksājumus",
                urgency=_URGENCY_BILLING_PAYMENT_SYNC,
            )
        return FamilyLaneStatus(
            key="billing",
            label="Rēķini izsūtīti",
            badge="Sinhronizēts",
            level="ok",
            icon="✓",
            next_action="Pārbaudīt maksājumus",
            urgency=_URGENCY_BILLING_PAYMENT_SYNC,
        )
    return FamilyLaneStatus(
        key="billing",
        label=str(record.get_status_display()),
        badge=str(record.get_status_display()),
        level="muted",
        icon="—",
        next_action="—",
        urgency=_URGENCY_INFORMATIONAL,
    )


# ---------------------------------------------------------------------------
# Kit-size helper
# ---------------------------------------------------------------------------


def canonical_kit_size_label(obj) -> str:
    """Return the single canonical "Formas izmērs" label or '—'.

    Reads ``member_kit_size_shirt`` from a RegistrationApplication-like object.
    The legacy ``kit_size_shirt`` member fallback is gone: ``Member`` has no
    such field, and the canonical value lives on the source application.
    """
    option = getattr(obj, "member_kit_size_shirt", None)
    if option is None:
        return "—"
    return str(getattr(option, "label", "—") or "—")


# ---------------------------------------------------------------------------
# Family context builders
# ---------------------------------------------------------------------------


def _first_current_agreement(member: "Member") -> "Agreement | None":
    """Return the member's current agreement from the prefetched cache.

    Mirrors ``apps.agreements.services.get_current_agreement`` (current row is
    the only one with ``is_current=True``) but reads ``member.agreements.all()``
    instead of issuing a fresh query, so the queue path stays N+1-free.
    """
    for agreement in member.agreements.all():  # type: ignore[attr-defined]
        if agreement.is_current:
            return cast("Agreement", agreement)
    return None


def _row_for_guardian(guardian: "Guardian") -> _QueueRow | None:
    """Return one queue row for a guardian, or None when no action needed.

    A family is "needs action" if any of:
    - a submitted/fix_requested application exists;
    - a generated/sent agreement exists;
    - a draft or failed billing record exists.

    Consumes prefetched caches populated by ``build_family_queue_rows`` —
    do not add new per-row queries here.
    """
    applications = sorted(
        list(guardian.applications.all()),
        key=lambda a: a.created_at,
        reverse=True,
    )
    members = list(guardian.members.all())
    member_by_id = {m.pk: m for m in members}

    statuses: list[FamilyLaneStatus] = []
    needs_action = False
    next_action_parts: list[str] = []
    highest_urgency = _URGENCY_INFORMATIONAL

    for application in applications:
        lane = application_lane(application)
        statuses.append(lane)
        if lane.urgency > highest_urgency:
            highest_urgency = lane.urgency
        if lane.next_action and lane.next_action != "—":
            needs_action = True
            next_action_parts.append(lane.next_action)
        # Agreement for this application's member (if approved) — read the
        # prefetched `member.agreements` cache instead of running a fresh
        # `get_current_agreement` query per approved application.
        if application.approved_member_id is not None:
            member = member_by_id.get(application.approved_member_id)
            if member is not None:
                agreement = _first_current_agreement(member)
                if agreement is not None:
                    al = agreement_lane(agreement)
                    statuses.append(al)
                    if al.urgency > highest_urgency:
                        highest_urgency = al.urgency
                    if al.next_action and al.next_action != "—":
                        needs_action = True
                        next_action_parts.append(al.next_action)

    # Membership + billing across all members
    for member in members:
        ml = membership_lane(member)
        statuses.append(ml)
        if ml.urgency > highest_urgency:
            highest_urgency = ml.urgency
        if ml.next_action and ml.next_action != "—":
            needs_action = True
            next_action_parts.append(ml.next_action)
        for record in member.billing_records.all():
            bl = billing_lane(record)
            statuses.append(bl)
            if bl.urgency > highest_urgency:
                highest_urgency = bl.urgency
            if bl.next_action and bl.next_action != "—":
                needs_action = True
                next_action_parts.append(bl.next_action)

    if not needs_action:
        return None

    next_action = ", ".join(dict.fromkeys(next_action_parts)) or "—"
    return {
        "guardian": guardian,
        "statuses": statuses,
        "needs_action": needs_action,
        "next_action": next_action,
        "highest_urgency": highest_urgency,
    }


def build_family_queue_rows() -> list[_QueueRow]:
    """Return all families that need action, sorted by urgency + name + pk."""
    from apps.members.models import Guardian

    rows: list[_QueueRow] = []
    # Prefetch applications, members (with training_group), the members'
    # billing_records, and the members' agreements so the per-guardian inner
    # loop stays in-memory and avoids N+1s on the three relations it walks.
    guardian_qs = (
        Guardian.objects.all()
        .order_by("pk")
        .prefetch_related(
            "applications",
            "members__training_group",
            "members__billing_records",
            "members__agreements",
        )
    )
    for guardian in guardian_qs:
        row = _row_for_guardian(guardian)
        if row is not None:
            rows.append(row)
    rows.sort(
        key=lambda r: (
            -r["highest_urgency"],
            str(getattr(r["guardian"], "display_name", "")).lower(),
            int(r["guardian"].pk),
        )
    )
    return rows


def build_family_hub_context(
    guardian: "Guardian",
    billing_setup_errors: dict[int, str] | None = None,
) -> dict[str, object]:
    """Return the full per-family hub context."""
    from apps.billing.models import MembershipPlan
    from apps.members.models import TrainingGroup

    applications = list(
        guardian.applications.order_by("-created_at")
        .select_related("guardian", "parent_account", "approved_member")
    )
    members = list(
        guardian.members.all().select_related(
            "training_group", "source_application"
        )
    )
    # Prefetch each member's non-empty-external_id agreements once per
    # request so the per-child document list stays in-memory and the hub
    # does not N+1 over ``Agreement`` (it would otherwise issue one query
    # per child for the historical agreements). Ordering matches the
    # spec: most-recent first, ties broken by pk.
    members_with_agreements = (
        guardian.members.prefetch_related(
            "agreements",
        )
    )
    members_by_pk = {m.pk: m for m in members_with_agreements}
    billing_records = list(
        BillingRecord.objects.filter(member__guardian=guardian)
        .select_related("member", "plan", "agreement")
        .prefetch_related("invoices")
        .order_by("member__full_name", "-season", "pk")
    )
    billing_setup_errors = billing_setup_errors or {}

    # Group billing records by member for the unified billing block
    billing_groups: list[_BillingGroup] = []
    for record in billing_records:
        member = record.member
        invoices = list(record.invoices.all().order_by("sequence"))
        billing_groups.append(
            {
                "record": record,
                "member": member,
                "season": record.season,
                "status": billing_lane(record),
                "invoices": [
                    _invoice_row(invoice) for invoice in invoices
                ],
                "error_message": (
                    get_invoice_error_message(record.external_error_code)
                    if record.external_error_code
                    else ""
                ),
                "deep_link": _billing_deep_link(record),
            }
        )

    children: list[_Child] = []
    for member in members:
        application = getattr(member, "source_application", None)
        agreement = get_current_agreement(member)
        kit_size_label = canonical_kit_size_label(member) if application is None else canonical_kit_size_label(application)
        prefetched = members_by_pk.get(member.pk)
        document_links = _build_member_document_links(prefetched, member)
        signed_artifact_links = _build_member_signed_artifact_links(
            prefetched, member
        )
        children.append(
            {
                "member": member,
                "application": application,
                "agreement": agreement,
                "kit_size_label": kit_size_label,
                "application_status": application_lane(application) if application else application_lane(_blank_application()),
                "agreement_status": agreement_lane(agreement),
                "membership_status": membership_lane(member),
                "billing_groups": [g for g in billing_groups if g["member"].pk == member.pk],
                "deep_links": {
                    "member": _member_deep_link(member),
                    "application": _application_deep_link(application) if application else "",
                    "agreement": _agreement_deep_link(agreement) if agreement else "",
                },
                "anchor_id": _child_anchor_id(application, member),
                "billing_setup_error": billing_setup_errors.get(agreement.pk, "") if agreement else "",
                "document_links": document_links,
                "signed_artifact_links": signed_artifact_links,
            }
        )

    # If the family has no Member yet but does have a submitted application,
    # surface that application as a "pending child" so staff can act on it.
    for application in applications:
        if application.approved_member_id is not None:
            continue
        children.append(
            {
                "member": None,
                "application": application,
                "agreement": None,
                "kit_size_label": canonical_kit_size_label(application),
                "application_status": application_lane(application),
                "agreement_status": agreement_lane(None),
                "membership_status": membership_lane(None),
                "billing_groups": [],
                "deep_links": {
                    "member": "",
                    "application": _application_deep_link(application),
                    "agreement": "",
                },
                "anchor_id": _child_anchor_id(application, None),
                "billing_setup_error": "",
                "document_links": [],
                "signed_artifact_links": [],
            }
        )

    statuses: list[FamilyLaneStatus] = []
    needs_action = False
    highest_urgency = _URGENCY_INFORMATIONAL
    next_action_parts: list[str] = []
    for child in children:
        for lane in (
            child["application_status"],
            child["agreement_status"],
            child["membership_status"],
        ):
            statuses.append(lane)
            if lane.urgency > highest_urgency:
                highest_urgency = lane.urgency
            if lane.next_action and lane.next_action != "—":
                needs_action = True
                next_action_parts.append(lane.next_action)
        for group in child["billing_groups"]:
            statuses.append(group["status"])
            if group["status"].urgency > highest_urgency:
                highest_urgency = group["status"].urgency
            if group["status"].next_action and group["status"].next_action != "—":
                needs_action = True
                next_action_parts.append(group["status"].next_action)

    return {
        "guardian": guardian,
        "members": members,
        "applications": applications,
        "children": children,
        "billing_groups": billing_groups,
        "statuses": statuses,
        "needs_action": needs_action,
        "highest_urgency": highest_urgency,
        "active_training_groups": list(
            TrainingGroup.objects.filter(is_active=True).order_by("name")
        ),
        "membership_plans": list(
            MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
        ),
        "next_action": ", ".join(dict.fromkeys(next_action_parts)) or "—",
    }


def _build_member_document_links(
    prefetched_member: "Member | None", member: "Member | None"
) -> list[dict[str, object]]:
    """Build the per-child document list, filtered to non-empty external_ids.

    Reads from the prefetched ``member.agreements`` cache (populated by the
    hub builder) so this helper stays N+1-free. The list is built via
    :func:`apps.agreements.presentation.build_agreement_document_links` with
    a closure over the guardian id — every URL points at the family hub's
    own document route (with ``?disposition=attachment`` appended at the
    template layer).
    """
    if prefetched_member is None or member is None:
        return []
    from apps.agreements.presentation import build_agreement_document_links
    from django.urls import reverse

    guardian_id = member.guardian_id
    agreements = [
        a for a in prefetched_member.agreements.all()  # type: ignore[attr-defined]
        if a.external_id
    ]
    if not agreements:
        return []

    def _url_builder(agreement):
        return str(
            reverse(
                "admin:members_guardian_docuseal_document",
                args=[guardian_id, agreement.pk],
            )
        )

    return build_agreement_document_links(agreements, url_builder=_url_builder)


_ARTIFACT_SORT_FALLBACK = timezone.datetime(2000, 1, 1, tzinfo=timezone.UTC)


def _build_member_signed_artifact_links(
    prefetched_member: "Member | None", member: "Member | None"
) -> list[dict[str, object]]:
    """Build the per-child signed-artifact list (P16-A).

    Returns only ``Agreement`` rows with a non-empty ``signed_artifact`` across
    every lifecycle state (current, superseded, voided, discontinued), newest
    first by ``signed_artifact_updated_at`` (pk tie-break). Reads from the
    prefetched ``member.agreements`` cache so the hub stays N+1-free, and
    points every row at the guardian-scoped signed-artifact proxy route —
    never a raw storage URL. The DocuSeal ``document_links`` list is left
    untouched.
    """
    if prefetched_member is None or member is None:
        return []
    from django.urls import reverse

    agreements = [
        a
        for a in prefetched_member.agreements.all()  # type: ignore[attr-defined]
        if a.signed_artifact
    ]
    if not agreements:
        return []
    agreements = sorted(
        agreements,
        key=lambda a: (
            a.signed_artifact_updated_at or _ARTIFACT_SORT_FALLBACK,
            a.pk,
        ),
        reverse=True,
    )
    guardian_id = member.guardian_id
    return [
        {
            "agreement": agreement,
            "state_label": str(agreement.get_state_display()),
            "signing_path_label": str(agreement.get_signing_path_display()),
            "download_url": str(
                reverse(
                    "admin:members_guardian_signed_artifact",
                    args=[guardian_id, agreement.pk],
                )
            ),
        }
        for agreement in agreements
    ]


def _blank_application() -> RegistrationApplication:
    """A throwaway application shell used as a default for missing children."""
    app = RegistrationApplication()
    app.status = RegistrationApplication.Status.DRAFT
    return app


def _invoice_row(invoice: "BillingInvoice") -> _InvoiceRow:
    return {
        "invoice": invoice,
        "due_date": invoice.due_date,
        "amount": invoice.amount,
        "external_status": invoice.external_status or "—",
        "payment_status_label": PAYMENT_STATUS_LABELS.get(
            invoice.payment_status, "—"
        ),
        "external_invoice_id": invoice.external_invoice_id,
        "error_message": (
            get_invoice_error_message(invoice.external_error_code)
            if invoice.external_error_code
            else ""
        ),
    }


def _application_deep_link(application) -> str:
    if application is None or not getattr(application, "pk", None):
        return ""
    from django.urls import reverse

    return str(
        reverse(
            "admin:registrations_registrationapplication_change",
            args=[application.pk],
        )
    )


def _member_deep_link(member) -> str:
    if member is None or not getattr(member, "pk", None):
        return ""
    from django.urls import reverse

    return str(
        reverse("admin:members_member_change", args=[member.pk])
    )


def _agreement_deep_link(agreement) -> str:
    if agreement is None or not getattr(agreement, "pk", None):
        return ""
    from django.urls import reverse

    return str(
        reverse("admin:agreements_agreement_change", args=[agreement.pk])
    )


def _billing_deep_link(record) -> str:
    if record is None or not getattr(record, "pk", None):
        return ""
    from django.urls import reverse

    return str(
        reverse("admin:billing_billingrecord_change", args=[record.pk])
    )


def render_status_badge(status: FamilyLaneStatus):
    """Convenience renderer for the template layer."""
    from apps.core.admin_badges import status_badge

    return format_html("{} {}", status_badge(status.badge, status.level), status.label)

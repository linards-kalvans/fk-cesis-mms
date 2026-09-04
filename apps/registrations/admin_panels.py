"""Review-context builders for the admin registration change page.

Hosts the document-preview classification and per-kind panel builder
(formerly private helpers in ``views.py``) plus ``build_review_context``
which assembles the full panels + agreement + training-group context.
"""

from django.db.models import F
from django.urls import reverse

from apps.agreements.messages import get_agreement_error_message
from apps.agreements.models import Agreement
from apps.agreements.presentation import build_agreement_document_links
from apps.core.admin_links import admin_link, admin_links
from apps.agreements.services import get_current_agreement
from apps.billing.models import BillingAdjustment, BillingInvoice, MembershipPlan, PaymentStatus
from apps.members.models import Member
from apps.documents.models import Document
from apps.documents.ocr import decrypt_json
from apps.members.models import TrainingGroup
from apps.registrations.models import RegistrationApplication
from apps.registrations.presentation import (
    DOCUMENT_KIND_LABELS,
    OCR_FIELD_LABELS,
    parse_ocr_summary,
)

_IMAGE_PREVIEW_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic"})
_PDF_PREVIEW_EXTENSIONS = frozenset({"pdf"})


def doc_preview_kind(document: object) -> str:
    """Classify a Document by file extension for inline-preview rendering.

    Returns ``"image"`` for image extensions (jpg/jpeg/png/webp/heic),
    ``"pdf"`` for PDF, and ``"other"`` for everything else (including missing
    or empty filenames). Uses ``original_filename`` when present, else
    ``document.file.name``. Comparison is case-insensitive.
    """
    filename = getattr(document, "original_filename", "") or ""
    if not filename:
        file_obj = getattr(document, "file", None)
        filename = getattr(file_obj, "name", "") or ""
    if "." not in filename:
        return "other"
    extension = filename.rsplit(".", 1)[1].lower()
    if extension in _IMAGE_PREVIEW_EXTENSIONS:
        return "image"
    if extension in _PDF_PREVIEW_EXTENSIONS:
        return "pdf"
    return "other"


def build_doc_panel(
    application: RegistrationApplication, kind: str
) -> dict[str, object]:
    """Build the per-kind panel context dict consumed by _doc_panel.html."""
    documents = application.documents.filter(kind=kind)
    active = (
        documents.filter(deleted_at__isnull=True)
        .select_related("extraction")
        .first()
    )
    replaced = list(
        documents.filter(deleted_at__isnull=False).order_by("-created_at")
    )
    for replaced_doc in replaced:
        replaced_doc.preview_kind = doc_preview_kind(replaced_doc)

    ocr_summary: list[tuple[str, str]] = []
    ocr_confidence_items: list[tuple[str, object]] = []
    if active is not None and kind != Document.Kind.MEMBER_PORTRAIT:
        extraction = getattr(active, "extraction", None)
        if extraction is not None:
            try:
                summary_value = decrypt_json(extraction.encrypted_summary)
                if isinstance(summary_value, str):
                    ocr_summary = parse_ocr_summary(summary_value)
                payload_value = decrypt_json(extraction.encrypted_payload)
                if isinstance(payload_value, dict):
                    confidence = payload_value.get("confidence")
                    if isinstance(confidence, dict):
                        ocr_confidence_items = [
                            (
                                OCR_FIELD_LABELS.get(
                                    str(key), str(key).replace("_", " ").title()
                                ),
                                value,
                            )
                            for key, value in confidence.items()
                        ]
            except Exception:
                ocr_summary = []
                ocr_confidence_items = []

    return {
        "kind": kind,
        "panel_title": DOCUMENT_KIND_LABELS.get(kind, kind),
        "active": active,
        "replaced": replaced,
        "ocr_summary": ocr_summary,
        "ocr_confidence_items": ocr_confidence_items,
        "preview_kind": doc_preview_kind(active) if active is not None else "",
    }


def build_review_context(
    application: RegistrationApplication,
) -> dict[str, object]:
    """Assemble panels + agreement + training-group context for review."""
    guardian_panel = build_doc_panel(
        application, str(Document.Kind.GUARDIAN_IDENTITY)
    )
    member_panel = build_doc_panel(application, str(Document.Kind.MEMBER_IDENTITY))
    portrait_panel = build_doc_panel(
        application, str(Document.Kind.MEMBER_PORTRAIT)
    )

    active_training_groups = list(
        TrainingGroup.objects.filter(is_active=True).order_by("name")
    )

    current_inactive_group = None
    if application.approved_member_id is not None:
        assigned = application.approved_member.training_group
        if assigned is not None and not assigned.is_active:
            current_inactive_group = assigned

    agreement = None
    if application.approved_member_id is not None:
        agreement = get_current_agreement(application.approved_member)

    agreement_error_message = None
    if agreement is not None and agreement.external_state == "failed":
        agreement_error_message = get_agreement_error_message(
            agreement.external_error_code
        )

    member = application.approved_member if application.approved_member_id else None
    billing_records = (
        list(member.billing_records.order_by("-created_at")) if member is not None else []
    )
    # The application's own guardian FK is often unset; resolve the canonical
    # guardian from the most reliable source available.
    guardian = application.guardian
    if guardian is None and member is not None:
        guardian = member.guardian
    if guardian is None and application.parent_account_id:
        guardian = getattr(application.parent_account, "guardian", None)
    related_links = {
        "Biedrs": admin_link(member),
        "Vecāks": admin_link(guardian),
        "Līgums": admin_link(agreement),
        "Rēķini": admin_links(billing_records),
    }

    agreement_lifecycle_events = []
    if agreement is not None:
        agreement_lifecycle_events = list(
            agreement.lifecycle_events.order_by("created_at")
        )

    # All non-empty-external-id agreements for the approved member —
    # current + history (generated, sent, signed, void, superseded,
    # discontinued). Ordered most-recent-first with pk as the stable tie
    # breaker. Powers the shared admin/_agreement_list.html partial so
    # staff can preview/download any document that ever had a DocuSeal
    # submission. The filter is non-empty external_id only — agreements
    # that never reached DocuSeal are excluded.
    document_links: list[dict] = []
    if member is not None:
        history_agreements = list(
            Agreement.objects.filter(member=member)
            .exclude(external_id="")
            .order_by("-generated_at", "-pk")
        )
        if history_agreements:

            def _url_builder(agreement_obj):
                return str(
                    reverse(
                        "admin:registrations_registrationapplication_docuseal_document",
                        args=[application.pk, agreement_obj.pk],
                    )
                )

            document_links = build_agreement_document_links(
                history_agreements, url_builder=_url_builder
            )

    # P16-A: every Agreement of the source member — current + history
    # (generated, sent, signed, void, superseded, discontinued) — newest
    # first, including rows without an artifact so staff can upload or
    # replace on any lifecycle state. Sensitive artifact coordinates are
    # never rendered: the template builds same-origin proxy URLs only.
    signed_artifact_agreements: list[Agreement] = []
    if member is not None:
        signed_artifact_agreements = list(
            Agreement.objects.filter(member=member).order_by(
                F("signed_artifact_updated_at").desc(nulls_last=True),
                "-generated_at",
                "-pk",
            )
        )

    discontinuation_invoice_candidates = []
    billing_adjustments = []
    discontinued_billing_invoices = []
    if member is not None and agreement is not None:
        if (
            agreement.state == Agreement.State.SIGNED
            and member.status == Member.Status.ACTIVE
        ):
            discontinuation_invoice_candidates = _discontinuation_candidates(member)
            billing_adjustments = list(
                BillingAdjustment.objects.filter(
                    billing_record__member=member
                ).order_by("-created_at")
            )
        elif (
            agreement.state == Agreement.State.DISCONTINUED
            or member.status == Member.Status.DISCONTINUED
        ):
            discontinued_billing_invoices = list(
                BillingInvoice.objects.filter(
                    billing_record__member=member, cancelled_at__isnull=False
                ).order_by("due_date")
            )
            billing_adjustments = list(
                BillingAdjustment.objects.filter(
                    billing_record__member=member
                ).order_by("-created_at")
            )

    return {
        "related_links": related_links,
        "guardian_panel": guardian_panel,
        "member_panel": member_panel,
        "portrait_panel": portrait_panel,
        "active_training_groups": active_training_groups,
        "current_inactive_group": current_inactive_group,
        "agreement": agreement,
        "agreement_error_message": agreement_error_message,
        "agreement_lifecycle_events": agreement_lifecycle_events,
        "document_links": document_links,
        "signed_artifact_agreements": signed_artifact_agreements,
        "discontinuation_invoice_candidates": discontinuation_invoice_candidates,
        "discontinued_billing_invoices": discontinued_billing_invoices,
        "billing_adjustments": billing_adjustments,
        "membership_plans": list(
            MembershipPlan.objects.filter(is_active=True).order_by("season", "name")
        ),
    }


def _proposed_action_for_invoice(invoice: BillingInvoice) -> str:
    if invoice.payment_status in (PaymentStatus.PAID, PaymentStatus.PARTIAL):
        return "Bloķē — jāapstrādā manuāli Invoice Ninja"
    if not invoice.external_invoice_id and invoice.sent_at is None:
        return "Atcelt lokāli"
    if invoice.external_invoice_id and invoice.external_status == "created":
        return "Arhivēt Invoice Ninja"
    if invoice.external_invoice_id and invoice.external_status == "sent":
        return "Atcelt Invoice Ninja"
    return "Nezināms stāvoklis — bloķēs"


def _discontinuation_candidates(member) -> list[BillingInvoice]:
    """Return eligible BillingInvoice rows for a member discontinuation form."""
    invoices = list(
        BillingInvoice.objects.filter(
            billing_record__member=member
        ).select_related("billing_record").order_by("due_date")
    )
    for invoice in invoices:
        invoice.proposed_action = _proposed_action_for_invoice(invoice)
    return invoices

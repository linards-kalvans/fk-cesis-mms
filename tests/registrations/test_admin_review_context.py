"""build_review_context — panels + agreement + training-group context for the admin change page."""

import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.registrations.admin_panels import build_review_context, doc_preview_kind
from apps.registrations.models import RegistrationApplication

from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def _png_upload(name):
    return SimpleUploadedFile(
        name=name,
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        content_type="image/png",
    )


def _make_document(application, kind, name):
    from apps.documents.models import Document

    return Document.objects.create(
        application=application,
        kind=kind,
        file=_png_upload(name),
        original_filename=name,
        content_type="image/png",
        file_size=12,
    )


def test_doc_preview_kind_classifies_by_extension():
    class _Doc:
        original_filename = "id.PNG"
        file = None
    assert doc_preview_kind(_Doc()) == "image"
    _Doc.original_filename = "scan.pdf"
    assert doc_preview_kind(_Doc()) == "pdf"
    _Doc.original_filename = "notes.txt"
    assert doc_preview_kind(_Doc()) == "other"


def test_build_review_context_keys():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    ctx = build_review_context(app)
    assert set(ctx) >= {
        "guardian_panel", "member_panel", "member_back_panel", "portrait_panel",
        "active_training_groups", "current_inactive_group",
        "agreement", "agreement_error_message",
    }
    assert ctx["agreement"] is None
    assert ctx["guardian_panel"]["kind"]


def test_build_review_context_approved_member_branches():
    from django.utils import timezone

    from apps.agreements.models import Agreement
    from apps.members.models import Member, TrainingGroup

    g = make_guardian(full_name="Vecāks")
    inactive = TrainingGroup.objects.create(name="Vecā grupa", is_active=False)
    m = Member.objects.create(full_name="Bērns", guardian=g, training_group=inactive)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED,
        member_full_name="Bērns",
        approved_member=m,
    )
    Agreement.objects.create(
        member=m,
        is_current=True,
        state=Agreement.State.GENERATED,
        generated_at=timezone.now(),
        external_state="failed",
        external_error_code="provider_unavailable",
    )
    ctx = build_review_context(app)
    assert ctx["current_inactive_group"] == inactive  # inactive assigned group surfaced
    assert ctx["agreement"] is not None
    assert ctx["agreement_error_message"]  # failed external_state -> Latvian message


# ---------------------------------------------------------------------------
# Member ID-card back panel (2026-09-11 plan, Task 3 Step 1 / requirement 8)
# ---------------------------------------------------------------------------


def test_member_back_panel_surfaces_active_doc_without_ocr():
    from apps.documents.models import Document

    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    back = _make_document(app, Document.Kind.MEMBER_IDENTITY_BACK, "back_id.png")

    panel = build_review_context(app)["member_back_panel"]

    assert panel["kind"] == str(Document.Kind.MEMBER_IDENTITY_BACK)
    assert panel["active"] == back
    assert panel["replaced"] == []
    # The back image is never OCR-processed: no readout, no confidence chips.
    assert panel["ocr_summary"] == []
    assert panel["ocr_confidence_items"] == []
    # Latvian label on the parent-facing surface comes from DOCUMENT_KIND_LABELS.
    assert panel["panel_title"] == "Bērna ID kartes aizmugure"
    assert panel["preview_kind"] == "image"


def test_member_back_panel_empty_without_upload():
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    panel = build_review_context(app)["member_back_panel"]
    assert panel["active"] is None
    assert panel["ocr_summary"] == []


@pytest.mark.admin_view
def test_admin_change_page_renders_back_panel_after_member_front(staff_client):
    """The registration admin change page must show a distinct fourth panel
    for the back document, positioned right after the member front panel,
    with its Latvian title and the authorized staff preview proxy URL."""
    from apps.documents.models import Document

    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="Bērns"
    )
    front = _make_document(app, Document.Kind.MEMBER_IDENTITY, "front_id.png")
    back = _make_document(app, Document.Kind.MEMBER_IDENTITY_BACK, "back_id.png")
    _make_document(app, Document.Kind.MEMBER_PORTRAIT, "portrait.png")

    url = reverse(
        "admin:registrations_registrationapplication_change", args=[app.pk]
    )
    html = staff_client.get(url).content.decode()

    # Distinct panel for the back kind exists.
    assert 'data-kind="member_identity_back"' in html
    assert "Bērna ID kartes aizmugure" in html

    # The back thumbnail links to the existing authorized preview proxy.
    back_preview = reverse("documents:admin-document-preview", args=[back.id])
    assert back_preview in html

    # Panel order: back panel sits directly after the member front panel.
    panel_kinds = re.findall(
        r'<section class="mms-review-panel" data-kind="([^"]+)"', html
    )
    assert panel_kinds.index("member_identity_back") == (
        panel_kinds.index("member_identity") + 1
    ), f"back panel must follow the member front panel; got {panel_kinds}"

    # No OCR readout is rendered anywhere: the back panel never has one, and
    # the other direct-created docs carry no extractions either.
    assert "mms-review-ocr-readout" not in html
    assert reverse("documents:admin-document-preview", args=[front.id]) in html

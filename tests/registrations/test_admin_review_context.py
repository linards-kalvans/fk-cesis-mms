"""build_review_context — panels + agreement + training-group context for the admin change page."""

import pytest

from apps.registrations.admin_panels import build_review_context, doc_preview_kind
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


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
        "guardian_panel", "member_panel", "portrait_panel",
        "active_training_groups", "current_inactive_group",
        "agreement", "agreement_error_message",
    }
    assert ctx["agreement"] is None
    assert ctx["guardian_panel"]["kind"]

"""build_review_context — panels + agreement + training-group context for the admin change page."""

import pytest

from apps.registrations.admin_panels import build_review_context, doc_preview_kind
from apps.registrations.models import RegistrationApplication

from tests.support import make_guardian

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

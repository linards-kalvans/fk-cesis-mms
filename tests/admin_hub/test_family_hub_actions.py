"""P11: Family hub POST actions — permissions, workflow, ownership."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _action_url(guardian):
    return reverse("admin:members_guardian_family_hub_action", args=[guardian.pk])


def _docuseal_document_url(guardian, agreement):
    return reverse(
        "admin:members_guardian_docuseal_document",
        args=[guardian.pk, agreement.pk],
    )


def test_non_staff_cannot_post_action(client, submitted_application):
    """Anonymous/non-staff must be blocked from hub actions."""
    guardian = submitted_application.guardian
    response = client.post(
        _action_url(guardian),
        {"action": "confirm_billing", "billing_record_id": "999"},
    )
    assert response.status_code in (302, 403)


def test_approve_application_from_hub(staff_client, submitted_application):
    """Approve application via hub POST changes status and creates member."""
    from apps.registrations.models import RegistrationApplication

    guardian = submitted_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "approve_application",
            "application_id": submitted_application.pk,
        },
    )
    assert response.status_code == 302

    submitted_application.refresh_from_db()
    assert submitted_application.status == RegistrationApplication.Status.APPROVED
    assert submitted_application.approved_member_id is not None


def test_mark_agreement_sent_from_hub(staff_client, approved_application):
    """Mark agreement sent via hub POST changes state to SENT."""
    from apps.agreements.models import Agreement

    guardian = approved_application.guardian
    agreement = Agreement.objects.get(
        member=approved_application.approved_member, is_current=True
    )

    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "mark_agreement_sent",
            "agreement_id": agreement.pk,
        },
    )
    assert response.status_code == 302

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SENT


def test_void_agreement_does_not_discontinue_member(
    staff_client, approved_application,
):
    """Void agreement must NOT change member status to discontinued."""
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_sent, mark_agreement_signed
    from apps.members.models import Member

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    mark_agreement_sent(agreement, None)
    mark_agreement_signed(agreement, None)

    guardian = approved_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "void_agreement",
            "agreement_id": agreement.pk,
            "void_reason": "Test void",
        },
    )
    assert response.status_code == 302

    agreement.refresh_from_db()
    member.refresh_from_db()
    assert agreement.state == Agreement.State.VOID
    assert member.status == Member.Status.ACTIVE


def test_discontinue_member_from_hub(
    staff_client, approved_application,
):
    """Discontinue membership via hub POST moves the member to discontinued
    and the agreement to discontinued. Complements the void test above."""
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_sent, mark_agreement_signed
    from apps.members.models import Member

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    mark_agreement_sent(agreement, None)
    mark_agreement_signed(agreement, None)

    guardian = approved_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "discontinue_member",
            "agreement_id": agreement.pk,
            "effective_date": "2026-07-01",
            "reason": "Bērns pamet klubu",
        },
    )
    assert response.status_code == 302

    agreement.refresh_from_db()
    member.refresh_from_db()
    assert agreement.state == Agreement.State.DISCONTINUED
    assert member.status == Member.Status.DISCONTINUED


def test_confirm_billing_from_hub(
    staff_client, approved_application, billing_record_factory,
):
    """Confirm billing via hub POST changes DRAFT → CONFIRMED."""
    from apps.billing.models import BillingRecord

    member = approved_application.approved_member
    record = billing_record_factory(member, status=BillingRecord.Status.DRAFT)
    guardian = approved_application.guardian

    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "confirm_billing",
            "billing_record_id": record.pk,
        },
    )
    assert response.status_code == 302

    record.refresh_from_db()
    assert record.status == BillingRecord.Status.CONFIRMED


def test_push_billing_from_hub_calls_enqueue(
    staff_client, approved_application, billing_record_factory,
):
    """Push billing via hub POST must call enqueue_push_billing_record."""
    from apps.billing.models import BillingRecord

    member = approved_application.approved_member
    record = billing_record_factory(member, status=BillingRecord.Status.CONFIRMED)
    guardian = approved_application.guardian

    with patch("apps.members.admin.enqueue_push_billing_record") as enqueue:
        response = staff_client.post(
            _action_url(guardian),
            {
                "action": "push_billing",
                "billing_record_id": record.pk,
            },
        )

    assert response.status_code == 302
    enqueue.assert_called_once_with(record.pk)


def test_sync_billing_payments_from_hub_calls_enqueue(
    staff_client, approved_application, billing_record_factory,
):
    """Sync billing payments via hub POST must call enqueue_sync_billing_record_payments."""
    member = approved_application.approved_member
    record = billing_record_factory(member)
    guardian = approved_application.guardian

    with patch("apps.members.admin.enqueue_sync_billing_record_payments") as enqueue:
        response = staff_client.post(
            _action_url(guardian),
            {
                "action": "sync_billing_payments",
                "billing_record_id": record.pk,
            },
        )

    assert response.status_code == 302
    enqueue.assert_called_once_with(record.pk)


def test_action_rejects_cross_family_billing_record(
    staff_client, submitted_application, billing_record_factory,
):
    """A billing record belonging to a different guardian must be rejected (404)."""
    from apps.billing.models import BillingRecord
    from apps.members.models import Member
    from tests.support import make_guardian as _make_guardian
    from apps.accounts.models import ParentAccount

    # The submitted_application's guardian
    guardian = submitted_application.guardian

    # Create an unrelated family with a billing record
    other_account = ParentAccount.objects.create(email="other-family@example.com")
    other_guardian = _make_guardian(account=other_account, full_name="Other Parent")
    other_member = Member.objects.create(full_name="Other Child", guardian=other_guardian)
    other_record = billing_record_factory(other_member, status=BillingRecord.Status.DRAFT)

    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "confirm_billing",
            "billing_record_id": other_record.pk,
        },
    )
    assert response.status_code == 404


def test_action_rejects_cross_family_application(
    staff_client, submitted_application, other_parent_account,
):
    """Application actions must reject another guardian's application."""
    from apps.registrations.services import create_or_update_draft

    other_application = create_or_update_draft(
        data={"guardian_email": other_parent_account.email},
        files={},
        verified_account=other_parent_account,
    )

    response = staff_client.post(
        _action_url(submitted_application.guardian),
        {
            "action": "approve_application",
            "application_id": other_application.pk,
        },
    )

    assert response.status_code == 404


def test_action_rejects_cross_family_agreement(
    staff_client, submitted_application, active_plan,
):
    """Agreement actions, including billing setup, must reject another guardian's agreement."""
    from apps.accounts.models import ParentAccount
    from apps.agreements.services import create_agreement_for_member
    from apps.members.models import Member
    from tests.support import make_guardian as _make_guardian

    other_account = ParentAccount.objects.create(email="agreement-family@example.com")
    other_guardian = _make_guardian(account=other_account, full_name="Agreement Parent")
    other_member = Member.objects.create(
        full_name="Agreement Child", guardian=other_guardian
    )
    other_agreement = create_agreement_for_member(other_member, signing_path="paper")

    response = staff_client.post(
        _action_url(submitted_application.guardian),
        {
            "action": "set_billing_setup",
            "agreement_id": other_agreement.pk,
            "billing_plan": active_plan.pk,
            "first_billing_month": "2026-09",
        },
    )

    assert response.status_code == 404


def test_set_billing_setup_from_hub(staff_client, approved_application, active_plan):
    """POSTing set_billing_setup with agreement_id, billing_plan, and
    first_billing_month persists both fields on the agreement."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    # Clear any default billing plan from approval
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "set_billing_setup",
            "agreement_id": agreement.pk,
            "billing_plan": active_plan.pk,
            "first_billing_month": "2026-09",
        },
    )
    assert response.status_code == 302

    agreement.refresh_from_db()
    assert agreement.billing_plan_id == active_plan.pk
    assert agreement.first_billing_month == "2026-09"


def test_mark_agreement_signed_after_set_billing_setup(
    staff_client, approved_application, active_plan,
):
    """After setting billing setup through the hub, mark_agreement_signed
    succeeds and the agreement becomes signed."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month", "updated_at"])

    guardian = approved_application.guardian

    # Step 1: set billing setup
    staff_client.post(
        _action_url(guardian),
        {
            "action": "set_billing_setup",
            "agreement_id": agreement.pk,
            "billing_plan": active_plan.pk,
            "first_billing_month": "2026-09",
        },
    )

    # Step 2: mark signed — must succeed now
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "mark_agreement_signed",
            "agreement_id": agreement.pk,
        },
    )
    assert response.status_code == 302

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SIGNED


def test_docuseal_document_endpoint_redirects_to_pdf(
    staff_client, approved_application,
):
    """DocuSeal document proxy endpoint must redirect to the first PDF URL
    returned by list_submission_documents."""
    from apps.agreements.models import Agreement
    from apps.integrations.agreement_platform import DocumentResult

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    pdf_url = "https://sign.example/docs/501.pdf"

    with patch(
        "apps.members.admin.agreement_platform.list_submission_documents"
    ) as list_docs:
        list_docs.return_value = [
            DocumentResult(
                filename="agreement.pdf",
                url=pdf_url,
                content_type="application/pdf",
            )
        ]

        response = staff_client.get(_docuseal_document_url(guardian, agreement))

    assert response.status_code == 302
    assert response["Location"] == pdf_url


def test_docuseal_document_endpoint_rejects_cross_family(
    staff_client, approved_application, other_parent_account,
):
    """DocuSeal document endpoint must reject requests for agreements that
    don't belong to the specified guardian (404)."""
    from apps.agreements.services import create_agreement_for_member
    from apps.members.models import Member
    from apps.members.services import resolve_guardian_for_account

    # Create another guardian + agreement
    other_guardian = resolve_guardian_for_account(other_parent_account)
    other_member = Member.objects.create(
        full_name="Other Child", guardian=other_guardian
    )
    other_agreement = create_agreement_for_member(other_member, signing_path="paper")
    other_agreement.external_id = "2002"
    other_agreement.save(update_fields=["external_id", "updated_at"])

    # Try to access other_agreement via approved_application's guardian
    guardian = approved_application.guardian
    response = staff_client.get(_docuseal_document_url(guardian, other_agreement))

    assert response.status_code == 404


def test_docuseal_document_endpoint_redirects_back_when_no_external_id(
    staff_client, approved_application,
):
    """When the agreement has no DocuSeal submission id, endpoint must
    redirect back to the hub with an admin message."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = ""
    agreement.save(update_fields=["external_id", "updated_at"])

    response = staff_client.get(
        _docuseal_document_url(approved_application.guardian, agreement), follow=True
    )

    assert response.status_code == 200
    messages = [m.message for m in response.context["messages"]]
    assert any("DocuSeal sūtījums vēl nav izveidots" in msg for msg in messages)


def test_docuseal_document_endpoint_redirects_back_when_no_documents(
    staff_client, approved_application,
):
    """When list_submission_documents returns empty, endpoint must redirect
    back to the hub with an admin message."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian

    with patch(
        "apps.members.admin.agreement_platform.list_submission_documents"
    ) as list_docs:
        list_docs.return_value = []

        response = staff_client.get(
            _docuseal_document_url(guardian, agreement), follow=True
        )

    assert response.status_code == 200
    messages = [m.message for m in response.context["messages"]]
    assert any("DocuSeal dokuments nav atrasts" in msg for msg in messages)


def test_assign_training_group_from_hub(
    staff_client, approved_application,
):
    """POSTing assign_training_group sets the member's training_group."""
    from apps.members.models import TrainingGroup

    group = TrainingGroup.objects.create(name="U10 A", is_active=True)
    member = approved_application.approved_member
    member.training_group = None
    member.save(update_fields=["training_group"])

    guardian = approved_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "assign_training_group",
            "member_id": member.pk,
            "training_group": group.pk,
        },
    )
    assert response.status_code == 302

    member.refresh_from_db()
    assert member.training_group_id == group.pk


def test_assign_training_group_rejects_cross_family_member(
    staff_client, approved_application,
):
    """Assigning a training group to another guardian's member must 404."""
    from apps.accounts.models import ParentAccount
    from apps.members.models import Member, TrainingGroup
    from tests.support import make_guardian as _make_guardian

    group = TrainingGroup.objects.create(name="U10 A", is_active=True)
    other_account = ParentAccount.objects.create(email="cross-family-group@example.com")
    other_guardian = _make_guardian(account=other_account, full_name="Other Parent")
    other_member = Member.objects.create(
        full_name="Other Child", guardian=other_guardian,
    )

    guardian = approved_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "assign_training_group",
            "member_id": other_member.pk,
            "training_group": group.pk,
        },
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Anchor redirect contract — POST actions preserve return_anchor as fragment.
# ---------------------------------------------------------------------------


def _hub_url(guardian):
    return reverse("admin:members_guardian_family_hub", args=[guardian.pk])


def test_approve_application_redirects_to_its_application_anchor(
    staff_client, submitted_application,
):
    """Approval POST with return_anchor must redirect to hub + #child-application-<pk>."""
    guardian = submitted_application.guardian
    anchor = f"child-application-{submitted_application.pk}"
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "approve_application",
            "application_id": submitted_application.pk,
            "return_anchor": anchor,
        },
    )

    assert response["Location"] == f"{_hub_url(guardian)}#{anchor}"


def test_mark_agreement_sent_redirects_with_source_application_anchor(
    staff_client, approved_application,
):
    """Agreement action must redirect to the source application anchor."""
    from apps.agreements.models import Agreement

    guardian = approved_application.guardian
    agreement = Agreement.objects.get(
        member=approved_application.approved_member, is_current=True
    )
    anchor = f"child-application-{approved_application.pk}"

    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "mark_agreement_sent",
            "agreement_id": agreement.pk,
            "return_anchor": anchor,
        },
    )

    assert response["Location"] == f"{_hub_url(guardian)}#{anchor}"


def test_assign_training_group_redirects_with_source_application_anchor(
    staff_client, approved_application,
):
    """Training-group assignment must redirect to the source application anchor."""
    from apps.members.models import TrainingGroup

    group = TrainingGroup.objects.create(name="U10 B", is_active=True)
    member = approved_application.approved_member
    member.training_group = None
    member.save(update_fields=["training_group"])

    guardian = approved_application.guardian
    anchor = f"child-application-{approved_application.pk}"

    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "assign_training_group",
            "member_id": member.pk,
            "training_group": group.pk,
            "return_anchor": anchor,
        },
    )

    assert response["Location"] == f"{_hub_url(guardian)}#{anchor}"


def test_confirm_billing_redirects_with_source_application_anchor(
    staff_client, approved_application, billing_record_factory,
):
    """Billing confirmation must redirect to the source application anchor."""
    from apps.billing.models import BillingRecord

    member = approved_application.approved_member
    record = billing_record_factory(member, status=BillingRecord.Status.DRAFT)
    guardian = approved_application.guardian
    anchor = f"child-application-{approved_application.pk}"

    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "confirm_billing",
            "billing_record_id": record.pk,
            "return_anchor": anchor,
        },
    )

    assert response["Location"] == f"{_hub_url(guardian)}#{anchor}"


def test_hub_action_discards_invalid_return_anchor(
    staff_client, submitted_application,
):
    """Invalid return_anchor (external URL) must redirect to base hub, not attacker URL."""
    guardian = submitted_application.guardian
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "request_fix",
            "application_id": submitted_application.pk,
            "review_message": "Lūdzu papildiniet.",
            "return_anchor": "https://attacker.example/#x",
        },
    )

    assert response["Location"] == _hub_url(guardian)


def test_docuseal_pdf_error_fallback_preserves_return_anchor(
    staff_client, approved_application,
):
    """DocuSeal PDF endpoint fallback (no external_id) must redirect to
    hub + #anchor when return_anchor query param is valid."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = ""
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    anchor = f"child-application-{approved_application.pk}"
    url = _docuseal_document_url(guardian, agreement)

    response = staff_client.get(f"{url}?return_anchor={anchor}")

    assert response["Location"] == f"{_hub_url(guardian)}#{anchor}"


# ---------------------------------------------------------------------------
# Defect 1: billing-plan setup error must show inline, not as top-level message.
# ---------------------------------------------------------------------------


def test_billing_setup_error_shows_inline_not_top_level(
    staff_client, approved_application, active_plan,
):
    """POSTing set_billing_setup with missing first_billing_month must show
    the mapped Latvian error inline (inside the billing-plan form/card for
    that specific agreement), NOT as a Django admin global messagelist entry."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month", "updated_at"])

    guardian = approved_application.guardian
    anchor = f"child-application-{approved_application.pk}"

    # POST with missing first_billing_month → ValueError("first billing month required")
    response = staff_client.post(
        _action_url(guardian),
        {
            "action": "set_billing_setup",
            "agreement_id": agreement.pk,
            "billing_plan": active_plan.pk,
            "first_billing_month": "",  # invalid → triggers mapped error
            "return_anchor": anchor,
        },
    )
    assert response.status_code == 302

    # Follow redirect to hub
    hub_response = staff_client.get(_hub_url(guardian))
    html = hub_response.content.decode()

    # The mapped Latvian error must appear in the HTML.
    assert "Pirmais rēķina mēnesis ir obligāts." in html

    # The error must NOT appear in the Django admin messagelist (top-level).
    # Django admin renders messages inside <ul class="messagelist">.
    if 'class="messagelist"' in html:
        messagelist_section = html.split('class="messagelist"')[1].split("</ul>")[0]
        assert "Pirmais rēķina mēnesis ir obligāts." not in messagelist_section

    # The error must be inside the specific agreement's card region.
    # Each child card has id="child-application-<pk>". Extract the segment
    # after this anchor and assert the error is in that bounded region.
    anchor_marker = f'id="{anchor}"'
    assert anchor_marker in html, f"Anchor {anchor} must be present in hub HTML"

    # Split on the anchor and take everything after it (the card content).
    # Since there's only one child in this test, the segment extends to the end.
    card_segment = html.split(anchor_marker, 1)[1]

    # The error must be in this card segment (proves it's tied to this agreement).
    assert "Pirmais rēķina mēnesis ir obligāts." in card_segment

    # Additionally, the billing-plan form controls for this agreement must be present
    # in the same card (proves the error is near the controls, not just anywhere).
    billing_plan_field_id = f'id="hub_billing_plan_{agreement.pk}"'
    first_month_field_id = f'id="hub_first_month_{agreement.pk}"'
    assert billing_plan_field_id in card_segment, "Billing plan field must be in the same card"
    assert first_month_field_id in card_segment, "First billing month field must be in the same card"


def test_billing_setup_error_is_one_shot(
    staff_client, approved_application, active_plan,
):
    """After the POST-redirect-GET shows the inline error, a subsequent GET
    must no longer show it (one-shot error)."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(update_fields=["billing_plan", "first_billing_month", "updated_at"])

    guardian = approved_application.guardian
    anchor = f"child-application-{approved_application.pk}"

    # POST invalid billing setup
    staff_client.post(
        _action_url(guardian),
        {
            "action": "set_billing_setup",
            "agreement_id": agreement.pk,
            "billing_plan": active_plan.pk,
            "first_billing_month": "",
            "return_anchor": anchor,
        },
    )

    # First GET after POST → error present INLINE (not in messagelist).
    first_get = staff_client.get(_hub_url(guardian))
    first_html = first_get.content.decode()
    assert "Pirmais rēķina mēnesis ir obligāts." in first_html
    # Must NOT be in messagelist (top-level).
    if 'class="messagelist"' in first_html:
        messagelist_section = first_html.split('class="messagelist"')[1].split("</ul>")[0]
        assert "Pirmais rēķina mēnesis ir obligāts." not in messagelist_section
    # Must be inside the specific agreement's card region.
    anchor_marker = f'id="child-application-{approved_application.pk}"'
    first_card_segment = first_html.split(anchor_marker, 1)[1]
    assert "Pirmais rēķina mēnesis ir obligāts." in first_card_segment

    # Second GET → error absent (one-shot)
    second_get = staff_client.get(_hub_url(guardian))
    second_html = second_get.content.decode()
    assert "Pirmais rēķina mēnesis ir obligāts." not in second_html

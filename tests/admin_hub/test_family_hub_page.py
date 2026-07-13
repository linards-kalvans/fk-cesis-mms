"""P11: Family hub page rendering — lanes, kit-size, deep links."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _hub_url(guardian):
    return reverse("admin:members_guardian_family_hub", args=[guardian.pk])


def test_hub_requires_staff(client, submitted_application):
    """Non-staff user must be redirected or forbidden from the hub."""
    guardian = submitted_application.guardian
    response = client.get(_hub_url(guardian))
    assert response.status_code in (302, 403)


def test_hub_renders_all_lane_headings(staff_client, submitted_application):
    """Hub page must show all four lane headings."""
    guardian = submitted_application.guardian
    response = staff_client.get(_hub_url(guardian))
    assert response.status_code == 200

    html = response.content.decode()
    assert "Pieteikumi" in html
    assert "Līgumi" in html
    assert "Dalība" in html
    assert "Norēķini un rēķini" in html


def test_hub_renders_next_action_label(staff_client, submitted_application):
    """A submitted application must show the Apstiprināt next-action label."""
    guardian = submitted_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()
    assert "Apstiprināt" in html


def test_hub_renders_single_form_size_label(
    staff_client, submitted_application, kit_sizes,
):
    """Hub shows one kit-size label 'Formas izmērs' and does NOT show
    'Šortu izmērs', 'member_kit_size_shorts', or raw shorts label."""
    from apps.members.models import KitSizeOption

    shirt_pk, _shorts_pk = kit_sizes
    shirt = KitSizeOption.objects.get(pk=shirt_pk)
    submitted_application.member_kit_size_shirt = shirt
    submitted_application.save(update_fields=["member_kit_size_shirt", "updated_at"])

    guardian = submitted_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Formas izmērs" in html
    assert "Šortu izmērs" not in html
    assert "member_kit_size_shorts" not in html


def test_hub_includes_deep_admin_links(staff_client, approved_application):
    """Hub must include 'Atvērt detalizēti' deep admin links."""
    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Atvērt detalizēti" in html
    assert "/admin/" in html


def test_hub_lane_status_uses_badge_class_with_icon_and_next_action(
    staff_client, submitted_application,
):
    """Each hub lane (application/agreement/membership/billing) must render
    as icon + .fk-badge with a level class + next-action label, not raw text
    'Statuss: <badge>.' alone."""
    guardian = submitted_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert response.status_code == 200
    # At least one .fk-badge with a level class on the hub.
    assert "fk-badge--" in html
    assert "fk-badge--pending" in html
    # Old plain-text "Statuss: <badge>." pattern is gone.
    assert "Statuss: Iesniegts." not in html
    # Icon char + badge text + next action all present for the application lane.
    assert "Apstiprināt" in html
    assert "Iesniegts" in html


def test_hub_renders_billing_plan_setup_form_for_unsigned_agreement(
    staff_client, approved_application, active_plan,
):
    """Unsigned agreement (generated/sent) without billing plan must render
    a billing-plan setup form with Norēķinu plāns + Pirmais rēķina mēnesis
    fields and a set_billing_setup action."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    # Ensure agreement is in 'generated' state with no billing plan.
    assert agreement.state == Agreement.State.GENERATED
    agreement.billing_plan = None
    agreement.save(update_fields=["billing_plan", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Norēķinu plāns" in html
    assert "Pirmais rēķina mēnesis" in html
    assert 'name="billing_plan"' in html
    assert 'name="first_billing_month"' in html
    assert 'value="set_billing_setup"' in html


def test_hub_shows_missing_billing_plan_warning_for_generated_or_sent(
    staff_client, approved_application,
):
    """When agreement has no billing plan and state is generated or sent,
    the hub must show a visible warning about the missing plan."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.billing_plan = None
    agreement.save(update_fields=["billing_plan", "updated_at"])

    # generated state
    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()
    assert "norēķinu plāns" in html.lower() or "billing plan" in html.lower()

    # sent state
    from apps.agreements.services import mark_agreement_sent
    from apps.billing.models import MembershipPlan

    plan = MembershipPlan.objects.filter(is_active=True).first()
    agreement.billing_plan = plan
    agreement.save(update_fields=["billing_plan", "updated_at"])
    mark_agreement_sent(agreement, None)
    # Now clear it again to test sent-state warning
    agreement.billing_plan = None
    agreement.save(update_fields=["billing_plan", "updated_at"])

    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()
    assert "norēķinu plāns" in html.lower() or "billing plan" in html.lower()


def test_hub_hides_mark_signed_until_billing_plan_is_set(
    staff_client, approved_application,
):
    """Sent agreement without a billing plan should show setup form, not the
    premature sign button that would only raise a service error."""
    from apps.agreements.models import Agreement
    from apps.agreements.services import mark_agreement_sent

    agreement = Agreement.objects.get(
        member=approved_application.approved_member, is_current=True
    )
    mark_agreement_sent(agreement, None)
    agreement.billing_plan = None
    agreement.save(update_fields=["billing_plan", "updated_at"])

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    assert "Trūkst norēķinu plāna" in html
    assert 'value="set_billing_setup"' in html
    assert 'value="mark_agreement_signed"' not in html


def test_discontinue_lives_under_daliba_heading_and_void_under_ligumi(
    staff_client, approved_application,
):
    """Agreement void belongs in the Līgumi lane; membership discontinuation
    belongs in the Dalība lane. The rendered HTML order must reflect that."""
    from apps.agreements.services import mark_agreement_sent, mark_agreement_signed

    # Drive the agreement to "signed" so the discontinue disclosure renders
    # and the void disclosure is still present (not void/discontinued).
    member = approved_application.approved_member
    from apps.agreements.models import Agreement
    agreement = Agreement.objects.get(member=member, is_current=True)
    mark_agreement_sent(agreement, None)
    mark_agreement_signed(agreement, None)

    response = staff_client.get(_hub_url(approved_application.guardian))
    html = response.content.decode()

    idx_ligumi = html.index(">Līgumi<")
    idx_daliba = html.index(">Dalība<")
    idx_void = html.index(">Atcelt līgumu<")
    idx_discontinue = html.index(">Pārtraukt dalību<")

    # Void sits under Līgumi, discontinue under Dalība.
    assert idx_ligumi < idx_void < idx_daliba
    assert idx_daliba < idx_discontinue
    # Discontinue is rendered after Dalība, not buried inside Līgumi.
    assert idx_discontinue > idx_daliba
    assert idx_discontinue > idx_void


def test_hub_shows_docuseal_pdf_link_when_external_id_exists(
    staff_client, approved_application,
):
    """Hub must show 'Lejupielādēt līguma PDF no DocuSeal' link when the
    agreement has an external_id (DocuSeal submission id)."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Lejupielādēt līguma PDF no DocuSeal" in html
    expected_url = reverse(
        "admin:members_guardian_docuseal_document",
        args=[guardian.pk, agreement.pk],
    )
    assert expected_url in html


def test_hub_hides_docuseal_pdf_link_without_external_id(
    staff_client, approved_application,
):
    """Hub must NOT show the DocuSeal PDF link when agreement.external_id
    is empty (no DocuSeal submission created yet)."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = ""
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Lejupielādēt līguma PDF no DocuSeal" not in html


def _make_group(name="U10 A"):
    from apps.members.models import TrainingGroup
    return TrainingGroup.objects.create(name=name, is_active=True)


def test_hub_shows_inline_group_assignment_for_member_without_group(
    staff_client, approved_application,
):
    """Member without training_group must show inline assign form with
    dropdown of active groups and a submit button."""
    group = _make_group()
    member = approved_application.approved_member
    member.training_group = None
    member.save(update_fields=["training_group"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert 'value="assign_training_group"' in html
    assert f'value="{member.pk}"' in html
    assert 'name="training_group"' in html
    assert "Piešķirt grupu" in html
    assert group.name in html


def test_hub_hides_inline_group_assignment_for_member_with_group(
    staff_client, approved_application,
):
    """Member already assigned to a group must NOT show the inline assign form."""
    group = _make_group()
    member = approved_application.approved_member
    member.training_group = group
    member.save(update_fields=["training_group"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert 'value="assign_training_group"' not in html

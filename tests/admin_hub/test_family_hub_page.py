"""P11: Family hub page rendering — lanes, kit-size, deep links."""

from __future__ import annotations

import re
from pathlib import Path

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
    """Hub must show the download link with the exact label
    'Lejupielādēt ģenerēto līgumu' when the agreement has an external_id.
    The href must be the same-origin internal document endpoint (never a
    DocuSeal URL)."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Lejupielādēt ģenerēto līgumu" in html
    expected_url = reverse(
        "admin:members_guardian_docuseal_document",
        args=[guardian.pk, agreement.pk],
    )
    assert expected_url in html
    # The rendered download anchor must request the attachment disposition.
    assert f"{expected_url}?disposition=attachment" in html


def test_hub_hides_docuseal_pdf_link_without_external_id(
    staff_client, approved_application,
):
    """Hub must NOT show the download link when agreement.external_id
    is empty (no DocuSeal submission created yet)."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = ""
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Lejupielādēt ģenerēto līgumu" not in html


def test_hub_lists_download_links_for_every_agreement_with_external_id(
    staff_client, approved_application,
):
    """The hub must list a download link for every agreement on the member
    with a nonempty external_id, including history states (generated/sent/
    signed/void/superseded/discontinued)."""
    from django.utils import timezone

    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    current = Agreement.objects.get(member=member, is_current=True)
    current.external_id = "cur-1"
    current.save(update_fields=["external_id", "updated_at"])

    history = Agreement.objects.create(
        member=member,
        is_current=False,
        state=Agreement.State.SUPERSEDED,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        generated_at=timezone.now(),
        external_id="hist-1",
    )

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Lejupielādēt ģenerēto līgumu" in html
    assert reverse(
        "admin:members_guardian_docuseal_document", args=[guardian.pk, current.pk]
    ) in html
    assert reverse(
        "admin:members_guardian_docuseal_document", args=[guardian.pk, history.pk]
    ) in html


def test_hub_does_not_leak_docuseal_document_url(
    staff_client, approved_application,
):
    """No rendered hub HTML may contain the DocuSeal document URL — the
    download must go through the same-origin proxy endpoint."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = "1001"
    agreement.external_url = "https://sign.example/s/abc"
    agreement.save(update_fields=["external_id", "external_url", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "https://sign.example" not in html
    assert "sign.example" not in html
    # Retired label must be gone too.
    assert "Lejupielādēt līguma PDF no DocuSeal" not in html


def test_hub_no_leaked_multiline_django_comment_text(
    staff_client, approved_application,
):
    """Multi-line Django `{# #}` comments leak their literal body into the
    rendered page (Django `{# #}` is single-line only). The shared
    agreement-list partial prose must never appear in the hub HTML."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.external_id = "1001"
    agreement.save(update_fields=["external_id", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert "Document list — every non-empty-external-id agreement" not in html
    assert "Shared app-neutral partial" not in html


@pytest.mark.parametrize(
    "state, label",
    [
        ("generated", "Sagatavots"),
        ("sent", "Nosūtīts parakstīšanai"),
        ("signed", "Parakstīts"),
        ("void", "Atcelts"),
        ("superseded", "Aizvietots"),
        ("discontinued", "Pārtraukts"),
    ],
)
def test_hub_renders_history_state_label_and_download_link(
    staff_client, approved_application, state, label,
):
    """For each agreement state, the hub must render the exact state display
    and the corresponding same-origin download endpoint for a history row."""
    from django.utils import timezone

    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    current = Agreement.objects.get(member=member, is_current=True)
    current.external_id = "cur-1"
    current.save(update_fields=["external_id", "updated_at"])

    history = Agreement.objects.create(
        member=member,
        is_current=False,
        state=state,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        generated_at=timezone.now(),
        external_id="hist-1",
    )

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    assert label in html
    assert reverse(
        "admin:members_guardian_docuseal_document", args=[guardian.pk, history.pk]
    ) in html


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


# ---------------------------------------------------------------------------
# Anchor contract — child card DOM ids and return_anchor hidden fields.
# ---------------------------------------------------------------------------


def test_hub_renders_application_child_anchor_and_return_field(
    staff_client, submitted_application,
):
    """Each child card must carry a stable id based on its source application,
    and every POST form inside that card must submit a matching return_anchor.
    For a submitted application, the template renders approve, request_fix,
    and reject forms — all three must carry the anchor."""
    guardian = submitted_application.guardian
    action_url = reverse(
        "admin:members_guardian_family_hub_action", args=[guardian.pk]
    )
    response = staff_client.get(_hub_url(guardian))

    anchor = f"child-application-{submitted_application.pk}"
    html = response.content.decode()

    # Card has the anchor id
    assert f'id="{anchor}"' in html

    # Known application controls are present
    assert 'value="approve_application"' in html
    assert 'value="request_fix"' in html
    assert 'value="reject"' in html

    # Count forms posting to the action URL and return_anchor fields
    form_count = html.count(f'action="{action_url}"')
    anchor_count = html.count(f'name="return_anchor" value="{anchor}"')

    # Sanity: at least the three application forms rendered
    assert form_count >= 3, f"Expected >=3 forms, got {form_count}"
    # Every form must have exactly one matching return_anchor
    assert anchor_count == form_count, (
        f"Expected {form_count} return_anchor fields, got {anchor_count}"
    )


def test_hub_approved_child_card_uses_source_application_anchor(
    staff_client, approved_application,
):
    """After approval the child card must keep its source-application anchor,
    not fall back to a member-based anchor. The approved_application fixture
    provides an agreement (generated state) and a member (no training_group),
    so the template renders agreement + membership controls — all must carry
    the source-application anchor."""
    source_app = approved_application
    guardian = source_app.guardian
    action_url = reverse(
        "admin:members_guardian_family_hub_action", args=[guardian.pk]
    )
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    anchor = f"child-application-{source_app.pk}"

    # Card has the anchor id
    assert f'id="{anchor}"' in html

    # Known controls are present: agreement (mark_agreement_sent, void) +
    # membership (assign_training_group)
    assert 'value="mark_agreement_sent"' in html
    assert 'value="void_agreement"' in html
    assert 'value="assign_training_group"' in html

    # Count forms posting to the action URL and return_anchor fields
    form_count = html.count(f'action="{action_url}"')
    anchor_count = html.count(f'name="return_anchor" value="{anchor}"')

    # Sanity: at least the three controls rendered
    assert form_count >= 3, f"Expected >=3 forms, got {form_count}"
    # Every form must have exactly one matching return_anchor
    assert anchor_count == form_count, (
        f"Expected {form_count} return_anchor fields, got {anchor_count}"
    )


# ---------------------------------------------------------------------------
# Static template contract — every form in family_hub.html must carry the
# return_anchor hidden field. Covers conditional branches (e.g. billing states,
# agreement states, member-with/without-group) not simultaneously rendered by
# one fixture.
# ---------------------------------------------------------------------------


def test_every_hub_form_carries_return_anchor_hidden_field():
    """Every <form method="post" action="{{ action_url }}"> in the hub template
    must include <input type="hidden" name="return_anchor" value="{{ child.anchor_id }}">.
    This contract covers all application, agreement, membership, and billing
    controls, including conditional branches not simultaneously rendered by
    one fixture."""
    template_path = (
        Path(__file__).resolve().parents[2]
        / "templates"
        / "admin"
        / "members"
        / "guardian"
        / "family_hub.html"
    )
    template_source = template_path.read_text(encoding="utf-8")

    # Match every form block: <form ... method="post" ... action="{{ action_url }}" ...>...</form>
    # The regex uses order-independent lookaheads so attribute order is irrelevant.
    form_pattern = re.compile(
        r'<form\s+(?=[^>]*method="post")'
        r'(?=[^>]*action="\{\{\s*action_url\s*\}\}")'
        r'[^>]*>.*?</form>',
        re.DOTALL,
    )
    forms = form_pattern.findall(template_source)

    assert len(forms) > 0, (
        "Expected at least one <form method=\"post\" action=\"{{ action_url }}\"> "
        "in family_hub.html"
    )

    # Every form must contain an <input> with both name="return_anchor" and
    # value="{{ child.anchor_id }}" in any attribute order.
    anchor_pattern = re.compile(
        r'<input\s+(?=[^>]*name="return_anchor")'
        r'(?=[^>]*value="\{\{\s*child\.anchor_id\s*\}\}")'
        r'[^>]*>'
    )
    missing = []
    for idx, form_html in enumerate(forms, start=1):
        if not anchor_pattern.search(form_html):
            missing.append(idx)

    assert not missing, (
        f"Forms at positions {missing} are missing the return_anchor hidden field. "
        f"Expected: name=\"return_anchor\" value=\"{{{{ child.anchor_id }}}}\". "
        f"Total forms: {len(forms)}."
    )


def test_hub_member_without_source_application_uses_member_anchor(
    staff_client,
):
    """A Member without a source_application must fall back to
    child-member-<pk> as its anchor, with matching return_anchor fields
    in rendered action forms."""
    from apps.members.models import Member
    from tests.support import make_guardian

    guardian = make_guardian(full_name="Member-Only Parent")
    member = Member.objects.create(
        full_name="Member-Only Child", guardian=guardian
    )

    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    anchor = f"child-member-{member.pk}"

    # Card id uses member fallback
    assert f'id="{anchor}"' in html

    # At least one return_anchor field carries the member anchor
    assert f'name="return_anchor" value="{anchor}"' in html

    # Inline training-group control renders so this is a real action-capable child
    assert 'value="assign_training_group"' in html


# ---------------------------------------------------------------------------
# P15 — family hub billing setup form uses native month input + required
# ---------------------------------------------------------------------------


def test_hub_billing_setup_month_input_is_native_and_required(
    staff_client, approved_application, active_plan,
):
    """The hub billing-setup form must use native type='month' input (not
    text) and mark it required so staff cannot submit blank months."""
    from apps.agreements.models import Agreement

    member = approved_application.approved_member
    agreement = Agreement.objects.get(member=member, is_current=True)
    agreement.billing_plan = None
    agreement.save(update_fields=["billing_plan", "updated_at"])

    guardian = approved_application.guardian
    response = staff_client.get(_hub_url(guardian))
    html = response.content.decode()

    # Must use native month input, not text
    assert 'type="text" name="first_billing_month"' not in html
    # Must be required
    import re
    month_input_pattern = re.compile(
        r'<input[^>]*name="first_billing_month"[^>]*type="month"[^>]*>'
    )
    match = month_input_pattern.search(html)
    assert match is not None, "Expected type='month' input for first_billing_month"
    assert 'required' in match.group(0), "Expected required attribute on month input"

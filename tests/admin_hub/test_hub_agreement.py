"""Agreement page — steps 3 to 5."""

from __future__ import annotations

import re

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def _signed_button_tags(body: str) -> list[str]:
    """Return EVERY ``<button ...>`` opening tag for ``mark_agreement_signed``.

    The page renders two — one in the step-5 card foot, one in the sticky
    action bar — each carrying its own copy of the disable condition. An
    earlier version of this helper returned the first match only, so the
    action-bar copy was asserted by nothing at all: re-adding a stale clause
    to it alone kept the whole file green. Returning both and asserting over
    all of them is what keeps the two in sync.

    A fixed-size substring window keyed off the position of the ``value``
    attribute is fragile: in the template, ``disabled`` renders *after*
    ``value="mark_agreement_signed"`` inside the same tag, so scanning
    backward from that marker (as ``marker[-300:]`` did) can never see it.
    Isolating the actual opening tag with a regex checks the real element
    instead of an arbitrary character window that happens to overlap by
    coincidence.
    """
    tags = re.findall(
        r'<button[^>]*value="mark_agreement_signed"[^>]*>', body, re.DOTALL
    )
    assert len(tags) == 2, (
        f"expected the card-foot and action-bar buttons, found {len(tags)}"
    )
    return tags


@pytest.fixture
def application_with_agreement(approved_application):
    return approved_application


def test_agreement_page_requires_staff(client, application_with_agreement):
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    response = client.get(url)
    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


def test_agreement_page_renders_all_three_step_cards(
    client, reviewer, application_with_agreement
):
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert "Līguma sagatavošana" in body
    assert "Lejupielāde un izsniegšana" in body
    assert "Parakstītais līgums" in body


def test_agreement_page_posts_mark_sent_to_the_existing_endpoint(
    client, reviewer, application_with_agreement
):
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application_with_agreement.pk],
    ) in body
    assert 'value="mark_agreement_sent"' in body


def test_mark_signed_is_enabled_without_an_uploaded_artifact(
    client, reviewer, application_with_agreement
):
    """The upload is optional, and the Hub was the only thing claiming
    otherwise.

    ``mark_agreement_signed`` never reads ``signed_artifact`` — its guards are
    state, billing plan, first billing month and plan activity. The club signs
    on paper and files the scan afterwards, so gating the transition on the
    file blocked a transition the domain permits.
    """
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])
    assert not agreement.signed_artifact, "fixture must have no artifact"
    assert agreement.billing_plan_id and agreement.first_billing_month, (
        "the approved_application fixture's default plan must already be set"
    )

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    tags = _signed_button_tags(body)
    assert all("disabled" not in tag for tag in tags)
    # The upload is still offered — demoted, not removed.
    assert 'name="signed_artifact"' in body
    assert "neobligāti" in body


def test_mark_signed_is_disabled_without_a_billing_plan(
    client, reviewer, application_with_agreement
):
    """The signed transition materialises the BillingRecord from the
    agreement's plan, so step 6 must be done before step 5 can complete."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(
        update_fields=["state", "sent_at", "billing_plan", "first_billing_month"]
    )

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert "Vispirms norādiet maksas plānu" in body
    tags = _signed_button_tags(body)
    assert all("disabled" in tag for tag in tags)


def test_mark_signed_is_disabled_with_artifact_but_no_billing_plan(
    client, reviewer, application_with_agreement
):
    """The artifact is present and only the billing plan is missing, so the
    disabled state cannot be explained by the artifact.

    This mattered more when the artifact was also a gate; it is kept because
    it still pins the direction of the remaining rule — a template that
    stopped reading ``has_billing_plan`` would pass the sibling tests, which
    all leave the artifact absent too."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.signed_artifact.save(
        "signed.pdf", ContentFile(b"%PDF-1.7"), save=False
    )
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(
        update_fields=[
            "state",
            "sent_at",
            "signed_artifact",
            "billing_plan",
            "first_billing_month",
        ]
    )

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    tags = _signed_button_tags(body)
    assert all("disabled" in tag for tag in tags)


def test_mark_signed_is_enabled_with_a_plan_and_an_artifact(
    client, reviewer, application_with_agreement
):
    """Complements the disabled-state tests above: without an enabled case, a
    bug that always renders `disabled` would pass all of them silently."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.signed_artifact.save(
        "signed.pdf", ContentFile(b"%PDF-1.7"), save=False
    )
    agreement.save(update_fields=["state", "sent_at", "signed_artifact"])
    assert agreement.billing_plan_id and agreement.first_billing_month, (
        "the approved_application fixture's default plan must already be set"
    )

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    tags = _signed_button_tags(body)
    assert all("disabled" not in tag for tag in tags)


def test_page_shows_the_lifecycle_timeline(
    client, reviewer, application_with_agreement
):
    """Render a real event's label — asserting only the static "Vēsture"
    heading would pass even with an empty history (the template's `{% empty
    %}` branch renders "Nav notikumu" under that same heading), so it would
    not catch a view that forgot to query `lifecycle_events` at all."""
    from apps.agreements.models import AgreementLifecycleEvent

    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    AgreementLifecycleEvent.objects.create(
        agreement=agreement,
        event_type=AgreementLifecycleEvent.EventType.DISCONTINUED,
        actor_label="hub_reviewer",
    )

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    assert "Vēsture" in body
    assert "Dalība pārtraukta" in body
    assert "Nav notikumu" not in body


def test_page_404s_when_the_application_has_no_member(
    client, reviewer, submitted_application
):
    """A submitted application has no agreement to show."""
    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[submitted_application.pk])
    response = client.get(url)
    assert response.status_code == 404


def test_agreement_page_offers_the_plan_form_before_signing(
    client, reviewer, application_with_agreement
):
    """Step 6's plan is a *precondition* of step 5, so the reviewer must be
    able to set it without leaving the agreement page.

    P9 and P15 in ``mark_agreement_signed`` require the plan and the first
    billing month before the state will move, while invoices (step 7) require
    the signing that produces the record — which forced a round trip to step 6
    and back for every agreement. The form posts the same ``set_billing_setup``
    action the billing page uses, so there is one endpoint and one set of
    validations."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()

    assert 'name="billing_plan"' in body
    assert 'name="first_billing_month"' in body
    assert 'value="set_billing_setup"' in body
    # Posting to the existing admin endpoint, not to a Hub-owned route.
    # Read off THIS form: the agreement page has five other forms already
    # posting to that URL, so a whole-body substring check would hold even
    # if the plan form posted somewhere else entirely.
    action, _payload = _plan_form(body)
    assert action == reverse(
        "admin:registrations_registrationapplication_review-action",
        args=[application_with_agreement.pk],
    )
    # The consequence of the current selection is visible before signing.
    assert "Aprēķinātais grafiks" in body


def test_agreement_page_shows_the_plan_read_only_once_signed(
    client, reviewer, application_with_agreement
):
    """After signing the plan stops being an intent on the agreement and
    becomes the BillingRecord's own data — ``set_billing_setup`` refuses it.

    An editable-looking select whose submit is refused is worse than no
    control, so the value renders read-only and points at step 6, which owns
    reassignment. The plan must still be *shown*: asserting only the select's
    absence would pass on a card that rendered nothing at all."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    plan_name = agreement.billing_plan.name
    agreement.state = agreement.State.SIGNED
    agreement.sent_at = timezone.now()
    agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at", "signed_at"])

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()

    assert 'name="billing_plan"' not in body
    assert 'value="set_billing_setup"' not in body
    # ...but the plan itself is still on the page, as a value.
    assert plan_name in body
    # The step-6 pointer, matched as an actual anchor carrying that label —
    # the bare URL is on every render of this page (step rail, action bar,
    # and the mark-signed form's hidden `next`), so a substring check would
    # survive deleting the link this test is named for.
    billing_url = reverse("admin_hub:billing", args=[application_with_agreement.pk])
    assert re.search(
        rf'<a[^>]*href="{re.escape(billing_url)}"[^>]*>[^<]*Mainīt 6\. solī',
        body,
    ), "the read-only plan must point at step 6, which owns reassignment"


def _plan_form(body: str) -> tuple[str, dict[str, str]]:
    """Extract the step-5 plan form's action and a ready-to-POST payload.

    Deliberately driven from the rendered HTML rather than from field names
    written out again in the test: a payload typed into the test passes even
    if the template posts entirely different names to an entirely different
    endpoint, which is the failure mode that matters here — the whole point of
    the change is that *this form* reaches the existing action."""
    match = re.search(
        r"<form[^>]*>(?:(?!</form>).)*?set_billing_setup(?:(?!</form>).)*?</form>",
        body,
        re.DOTALL,
    )
    assert match is not None, "step-5 plan form must be present"
    form = match.group(0)
    action = re.search(r'action="([^"]+)"', form)
    assert action is not None, "plan form must post somewhere"

    select = re.search(r'<select[^>]*name="([^"]+)"', form)
    assert select is not None, "plan form must offer a plan select"
    option = re.search(r'<option value="(\d+)"', form)
    assert option is not None, "plan select must list at least one active plan"
    month = re.search(r'<input[^>]*type="month"[^>]*name="([^"]+)"', form)
    assert month is not None, "plan form must offer a first-billing-month input"
    submit = re.search(r'<button[^>]*name="([^"]+)"[^>]*value="set_billing_setup"', form)
    assert submit is not None, "plan form must submit the action by name"

    return action.group(1), {
        submit.group(1): "set_billing_setup",
        select.group(1): option.group(1),
        month.group(1): "",
    }


def test_plan_then_sign_completes_without_leaving_the_agreement_page(
    client, acting_reviewer, application_with_agreement
):
    """End-to-end proof that the round trip is gone.

    Previously: signing needed a plan that only step 6 could set, and step 7's
    invoices needed the record that only signing creates — so the reviewer went
    agreement page -> billing page -> agreement page -> billing page for every
    application. Both POSTs now originate from the agreement page and land back
    on it, so step 6 is reached once, already signed.

    The plan POST is built from the page's own markup, so this fails if the
    form stops reaching the real endpoint — not merely if the endpoint itself
    regresses."""
    from apps.agreements.models import Agreement
    from apps.billing.services import derive_first_billing_month
    from apps.billing.models import BillingRecord, MembershipPlan

    member = application_with_agreement.approved_member
    agreement = member.agreements.get(is_current=True)
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.billing_plan = None
    agreement.first_billing_month = ""
    agreement.save(
        update_fields=["state", "sent_at", "billing_plan", "first_billing_month"]
    )
    assert not agreement.signed_artifact, "no artifact is uploaded anywhere below"

    hub_url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    client.force_login(acting_reviewer)

    action_url, payload = _plan_form(client.get(hub_url).content.decode())
    plan = MembershipPlan.objects.get(pk=int(payload[
        next(k for k, v in payload.items() if v.isdigit())
    ]))
    # Derived, never a literal: set_billing_setup refuses a month below
    # derive_first_billing_month(plan), which moves with today's date and the
    # plan's cutoff day. A hardcoded "2026-09" passes today and starts failing
    # on 2026-09-21.
    payload[next(k for k, v in payload.items() if v == "")] = (
        derive_first_billing_month(plan)
    )
    payload["next"] = hub_url

    set_plan = client.post(action_url, payload)
    assert set_plan.status_code == 302
    assert set_plan["Location"] == hub_url
    agreement.refresh_from_db()
    assert agreement.billing_plan_id == plan.pk, (
        "the rendered form must actually set the plan"
    )

    sign = client.post(
        action_url,
        {"action": "mark_agreement_signed", "next": hub_url},
    )
    assert sign.status_code == 302

    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SIGNED, (
        "signing must succeed with no artifact uploaded and no visit to step 6"
    )
    # Signing materialised the record, so step 7 is now reachable.
    assert BillingRecord.objects.filter(member=member).exists()


@pytest.mark.parametrize(
    ("state", "plan_editable", "sign_offered"),
    [
        ("generated", True, True),
        ("sent", True, True),
        ("signed", False, False),
        ("superseded", False, False),
        ("discontinued", False, False),
        ("void", True, False),
    ],
)
def test_step_five_controls_match_the_services_own_state_guards(
    client, reviewer, application_with_agreement, state, plan_editable, sign_offered
):
    """Every agreement state, against both endpoints' real guards.

    Two separate state sets meet on this card and neither is the other:

    * ``set_billing_setup`` refuses SIGNED / SUPERSEDED / DISCONTINUED, so the
      plan is editable in the other three — VOID included, which the domain
      does permit.
    * ``mark_agreement_signed`` accepts only GENERATED and SENT, so the sign
      button is offered in two states, not four.

    Both were previously covered for SIGNED alone. That let a real regression
    through: with the signed-artifact clause dropped from the disable
    condition, the sign button rendered enabled on an already-signed
    agreement, and pressing it surfaced the raw English "cannot mark signed
    from state signed" in a Latvian UI. It also left ``_billing_is_locked``'s
    three-state tuple unpinned — narrowing it to ``(SIGNED,)`` broke nothing.
    """
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = state
    agreement.sent_at = timezone.now()
    if state == "signed":
        agreement.signed_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at", "signed_at"])
    assert agreement.billing_plan_id and agreement.first_billing_month, (
        "the plan must be set, so the plan is never what disables the button"
    )

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    ).content.decode()

    assert ('name="billing_plan"' in body) is plan_editable
    # The read-only rendering is the alternative, not an empty card.
    if not plan_editable:
        assert agreement.billing_plan.name in body
    for tag in _signed_button_tags(body):
        assert ("disabled" in tag) is not sign_offered


def test_no_schedule_is_shown_while_the_first_billing_month_is_blank(
    client, reviewer, application_with_agreement
):
    """A plan without a month must not render a grid of concrete deadlines.

    ``derive_installment_schedule`` falls back to the plan's own
    ``first_installment_month`` and the season start year when the month is
    blank, so the card would otherwise show real-looking dates immediately
    above the warning saying the month is still required — for a signing that
    P15 refuses outright. Neither page tested this branch: only the
    no-plan-at-all case was covered."""
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.first_billing_month = ""
    agreement.save(update_fields=["state", "sent_at", "first_billing_month"])
    assert agreement.billing_plan_id, "the plan stays set; only the month is blank"

    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    ).content.decode()

    assert "Aprēķinātais grafiks" not in body
    assert "schedrow" not in body
    # The hint takes its place, so this is not an empty card.
    assert "Izvēlieties plānu un pirmo mēnesi" in body
    # ...and signing is still refused, for the month rather than the plan.
    for tag in _signed_button_tags(body):
        assert "disabled" in tag

"""Agreement page — steps 3 to 5."""

from __future__ import annotations

import re

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def _signed_button_tag(body: str) -> str:
    """Return the exact ``<button ...>`` opening tag for
    ``mark_agreement_signed``.

    A fixed-size substring window keyed off the position of the ``value``
    attribute is fragile: in the template, ``disabled`` renders *after*
    ``value="mark_agreement_signed"`` inside the same tag, so scanning
    backward from that marker (as ``marker[-300:]`` did) can never see it.
    Isolating the actual opening tag with a regex checks the real element
    instead of an arbitrary character window that happens to overlap by
    coincidence.
    """
    match = re.search(
        r'<button[^>]*value="mark_agreement_signed"[^>]*>', body, re.DOTALL
    )
    assert match is not None, "mark_agreement_signed button must be present"
    return match.group(0)


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


def test_mark_signed_is_disabled_without_an_uploaded_artifact(
    client, reviewer, application_with_agreement
):
    agreement = application_with_agreement.approved_member.agreements.get(
        is_current=True
    )
    agreement.state = agreement.State.SENT
    agreement.sent_at = timezone.now()
    agreement.save(update_fields=["state", "sent_at"])

    client.force_login(reviewer)
    url = reverse("admin_hub:agreement", args=[application_with_agreement.pk])
    body = client.get(url).content.decode()
    tag = _signed_button_tag(body)
    assert "disabled" in tag, (
        "without a signed artifact the transition must not be offered"
    )


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
    tag = _signed_button_tag(body)
    assert "disabled" in tag


def test_mark_signed_is_disabled_with_artifact_but_no_billing_plan(
    client, reviewer, application_with_agreement
):
    """The discriminating case. Both tests above leave the *other*
    precondition false too (no artifact by default in one; no artifact set
    in the other), so either alone is satisfied by a template that only
    checks `not has_signed_artifact` and never looks at the billing plan at
    all. This is the one scenario where the artifact IS present and only
    the billing plan is missing — the only test that would fail if
    `or not has_billing_plan` were dropped from the button's disable
    condition."""
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
    tag = _signed_button_tag(body)
    assert "disabled" in tag


def test_mark_signed_is_enabled_once_both_preconditions_are_met(
    client, reviewer, application_with_agreement
):
    """Complements the two disabled-state tests above: without this, a bug
    that always renders `disabled` regardless of state would pass both of
    them silently."""
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
    tag = _signed_button_tag(body)
    assert "disabled" not in tag


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

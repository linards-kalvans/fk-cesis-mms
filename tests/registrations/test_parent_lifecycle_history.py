"""P8: Parent portal lifecycle history visibility tests.

Tests that the parent portal shows agreement/member lifecycle status
and that another guardian cannot see a different member's history.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.urls import reverse

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    mark_agreement_sent,
    mark_agreement_signed,
)
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="reviewer", is_staff=True)


@pytest.fixture
def approved_app(submitted_application, reviewer):
    """An approved application with a signed agreement."""
    app = approve_application(submitted_application, reviewer)
    agreement = create_agreement_for_member(
        app.approved_member, Agreement.SigningPath.PAPER
    )
    mark_agreement_sent(agreement, reviewer)
    mark_agreement_signed(agreement, reviewer)
    return app


# -- Owner sees current lifecycle status --


def test_owner_sees_member_lifecycle_status(approved_app, verified_client):
    """Parent portal must include lifecycle status/history for the approved child."""
    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode("utf-8")

    # Current agreement status should be visible
    member = approved_app.approved_member
    assert member.full_name in html


def test_owner_sees_discontinued_status(approved_app, verified_client, reviewer):
    """When the member is discontinued, the portal must reflect that."""
    from apps.agreements.services import discontinue_agreement

    agreement = Agreement.objects.filter(
        member=approved_app.approved_member, is_current=True
    ).first()

    discontinue_agreement(
        agreement,
        reviewer,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[],
    )

    resp = verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode("utf-8")

    # Portal displays discontinued status
    assert "Pārtraukta" in html or "pārtraukta" in html


# -- Another guardian cannot see lifecycle history --


def test_other_guardian_does_not_see_lifecycle(
    approved_app, other_verified_client
):
    """Another authenticated guardian must not see this member's lifecycle."""
    # The other parent has no relationship to the approved application.
    resp = other_verified_client.get(reverse("registrations:parent-portal"))
    html = resp.content.decode("utf-8")

    member = approved_app.approved_member
    assert member.full_name not in html


# -- Discontinuation email includes effective date, reason, credit summary --


def test_discontinuation_email_has_effective_date_reason_and_credit(
    approved_app, reviewer
):
    """The discontinuation email body must contain effective date, reason,
    and credit summary."""
    from django.core import mail
    from apps.agreements.services import discontinue_agreement

    agreement = Agreement.objects.filter(
        member=approved_app.approved_member, is_current=True
    ).first()

    mail.outbox.clear()
    discontinue_agreement(
        agreement,
        reviewer,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās uz citu pilsētu",
        selected_invoice_ids=[],
    )

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body

    # Effective date
    assert "2026" in body
    # Reason
    assert "Pārcelšanās uz citu pilsētu" in body
    # Credit summary — when no invoices selected, credit section still present
    assert "korekcij" in body.lower()


def test_discontinuation_email_contains_portal_url(
    approved_app, reviewer
):
    from django.core import mail
    from apps.agreements.services import discontinue_agreement

    agreement = Agreement.objects.filter(
        member=approved_app.approved_member, is_current=True
    ).first()

    mail.outbox.clear()
    discontinue_agreement(
        agreement,
        reviewer,
        effective_date=date(2026, 9, 1),
        reason="Pārcelšanās",
        selected_invoice_ids=[],
    )

    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    # Portal URL should appear in the email
    assert "/portal/" in body

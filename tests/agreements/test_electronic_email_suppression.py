"""Electronic path suppresses sent/signed emails; void always sends; paper
sends on all transitions (P5 Slice D)."""

from __future__ import annotations

import pytest
from django.core import mail
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import (
    mark_agreement_signed,
    void_agreement,
)


pytestmark = pytest.mark.django_db


def _agreement(member, path, state=Agreement.State.GENERATED, plan=None):
    return Agreement.objects.create(
        member=member,
        signing_path=path,
        state=state,
        generated_at=timezone.now(),
        billing_plan=plan,
        first_billing_month="2026-09" if plan is not None else "",
    )


def test_electronic_signed_suppresses_email(agreement_member, actor, default_plan):
    a = _agreement(
        agreement_member, Agreement.SigningPath.ELECTRONIC, plan=default_plan
    )
    mail.outbox.clear()
    mark_agreement_signed(a, actor)
    assert len(mail.outbox) == 0


def test_electronic_void_still_emails(agreement_member, actor):
    a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mail.outbox.clear()
    void_agreement(a, actor, "duplicate")
    assert len(mail.outbox) == 1


def test_paper_signed_emails(agreement_member, actor, default_plan):
    a = _agreement(
        agreement_member, Agreement.SigningPath.PAPER, plan=default_plan
    )
    mail.outbox.clear()
    mark_agreement_signed(a, actor)
    assert len(mail.outbox) == 1

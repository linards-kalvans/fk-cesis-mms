"""Mark-sent enqueues a DocuSeal submission for both paths — DocuSeal
emails the guardian only on the electronic path; empty guardian email
falls back to paper; void archives electronic submissions (P5 Slice D)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_sent, void_agreement


pytestmark = pytest.mark.django_db


def _agreement(member, path):
    return Agreement.objects.create(
        member=member,
        signing_path=path,
        state=Agreement.State.GENERATED,
        generated_at=timezone.now(),
    )


def test_electronic_mark_sent_enqueues_create(agreement_member, actor):
    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as spy:
        a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
        mark_agreement_sent(a, actor)
    a.refresh_from_db()
    assert a.state == Agreement.State.SENT
    spy.assert_called_once_with(a.id, send_email=True)


def test_paper_mark_sent_enqueues_create_without_email(agreement_member, actor):
    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as spy:
        a = _agreement(agreement_member, Agreement.SigningPath.PAPER)
        mark_agreement_sent(a, actor)
    spy.assert_called_once_with(a.id, send_email=False)


def test_electronic_no_email_falls_back_to_paper(agreement_member, actor):
    agreement_member.guardian.parent_account.email = ""
    agreement_member.guardian.parent_account.save(update_fields=["email"])
    with patch(
        "apps.integrations.tasks.enqueue_create_agreement_submission"
    ) as spy:
        a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
        mark_agreement_sent(a, actor)
    a.refresh_from_db()
    assert a.signing_path == Agreement.SigningPath.PAPER
    spy.assert_called_once_with(a.id, send_email=False)


def test_electronic_void_enqueues_archive(agreement_member, actor):
    with patch(
        "apps.integrations.tasks.enqueue_archive_agreement_submission"
    ) as spy:
        a = _agreement(agreement_member, Agreement.SigningPath.ELECTRONIC)
        a.external_id = "ds-1"
        a.state = Agreement.State.SENT
        a.save(update_fields=["external_id", "state"])
        void_agreement(a, actor, "duplicate")
    spy.assert_called_once_with("ds-1")


def test_paper_void_does_not_enqueue_archive(agreement_member, actor):
    with patch(
        "apps.integrations.tasks.enqueue_archive_agreement_submission"
    ) as spy:
        a = _agreement(agreement_member, Agreement.SigningPath.PAPER)
        a.state = Agreement.State.SENT
        a.save(update_fields=["state"])
        void_agreement(a, actor, "duplicate")
    spy.assert_not_called()

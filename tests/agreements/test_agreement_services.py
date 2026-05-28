"""Tests for apps.agreements.services."""

from __future__ import annotations

import pytest
from django.core import mail
from django.db import connection
from django.test.utils import CaptureQueriesContext, override_settings

from apps.agreements.models import Agreement
from apps.agreements.services import (
    create_agreement_for_member,
    get_current_agreement,
    mark_agreement_sent,
    mark_agreement_signed,
    regenerate_agreement,
    set_signing_path,
    void_agreement,
)


pytestmark = pytest.mark.django_db


# --- get_current_agreement ---


def test_get_current_returns_none_when_no_agreement(agreement_member):
    assert get_current_agreement(agreement_member) is None


def test_get_current_returns_only_current_row(agreement_member):
    current = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    # Hand-create an archived row (no service path produces this yet)
    Agreement.objects.create(
        member=agreement_member,
        is_current=False,
        state=Agreement.State.VOID,
        generated_at=current.generated_at,
        voided_at=current.generated_at,
    )
    assert get_current_agreement(agreement_member).id == current.id


# --- create_agreement_for_member ---


def test_create_creates_with_state_generated(agreement_member):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    assert a.state == Agreement.State.GENERATED
    assert a.signing_path == Agreement.SigningPath.ELECTRONIC
    assert a.is_current is True


def test_create_is_idempotent_when_current_is_non_void(agreement_member):
    first = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    second = create_agreement_for_member(agreement_member, Agreement.SigningPath.PAPER)
    assert first.id == second.id
    assert Agreement.objects.filter(member=agreement_member).count() == 1


def test_create_after_void_archives_and_creates_fresh(agreement_member, actor):
    first = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    void_agreement(first, actor, "test reason")
    fresh = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    assert fresh.id != first.id
    first.refresh_from_db()
    assert first.is_current is False
    assert first.state == Agreement.State.VOID
    assert fresh.is_current is True
    assert fresh.state == Agreement.State.GENERATED
    assert Agreement.objects.filter(member=agreement_member).count() == 2


# --- regenerate_agreement ---


def test_regenerate_on_void_succeeds(agreement_member, actor):
    first = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    void_agreement(first, actor, "reason")
    fresh = regenerate_agreement(agreement_member, Agreement.SigningPath.PAPER, actor)
    assert fresh.state == Agreement.State.GENERATED
    assert fresh.signing_path == Agreement.SigningPath.PAPER
    first.refresh_from_db()
    assert first.is_current is False


def test_regenerate_on_non_void_raises_value_error(agreement_member, actor):
    create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    with pytest.raises(ValueError, match="active agreement cannot be replaced"):
        regenerate_agreement(agreement_member, Agreement.SigningPath.PAPER, actor)


def test_regenerate_without_existing_agreement_raises_value_error(agreement_member, actor):
    with pytest.raises(ValueError, match="no agreement exists to regenerate"):
        regenerate_agreement(agreement_member, Agreement.SigningPath.PAPER, actor)


# --- mark_agreement_sent ---


def test_mark_sent_from_generated_succeeds_and_sends_email(
    agreement_member, agreement_guardian, actor
):
    mail.outbox.clear()
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_sent(a, actor)
    a.refresh_from_db()
    assert a.state == Agreement.State.SENT
    assert a.sent_at is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [agreement_guardian.email]
    assert mail.outbox[0].subject == "Jūsu līgums ir nosūtīts parakstīšanai"
    assert "nosūtīts parakstīšanai" in mail.outbox[0].body


def test_mark_signed_email_subject_is_latvian(agreement_member, actor):
    mail.outbox.clear()
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_signed(a, actor)
    assert mail.outbox[0].subject == "Jūsu līgums ir parakstīts"


@pytest.mark.parametrize(
    "from_state",
    [Agreement.State.SENT, Agreement.State.SIGNED, Agreement.State.VOID],
)
def test_mark_sent_from_illegal_states_raises(agreement_member, actor, from_state):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.state = from_state
    a.save(update_fields=["state"])
    with pytest.raises(ValueError):
        mark_agreement_sent(a, actor)


# --- mark_agreement_signed ---


def test_mark_signed_from_generated_succeeds_and_sends_email(agreement_member, actor):
    mail.outbox.clear()
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_signed(a, actor)
    a.refresh_from_db()
    assert a.state == Agreement.State.SIGNED
    assert a.signed_at is not None
    assert len(mail.outbox) == 1
    assert "parakstīts" in mail.outbox[0].body


def test_mark_signed_from_sent_succeeds_and_sends_email(agreement_member, actor):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_sent(a, actor)
    mail.outbox.clear()
    mark_agreement_signed(a, actor)
    a.refresh_from_db()
    assert a.state == Agreement.State.SIGNED
    assert len(mail.outbox) == 1


@pytest.mark.parametrize(
    "from_state",
    [Agreement.State.SIGNED, Agreement.State.VOID],
)
def test_mark_signed_from_illegal_states_raises(agreement_member, actor, from_state):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    a.state = from_state
    a.save(update_fields=["state"])
    with pytest.raises(ValueError):
        mark_agreement_signed(a, actor)


# --- void_agreement ---


def test_void_from_generated_succeeds_no_email(agreement_member, actor):
    mail.outbox.clear()
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    void_agreement(a, actor, "test reason")
    a.refresh_from_db()
    assert a.state == Agreement.State.VOID
    assert a.voided_at is not None
    assert a.void_reason == "test reason"
    assert a.is_current is True  # keeps is_current until regenerate
    assert mail.outbox == []


def test_void_from_void_is_idempotent_no_update(agreement_member, actor):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    void_agreement(a, actor, "reason")
    with CaptureQueriesContext(connection) as ctx:
        void_agreement(a, actor, "another reason")
    update_queries = [q for q in ctx.captured_queries if "UPDATE" in q["sql"].upper()]
    assert update_queries == []
    a.refresh_from_db()
    assert a.void_reason == "reason"  # unchanged


# --- set_signing_path ---


def test_set_signing_path_changes_value_no_email(agreement_member, actor):
    mail.outbox.clear()
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    set_signing_path(a, Agreement.SigningPath.PAPER, actor)
    a.refresh_from_db()
    assert a.signing_path == Agreement.SigningPath.PAPER
    assert mail.outbox == []


def test_set_signing_path_same_value_is_idempotent(agreement_member, actor):
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    with CaptureQueriesContext(connection) as ctx:
        set_signing_path(a, Agreement.SigningPath.ELECTRONIC, actor)
    update_queries = [q for q in ctx.captured_queries if "UPDATE" in q["sql"].upper()]
    assert update_queries == []


def test_set_signing_path_allowed_when_signed(agreement_member, actor):
    """User explicitly chose 'override at any state' — verify signed allows it."""
    a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
    mark_agreement_signed(a, actor)
    set_signing_path(a, Agreement.SigningPath.PAPER, actor)
    a.refresh_from_db()
    assert a.signing_path == Agreement.SigningPath.PAPER


# --- email body uses SITE_URL ---


def test_sent_email_body_includes_portal_url_from_settings(agreement_member, actor):
    mail.outbox.clear()
    with override_settings(SITE_URL="https://test.example"):
        a = create_agreement_for_member(agreement_member, Agreement.SigningPath.ELECTRONIC)
        mark_agreement_sent(a, actor)
    assert "https://test.example" in mail.outbox[0].body

"""record_audit_event — fail-safe explicit audit recording."""

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from apps.core.audit import record_audit_event
from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_records_system_event_with_label():
    e = record_audit_event(
        action=AuditEvent.Action.INVOICE_PUSH_FAILED,
        actor_label="system: push_billing_record",
        metadata={"error_code": "unavailable"},
    )
    assert e is not None
    assert e.actor is None
    assert e.actor_label == "system: push_billing_record"
    assert e.metadata == {"error_code": "unavailable"}


def test_derives_target_from_instance_and_actor_label_from_user():
    user = User.objects.create_user(username="staff", email="s@example.com")
    plan = User.objects.create_user(username="x")  # any model with a pk/str works as a stand-in
    e = record_audit_event(action=AuditEvent.Action.APPLICATION_APPROVED, actor=user, target=plan)
    assert e.actor == user
    assert e.actor_label == "s@example.com"  # email preferred, else username
    assert e.target_type == "user"
    assert e.target_id == str(plan.pk)
    assert e.target_repr == str(plan)


def test_extracts_ip_and_user_agent_from_request():
    rf = RequestFactory()
    req = rf.get("/x", HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1", HTTP_USER_AGENT="UA/1.0")
    e = record_audit_event(action=AuditEvent.Action.DOCUMENT_DOWNLOADED, request=req)
    assert e.ip_address == "203.0.113.9"
    assert e.user_agent == "UA/1.0"


def test_uses_request_user_when_actor_unset():
    rf = RequestFactory()
    user = User.objects.create_user(username="staff2", email="s2@example.com")
    req = rf.get("/x")
    req.user = user
    e = record_audit_event(action=AuditEvent.Action.DOCUMENT_PREVIEWED, request=req)
    assert e.actor == user


def test_never_raises_on_write_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(AuditEvent.objects, "create", boom)
    result = record_audit_event(action=AuditEvent.Action.APPLICATION_APPROVED)
    assert result is None

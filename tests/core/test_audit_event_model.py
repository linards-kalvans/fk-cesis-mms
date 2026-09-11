"""AuditEvent model — append-only audit row."""

import pytest

from apps.core.models import AuditEvent

pytestmark = pytest.mark.django_db


def test_minimal_event_defaults():
    e = AuditEvent.objects.create(action=AuditEvent.Action.APPLICATION_APPROVED)
    e.refresh_from_db()
    assert e.actor is None
    assert e.actor_label == ""
    assert e.metadata == {}
    assert e.ip_address is None
    assert e.user_agent == ""
    assert e.created_at is not None


def test_action_choices_include_catalog():
    values = set(AuditEvent.Action.values)
    assert {
        "application_approved",
        "application_rejected",
        "application_fix_requested",
        "training_group_assigned",
        "training_group_cleared",
        "document_previewed",
        "document_downloaded",
        "document_deleted",
        "agreement_sent",
        "agreement_signed",
        "agreement_voided",
        "agreement_sync_failed",
        "billing_push_triggered",
        "payment_sync_triggered",
        "invoice_push_failed",
        "invoice_send_failed",
        "payment_sync_failed",
    } <= values


def test_default_ordering_newest_first():
    import datetime

    from django.utils import timezone

    a = AuditEvent.objects.create(action=AuditEvent.Action.DOCUMENT_DOWNLOADED)
    b = AuditEvent.objects.create(action=AuditEvent.Action.DOCUMENT_PREVIEWED)
    # Force distinct timestamps so ordering is deterministic (auto_now_add can tie
    # on fast SQLite runs, leaving -created_at order undefined).
    now = timezone.now()
    AuditEvent.objects.filter(pk=a.pk).update(created_at=now - datetime.timedelta(minutes=1))
    AuditEvent.objects.filter(pk=b.pk).update(created_at=now)
    assert list(AuditEvent.objects.all()) == [b, a]


def test_no_updated_at_field():
    field_names = {f.name for f in AuditEvent._meta.get_fields()}
    assert "updated_at" not in field_names


def test_data_exported_action_exists():
    assert "data_exported" in set(AuditEvent.Action.values)


def test_member_export_audit_actions_exist():
    assert AuditEvent.Action.MEMBER_EXPORT_TEMPLATE_MUTATED == "member_export_template_mutated"
    assert AuditEvent.Action.MEMBER_EXPORT_RUN == "member_export_run"
    values = set(AuditEvent.Action.values)
    assert "member_export_template_mutated" in values
    assert "member_export_run" in values

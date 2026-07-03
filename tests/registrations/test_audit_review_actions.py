"""Review actions emit AuditEvents."""

import pytest
from django.contrib.auth.models import User

from apps.core.models import AuditEvent
from apps.registrations.models import RegistrationApplication
from apps.registrations.services import (
    approve_application,
    reject_application,
    request_application_fix,
)

pytestmark = pytest.mark.django_db


def _submitted_app():
    return RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED,
        member_full_name="Bērns",
    )


def test_reject_emits_audit_event():
    reviewer = User.objects.create_user(username="rev", email="rev@example.com")
    app = _submitted_app()
    reject_application(app, reviewer, "trūkst dokumenta")
    e = AuditEvent.objects.get(action=AuditEvent.Action.APPLICATION_REJECTED)
    assert e.actor == reviewer
    assert e.target_type == "registrationapplication"
    assert e.target_id == str(app.pk)


def test_request_fix_emits_audit_event():
    reviewer = User.objects.create_user(username="rev2", email="rev2@example.com")
    app = _submitted_app()
    request_application_fix(app, reviewer, "labo adresi")
    e = AuditEvent.objects.get(action=AuditEvent.Action.APPLICATION_FIX_REQUESTED)
    assert e.actor == reviewer
    assert e.target_type == "registrationapplication"
    assert e.target_id == str(app.pk)


def test_approve_emits_audit_event(submitted_application):
    # Uses the conftest `submitted_application` fixture (fully documented + submitted)
    # so the real approval flow runs end-to-end.
    reviewer = User.objects.create_user(username="rev3", email="rev3@example.com")
    approve_application(submitted_application, reviewer)
    e = AuditEvent.objects.get(action=AuditEvent.Action.APPLICATION_APPROVED)
    assert e.actor == reviewer
    assert e.target_type == "registrationapplication"
    assert e.target_id == str(submitted_application.pk)

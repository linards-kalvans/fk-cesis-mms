"""In-place field correction from the Admin Hub cockpit.

The cockpit's readout is the surface a reviewer compares against the uploaded
document, so it stays read-only — but a typo in a surname should not require
leaving the Hub for Django admin. These cover the endpoint that makes that
possible, and the three decisions behind it: the e-mail is not editable,
every edit is audited, and an edit after approval must reach the Member row
too or a regenerated agreement would rebuild from the stale snapshot.
"""

from __future__ import annotations

import datetime

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view]


def _edit_url(application):
    return reverse(
        "admin:registrations_registrationapplication_edit-fields",
        args=[application.pk],
    )


@pytest.fixture
def editor(db):
    """A superuser: the endpoint requires has_change_permission, which the
    Hub's own is_staff-only decorator does not imply."""
    from django.contrib.auth.models import User

    return User.objects.create_superuser(
        username="editor", email="editor@example.lv", password="x"
    )


def test_corrects_a_member_typo(client, editor, submitted_application):
    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application),
        {"member_full_name": "Jānis Kalējs-Bērziņš"},
    )
    assert response.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.member_full_name == "Jānis Kalējs-Bērziņš"


def test_corrects_a_guardian_typo(client, editor, submitted_application):
    client.force_login(editor)
    client.post(_edit_url(submitted_application), {"family_name": "Bērziņa-Ozola"})
    submitted_application.guardian.refresh_from_db()
    assert submitted_application.guardian.family_name == "Bērziņa-Ozola"


def test_rejects_a_malformed_personal_id_and_writes_nothing(
    client, editor, submitted_application
):
    """Validation reuses the same rule the parent-facing form applies, so the
    two cannot drift apart on what a valid personal id is."""
    before = submitted_application.member_full_name
    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application),
        {"member_personal_id": "not-a-code", "member_full_name": "Changed Too"},
    )
    assert response.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.member_personal_id != "not-a-code"
    # The valid field in the same submission must not have landed either:
    # a rejected edit writes nothing at all.
    assert submitted_application.member_full_name == before


def test_the_email_is_not_editable(client, editor, submitted_application):
    """A non-null parent_account IS the proof the address is reachable, and
    the cockpit says so. Rewriting it here would make that claim false."""
    original = submitted_application.guardian_contact_email
    client.force_login(editor)
    client.post(
        _edit_url(submitted_application),
        {"guardian_email": "attacker@example.com", "email": "attacker@example.com"},
    )
    submitted_application.refresh_from_db()
    assert submitted_application.guardian_contact_email == original


def test_records_an_audit_event_naming_the_fields_but_not_the_values(
    client, editor, submitted_application
):
    from apps.core.models import AuditEvent

    client.force_login(editor)
    client.post(
        _edit_url(submitted_application), {"member_full_name": "Pēteris Liepa"}
    )
    event = AuditEvent.objects.filter(
        action=str(AuditEvent.Action.APPLICATION_DATA_EDITED),
        target_id=str(submitted_application.pk),
    ).latest("created_at")
    assert "member_full_name" in event.metadata["fields"]
    # The values are personal data and must not be in the audit trail.
    assert "Pēteris Liepa" not in str(event.metadata)


def test_an_unchanged_submission_records_no_audit_event(
    client, editor, submitted_application
):
    from apps.core.models import AuditEvent

    client.force_login(editor)
    client.post(
        _edit_url(submitted_application),
        {"member_full_name": submitted_application.member_full_name},
    )
    assert not AuditEvent.objects.filter(
        action=str(AuditEvent.Action.APPLICATION_DATA_EDITED),
        target_id=str(submitted_application.pk),
    ).exists()


def test_an_edit_after_approval_reaches_the_member_row(
    client, editor, approved_application
):
    """The decisive case for editing after approval. Approval copies the
    child's data onto a Member, and agreement generation reads the Member —
    so without this mirroring, correcting a name and regenerating the
    agreement would rebuild it from the old name and appear to do nothing."""
    member = approved_application.approved_member
    assert member is not None

    client.force_login(editor)
    client.post(
        _edit_url(approved_application),
        {
            "member_full_name": "Labotais Vārds",
            "member_birth_date": "2015-03-14",
        },
    )

    approved_application.refresh_from_db()
    member.refresh_from_db()
    assert approved_application.member_full_name == "Labotais Vārds"
    assert member.full_name == "Labotais Vārds", (
        "the Member snapshot did not receive the correction"
    )
    assert member.birth_date == datetime.date(2015, 3, 14)


def test_get_is_refused(client, editor, submitted_application):
    """Django does not CSRF-protect GET, and this writes personal data."""
    before = submitted_application.member_full_name
    client.force_login(editor)
    response = client.get(
        _edit_url(submitted_application), {"member_full_name": "Via GET"}
    )
    assert response.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.member_full_name == before


def test_staff_without_change_permission_is_refused(
    client, django_user_model, submitted_application
):
    """The Hub's own views require only is_staff. Putting the mutation on the
    admin means it inherits the stronger bar every other action uses."""
    plain_staff = django_user_model.objects.create_user(
        username="viewer_only", password="x", is_staff=True
    )
    before = submitted_application.member_full_name
    client.force_login(plain_staff)
    response = client.post(
        _edit_url(submitted_application), {"member_full_name": "Not Allowed"}
    )
    assert response.status_code in (302, 403)
    submitted_application.refresh_from_db()
    assert submitted_application.member_full_name == before


def test_cockpit_offers_the_edit_panel(client, reviewer, submitted_application):
    client.force_login(reviewer)
    body = client.get(
        reverse("admin_hub:cockpit", args=[submitted_application.pk])
    ).content.decode()
    assert "Labot datus" in body
    assert _edit_url(submitted_application) in body
    # the e-mail must not appear as an editable input
    assert 'name="guardian_email"' not in body

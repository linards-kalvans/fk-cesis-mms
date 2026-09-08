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


def test_corrects_a_phone_number_via_the_parent_account(
    client, editor, submitted_application
):
    """Guardian.phone (apps/members/models.py) is a read-only @property
    proxying ParentAccount.phone — it has no setter. The correction must
    write through to parent_account.phone, not to the Guardian row, or the
    endpoint raises AttributeError the first time a reviewer edits it."""
    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application), {"phone": "+37129998888"}
    )
    assert response.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.guardian_contact_phone == "+37129998888"
    submitted_application.parent_account.refresh_from_db()
    assert submitted_application.parent_account.phone == "+37129998888"


def test_a_phone_edit_with_no_linked_parent_account_writes_nothing_and_does_not_raise(
    client, editor, submitted_application, parent_account
):
    """A draft application may have no parent_account, and the raw Django
    admin change form can also produce this directly (neither `guardian`
    nor `parent_account` is readonly or excluded there): a staff user can
    set `guardian` while leaving `parent_account` blank. The endpoint must
    neither crash nor silently claim a change was made."""
    submitted_application.parent_account = None
    submitted_application.save(update_fields=["parent_account"])
    # The fixture's in-memory `parent_account` predates the draft-save that
    # copied guardian_phone onto it, so read the real current value fresh.
    parent_account.refresh_from_db()
    before_phone = parent_account.phone

    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application), {"phone": "+37166600000"}
    )
    assert response.status_code == 302

    from django.contrib.messages import get_messages

    texts = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("nav piesaistīts vecāka konts" in text for text in texts)

    parent_account.refresh_from_db()
    assert parent_account.phone == before_phone


def test_a_phone_edit_with_a_guardian_application_account_mismatch_writes_nothing(
    client, editor, submitted_application, other_parent_account
):
    """guardian.phone (apps/members/models.py) is displayed to the reviewer
    via the Guardian's OWN parent_account, but a correction is written onto
    application.parent_account — two independently-nullable FKs that
    nothing enforces agree. The raw Django admin change form can point them
    at different accounts directly. A correction must never land on an
    account the reviewer was not looking at, so this must be refused rather
    than silently written to either side."""
    guardian_account = submitted_application.guardian.parent_account
    before_guardian_account_phone = guardian_account.phone
    before_other_account_phone = other_parent_account.phone

    submitted_application.parent_account = other_parent_account
    submitted_application.save(update_fields=["parent_account"])

    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application), {"phone": "+37177700000"}
    )
    assert response.status_code == 302

    from django.contrib.messages import get_messages

    texts = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("konti nesakrīt" in text for text in texts)

    guardian_account.refresh_from_db()
    other_parent_account.refresh_from_db()
    assert guardian_account.phone == before_guardian_account_phone
    # The account this write would actually target — the one a naive fix
    # (compare to guardian.phone, always write to application.parent_account)
    # would have silently overwritten.
    assert other_parent_account.phone == before_other_account_phone


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


def test_an_out_of_range_date_gets_the_latvian_message_not_the_raw_exception(
    client, editor, submitted_application
):
    """Django's parse_date raises ValueError itself for a string shaped like
    a date but with an out-of-range component (e.g. month 13), rather than
    returning None — bypassing the `if parsed is None` check and leaking the
    raw internal message to the reviewer instead of the Latvian one."""
    before = submitted_application.member_birth_date
    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application), {"member_birth_date": "2015-13-45"}
    )
    assert response.status_code == 302
    from django.contrib.messages import get_messages

    texts = [str(m) for m in get_messages(response.wsgi_request)]
    assert any("GGGG-MM-DD" in text for text in texts)
    assert not any("must be in 1..12" in text for text in texts)
    submitted_application.refresh_from_db()
    assert submitted_application.member_birth_date == before


def test_a_blank_required_field_is_rejected_and_writes_nothing(
    client, editor, submitted_application
):
    """member_full_name was mandatory at submission
    (RegistrationApplicationForm.submit_required_fields); a reviewer clearing
    it must be rejected like a malformed personal id, not silently accepted.
    The valid field in the same submission must not land either."""
    before_name = submitted_application.member_full_name
    before_address = submitted_application.member_actual_address
    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application),
        {"member_full_name": "", "member_actual_address": "Jauna adrese 5"},
    )
    assert response.status_code == 302
    submitted_application.refresh_from_db()
    assert submitted_application.member_full_name == before_name
    assert submitted_application.member_actual_address == before_address


def test_a_blank_name_on_an_approved_application_does_not_reach_the_member(
    client, editor, approved_application
):
    """The case that motivated the fix: a blank mirrors onto the Member,
    which apps.integrations.docuseal reads verbatim into the agreement
    payload, so an accidentally cleared name would silently blank a
    regenerated legal agreement."""
    member = approved_application.approved_member
    before_member_name = member.full_name

    client.force_login(editor)
    client.post(_edit_url(approved_application), {"member_full_name": ""})

    approved_application.refresh_from_db()
    member.refresh_from_db()
    assert approved_application.member_full_name != ""
    assert member.full_name == before_member_name


def test_an_edit_after_approval_mirrors_personal_id_onto_the_member(
    client, editor, approved_application
):
    """Only full_name and birth_date were covered before; a typo in the
    personal_id entry of _MEMBER_MIRRORED_FIELDS would have gone unnoticed."""
    member = approved_application.approved_member

    client.force_login(editor)
    client.post(
        _edit_url(approved_application),
        {"member_personal_id": "020202-23456"},
    )

    approved_application.refresh_from_db()
    member.refresh_from_db()
    assert approved_application.member_personal_id == "020202-23456"
    assert member.personal_id == "020202-23456"


def test_an_invalid_guardian_field_writes_nothing_even_when_an_application_field_was_valid(
    client, editor, submitted_application
):
    """Both loops (application, then guardian) finish collecting changes
    before the transaction opens — so an invalid guardian field must still
    block an already-collected, valid application field from the same
    request. Untested from this direction before."""
    before_name = submitted_application.member_full_name
    before_family_name = submitted_application.guardian.family_name

    client.force_login(editor)
    response = client.post(
        _edit_url(submitted_application),
        {"member_full_name": "Changed Name", "personal_id": "not-a-code"},
    )

    assert response.status_code == 302
    submitted_application.refresh_from_db()
    submitted_application.guardian.refresh_from_db()
    assert submitted_application.member_full_name == before_name
    assert submitted_application.guardian.family_name == before_family_name


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
    """Checks the WHOLE row, not just metadata: record_audit_event auto-fills
    target_repr from str(target) when a caller omits it, and
    RegistrationApplication.__str__ returns
    "{guardian_email} — {member_full_name}" — exactly the values this test's
    own name claims are excluded. A version of this test that inspects only
    metadata would pass even if target_repr leaked both."""
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
    assert event.target_repr == f"pieteikums #{submitted_application.pk}"
    assert "@" not in event.target_repr
    assert "Pēteris Liepa" not in event.target_repr


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
    # RegistrationApplicationAdmin does not override has_change_permission,
    # so a refusal is always 403 — a (302, 403) tolerance here would mask a
    # change in how refusal gets signalled.
    assert response.status_code == 403
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

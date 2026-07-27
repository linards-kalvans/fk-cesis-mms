"""P11: Guardian changelist — action-needed column + ordering."""

from __future__ import annotations

import pytest
from django.urls import reverse

from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def _changelist_url():
    return reverse("admin:members_guardian_changelist")


def test_changelist_has_next_action_column(staff_client, submitted_application):
    """Guardian changelist must render a dedicated Latvian column header for
    missing / next action. Expected label: 'Nākamā darbība'."""
    response = staff_client.get(_changelist_url())
    html = response.content.decode()
    assert response.status_code == 200
    assert "Nākamā darbība" in html


def test_changelist_orders_action_needed_before_no_action(
    staff_client, db,
):
    """Guardian with a submitted application (action needed) must appear
    before a Guardian with no action needed in the changelist HTML.

    The idle guardian is created first (lower pk) so default pk ordering
    would put it first; the test fails unless the changelist reorders by
    action needed.
    """
    from apps.registrations.services import create_or_update_draft, submit_application
    from apps.documents.models import Document
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.accounts.models import ParentAccount

    # Idle guardian created FIRST (lower pk).
    idle_guardian = make_guardian(full_name="Idle Guardian")

    # Action-needed guardian created SECOND (higher pk).
    action_account = ParentAccount.objects.create(email="action-parent@example.test")
    action_guardian = make_guardian(account=action_account, full_name="Action Guardian")

    # Build a submitted application for the action guardian.
    png = SimpleUploadedFile("id.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", content_type="image/png")
    app = create_or_update_draft(
        data={"guardian_email": action_account.email},
        files={},
        verified_account=action_account,
    )
    shirt_pk = None
    from apps.members.models import KitSizeOption
    shirt, _ = KitSizeOption.objects.get_or_create(kind=KitSizeOption.Kind.SHIRT, label="S", defaults={"is_active": True})
    shirt_pk = shirt.pk
    Document.objects.create(application=app, kind=Document.Kind.GUARDIAN_IDENTITY, file=png, original_filename="id.png", content_type="image/png", file_size=16)
    Document.objects.create(application=app, kind=Document.Kind.MEMBER_IDENTITY, file=png, original_filename="id.png", content_type="image/png", file_size=16)
    Document.objects.create(application=app, kind=Document.Kind.MEMBER_PORTRAIT, file=png, original_filename="id.png", content_type="image/png", file_size=16)
    payload = {
        "guardian_first_name": "Action",
        "guardian_family_name": "Guardian",
        "guardian_personal_id": "010101-99999",
        "guardian_email": action_account.email,
        "guardian_phone": "+37120000001",
        "guardian_declared_address": "Riga, Testa 1",
        "member_full_name": "Action Child",
        "member_personal_id": "010125-88888",
        "member_birth_date": "2025-01-01",
        "member_same_address_as_guardian": True,
        "member_kit_size_shirt": shirt_pk,
        "preferred_agreement_signing": "paper",
    }
    app = create_or_update_draft(data=payload, files={}, application=app, verified_account=action_account)
    submit_application(app, action_account)

    response = staff_client.get(_changelist_url())
    html = response.content.decode()

    # Search within the changelist <tbody> — raw pk values (e.g. "1", "2")
    # also appear in CSS URLs and CSRF tokens well before the table, which
    # makes a full-page find unreliable.
    tbody_start = html.find("<tbody>")
    tbody_end = html.find("</tbody>", tbody_start)
    assert tbody_start != -1 and tbody_end != -1, "changelist <tbody> not found"
    table = html[tbody_start:tbody_end]

    idx_action = table.find(str(action_guardian.pk))
    idx_idle = table.find(str(idle_guardian.pk))
    assert idx_action != -1, "action-needed guardian not found in changelist"
    assert idx_idle != -1, "idle guardian not found in changelist"
    assert idx_action < idx_idle, (
        f"action-needed guardian (pk={action_guardian.pk}) must appear before "
        f"idle guardian (pk={idle_guardian.pk}) in the changelist"
    )


def test_changelist_next_action_column_shows_apstiprinat_for_submitted(
    staff_client, submitted_application,
):
    """The next-action column must show 'Apstiprināt' for a family with a
    submitted application."""
    response = staff_client.get(_changelist_url())
    html = response.content.decode()
    assert "Apstiprināt" in html

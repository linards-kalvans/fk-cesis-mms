"""P11: Family action queue — pure helper + URL tests."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_queue_rows_include_submitted_application_needing_review(
    submitted_application,
):
    """A submitted application must appear in the action-needed queue."""
    from apps.members.family_hub import build_family_queue_rows

    guardian = submitted_application.guardian
    rows = build_family_queue_rows()

    matching = [row for row in rows if row["guardian"].pk == guardian.pk]
    assert matching, "submitted application family missing from queue"
    assert matching[0]["needs_action"] is True
    assert any(s.key == "application" for s in matching[0]["statuses"])


def test_queue_rows_exclude_draft_only_family(draft_application):
    """A family with only a draft application must NOT appear in the queue."""
    from apps.members.family_hub import build_family_queue_rows

    guardian = draft_application.guardian
    rows = build_family_queue_rows()

    guardian_pks = {row["guardian"].pk for row in rows}
    assert guardian.pk not in guardian_pks


def test_queue_orders_submitted_before_billing_sync(
    submitted_application, billing_record_factory,
):
    """Submitted application (high urgency) must appear before a synced billing
    record (low urgency) in the queue."""
    from apps.billing.models import BillingRecord
    from apps.members.family_hub import build_family_queue_rows

    urgent_guardian = submitted_application.guardian

    # Create a separate family with a synced billing record (low urgency)
    from tests.support import make_guardian as _make_guardian
    from apps.accounts.models import ParentAccount
    from apps.members.models import Member

    other_account = ParentAccount.objects.create(email="billing-family@example.com")
    other_guardian = _make_guardian(account=other_account, full_name="Billing Parent")
    other_member = Member.objects.create(full_name="Billing Child", guardian=other_guardian)
    billing_record_factory(
        other_member,
        status=BillingRecord.Status.CONFIRMED,
        external_status="synced",
    )

    rows = build_family_queue_rows()
    guardian_pks = [row["guardian"].pk for row in rows]

    assert urgent_guardian.pk in guardian_pks
    assert other_guardian.pk in guardian_pks
    assert guardian_pks.index(urgent_guardian.pk) < guardian_pks.index(other_guardian.pk)


def test_staff_can_access_queue_url(staff_client):
    """Staff user can open the family queue page."""
    url = reverse("admin:members_guardian_family_queue")
    response = staff_client.get(url)
    assert response.status_code == 200


def test_anonymous_cannot_access_queue_url(client):
    """Anonymous user is redirected or forbidden from the queue."""
    url = reverse("admin:members_guardian_family_queue")
    response = client.get(url)
    assert response.status_code in (302, 403)


def test_queue_row_renders_lane_indicators_with_badge_and_icon(
    staff_client, submitted_application,
):
    """Queue row must render lane indicators as icon + .fk-badge + next action,
    not raw numeric urgency only."""
    url = reverse("admin:members_guardian_family_queue")
    response = staff_client.get(url)
    html = response.content.decode()

    assert response.status_code == 200
    # A .fk-badge with one of the existing level classes is present.
    assert 'class="fk-badge fk-badge--pending"' in html or 'fk-badge--pending' in html
    # The submitted application's badge label "Iesniegts" is rendered.
    assert "Iesniegts" in html
    # Next-action copy from the lane is rendered.
    assert "Apstiprināt" in html
    # The numeric urgency column is no longer the only lane signal — confirm the
    # table header is the lanes column, not a "Steidzamība" numeric column.
    assert "Steidzamība" not in html

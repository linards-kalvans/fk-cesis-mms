"""Sync-health badge + filter on the agreements admin.

Only the agreement-specific filter wiring (failed/ok/none bucket behaviour) is
covered here. The generic badge/filter/sidebar pattern is the same as the
billing/core helpers and is exercised there.
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member

from tests.support import make_guardian

pytestmark = [pytest.mark.django_db, pytest.mark.admin_view, pytest.mark.slow]


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _agreement(name, **kw):
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name=name, guardian=g)
    return Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT,
        generated_at=timezone.now(), **kw,
    )


@pytest.mark.parametrize(
    ("filter_value", "expected", "excluded"),
    [
        # failed: external_error_code set, regardless of external_state
        ("failed", "Fail", ["Clean", "Fresh"]),
        # ok: external_state set, external_error_code empty
        ("ok", "Clean", ["Fail", "Fresh"]),
        # none: both empty
        ("none", "Fresh", ["Fail", "Clean"]),
    ],
)
def test_sync_health_filter_isolates_bucket(filter_value, expected, excluded):
    _agreement("Fail", external_state="failed", external_error_code="provider_error")
    _agreement("Clean", external_state="created", external_error_code="")
    _agreement("Fresh", external_state="", external_error_code="")
    c = _staff_client()
    url = reverse("admin:agreements_agreement_changelist") + f"?sync_health={filter_value}"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert expected in body
    for name in excluded:
        assert name not in body

"""Changelist shows status-aware quick actions."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member

from tests.support import make_guardian
from apps.registrations.models import RegistrationApplication

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def test_changelist_renders_open_link_and_agreement_quick_action():
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.GENERATED, generated_at=timezone.now()
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Atvērt" in html
    assert "Atzīmēt nosūtītu" in html  # generated -> mark-sent quick action
    # A bare formaction button (NOT a nested <form>, which the browser drops):
    # rides the changelist's POST form + CSRF; the action rides the query string.
    action_url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    assert f'formaction="{action_url}?action=mark_agreement_sent"' in html
    assert 'formmethod="post"' in html
    assert f'<form method="post" action="{action_url}"' not in html  # old nested form gone


def test_changelist_quick_action_post_executes_transition():
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.GENERATED, generated_at=timezone.now()
    )
    c = _staff_client()
    action_url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(action_url, {"action": "mark_agreement_sent"})
    assert resp.status_code == 302
    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SENT


def test_changelist_quick_action_executes_via_query_string_action():
    # The quick-action button rides the changelist form (empty body `action`
    # from the bulk-action select) and passes the action via the query string.
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name="B", guardian=g)
    app = RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.APPROVED, member_full_name="B", approved_member=m
    )
    agreement = Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.GENERATED, generated_at=timezone.now()
    )
    c = _staff_client()
    action_url = reverse("admin:registrations_registrationapplication_review-action", args=[app.pk])
    resp = c.post(action_url + "?action=mark_agreement_sent", {"action": ""})  # empty body select
    assert resp.status_code == 302
    agreement.refresh_from_db()
    assert agreement.state == Agreement.State.SENT


def test_changelist_open_link_without_agreement():
    RegistrationApplication.objects.create(
        status=RegistrationApplication.Status.SUBMITTED, member_full_name="X"
    )
    c = _staff_client()
    html = c.get(reverse("admin:registrations_registrationapplication_changelist")).content.decode()
    assert "Atvērt" in html
    assert "Atzīmēt nosūtītu" not in html  # no agreement -> no agreement quick action

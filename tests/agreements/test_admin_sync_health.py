"""Sync-health badge + filter on the agreements admin."""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement
from apps.members.models import Member

from tests.support import make_guardian

pytestmark = pytest.mark.django_db


def _staff_client():
    User.objects.create_superuser("staff", "s@example.com", "pw")
    c = Client()
    c.login(username="staff", password="pw")
    return c


def _agreement(**kw):
    g = make_guardian(full_name="V")
    m = Member.objects.create(full_name=kw.pop("name", "Bērns"), guardian=g)
    return Agreement.objects.create(
        member=m, is_current=True, state=Agreement.State.SENT,
        generated_at=timezone.now(), **kw,
    )


def test_failed_sync_shows_fail_badge():
    from apps.agreements.messages import get_agreement_error_message

    _agreement(external_state="failed", external_error_code="provider_error", name="Fail")
    c = _staff_client()
    html = c.get(reverse("admin:agreements_agreement_changelist")).content.decode()
    assert "fk-badge--fail" in html
    assert f'title="{get_agreement_error_message("provider_error")}"' in html


def test_sync_health_filter_isolates_failed():
    _agreement(external_state="failed", external_error_code="provider_error", name="Fail")
    _agreement(name="Clean")
    c = _staff_client()
    url = reverse("admin:agreements_agreement_changelist") + "?sync_health=failed"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Fail" in body
    assert "Clean" not in body


def test_sync_health_filter_ok_excludes_errored():
    _agreement(external_state="completed", name="Clean")
    _agreement(external_state="completed", external_error_code="provider_error", name="Tainted")
    c = _staff_client()
    url = reverse("admin:agreements_agreement_changelist") + "?sync_health=ok"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Clean" in body
    assert "Tainted" not in body


def test_sync_health_filter_none_excludes_errored():
    _agreement(external_state="", name="Untouched")
    _agreement(external_state="", external_error_code="provider_error", name="Errored")
    c = _staff_client()
    url = reverse("admin:agreements_agreement_changelist") + "?sync_health=none"
    body = c.get(url).content.decode().split("</thead>")[-1]
    assert "Untouched" in body
    assert "Errored" not in body


def test_filter_rendered_in_sidebar():
    _agreement(name="Any")
    c = _staff_client()
    html = c.get(reverse("admin:agreements_agreement_changelist")).content.decode()
    assert "sync_health" in html

"""Līgums module DocuSeal UI: error surface, retry, sync, external link.

Ported to the admin change page + review-action endpoint (P7 C-i).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.agreements.services import get_current_agreement
from apps.registrations.services import approve_application


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewer(db):
    from django.contrib.auth.models import User

    return User.objects.create_user(username="staff", is_staff=True, is_superuser=True)


def _change_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_change", args=[app_id]
    )


def _action_url(app_id):
    return reverse(
        "admin:registrations_registrationapplication_review-action", args=[app_id]
    )


def _approved_agreement(submitted_application, reviewer, **fields):
    approve_application(submitted_application, reviewer)
    agreement = get_current_agreement(submitted_application.approved_member)
    for k, v in fields.items():
        setattr(agreement, k, v)
    if fields:
        agreement.save(update_fields=list(fields))
    return agreement


def test_failed_state_renders_latvian_error_and_retry(
    client, submitted_application, reviewer
):
    _approved_agreement(
        submitted_application,
        reviewer,
        external_state="failed",
        external_error_code="auth_failed",
    )
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "DocuSeal autentifikācija neizdevās" in html
    assert 'value="retry_docuseal"' in html


def test_external_url_renders_open_link(client, submitted_application, reviewer):
    _approved_agreement(
        submitted_application,
        reviewer,
        external_id="ds-1",
        external_url="https://sign.example/s/abc",
    )
    client.force_login(reviewer)
    resp = client.get(_change_url(submitted_application.id))
    html = resp.content.decode()
    assert "https://sign.example/s/abc" in html
    assert 'value="sync_docuseal"' in html


def test_retry_action_re_enqueues_create(
    client, submitted_application, reviewer
):
    agreement = _approved_agreement(
        submitted_application,
        reviewer,
        external_state="failed",
        external_error_code="unavailable",
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_create_agreement_submission"
    ) as spy:
        client.post(
            _action_url(submitted_application.id),
            {"action": "retry_docuseal"},
        )
    spy.assert_called_once_with(agreement.id)


def test_retry_action_rejected_when_not_failed(
    client, submitted_application, reviewer
):
    _approved_agreement(
        submitted_application, reviewer, external_state="pending"
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_create_agreement_submission"
    ) as spy:
        resp = client.post(
            _action_url(submitted_application.id),
            {"action": "retry_docuseal"},
            follow=True,
        )
    assert "Atkārtot var tikai neizdevušos sūtījumu." in resp.content.decode()
    spy.assert_not_called()


def test_sync_action_enqueues_sync(client, submitted_application, reviewer):
    agreement = _approved_agreement(
        submitted_application, reviewer, external_id="ds-1"
    )
    client.force_login(reviewer)
    with patch(
        "apps.registrations.admin.enqueue_sync_agreement_submission"
    ) as spy:
        client.post(
            _action_url(submitted_application.id),
            {"action": "sync_docuseal"},
        )
    spy.assert_called_once_with(agreement.id)

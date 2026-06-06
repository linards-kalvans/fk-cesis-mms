"""DocuSeal webhook: HMAC-verified submission.completed drives signed."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.agreements.models import Agreement


pytestmark = pytest.mark.django_db


@pytest.fixture
def webhook_settings(settings):
    settings.AGREEMENT_PROVIDER_MODE = "docuseal"
    settings.DOCUSEAL_WEBHOOK_SECRET = "whsecret"
    return settings


@pytest.fixture
def sent_electronic(agreement_member):
    return Agreement.objects.create(
        member=agreement_member,
        signing_path=Agreement.SigningPath.ELECTRONIC,
        state=Agreement.State.SENT,
        external_id="ds-100",
        generated_at=timezone.now(),
    )


def _sign(body: bytes, secret: str = "whsecret", ts: int | None = None) -> str:
    """Build an ``X-Docuseal-Signature`` header: ``timestamp.hexdigest`` where
    the digest is HMAC-SHA256 over ``timestamp.raw_body`` (DocuSeal's scheme)."""
    if ts is None:
        ts = int(time.time())
    signed = f"{ts}".encode() + b"." + body
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"{ts}.{digest}"


def _post(client, payload: dict, signature: str | None):
    body = json.dumps(payload).encode()
    headers = {}
    if signature is not None:
        headers["HTTP_X_DOCUSEAL_SIGNATURE"] = signature
    return client.post(
        reverse("agreements:docuseal-webhook"),
        data=body,
        content_type="application/json",
        **headers,
    )


def test_valid_completed_drives_signed(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SIGNED


def test_bad_signature_rejected(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    resp = _post(client, payload, "deadbeef")
    assert resp.status_code == 403
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SENT


def test_stale_timestamp_rejected(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    stale = int(time.time()) - 400  # outside the 5-minute tolerance
    resp = _post(client, payload, _sign(body, ts=stale))
    assert resp.status_code == 403
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SENT


def test_wrong_event_is_noop_200(client, webhook_settings, sent_electronic):
    payload = {"event_type": "submission.viewed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200
    sent_electronic.refresh_from_db()
    assert sent_electronic.state == Agreement.State.SENT


def test_unknown_external_id_is_noop_200(client, webhook_settings):
    payload = {"event_type": "submission.completed", "data": {"id": "ghost"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200


def test_already_signed_is_idempotent_200(client, webhook_settings, sent_electronic):
    sent_electronic.state = Agreement.State.SIGNED
    sent_electronic.signed_at = timezone.now()
    sent_electronic.save(update_fields=["state", "signed_at"])
    payload = {"event_type": "submission.completed", "data": {"id": "ds-100"}}
    body = json.dumps(payload).encode()
    resp = _post(client, payload, _sign(body))
    assert resp.status_code == 200


def test_get_not_allowed(client, webhook_settings):
    resp = client.get(reverse("agreements:docuseal-webhook"))
    assert resp.status_code == 405

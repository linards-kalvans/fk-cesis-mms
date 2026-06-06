"""DocuSeal self-hosted provider — HTTP transport, HMAC verify, field maps.

Raises the boundary exception taxonomy from
apps.integrations.agreement_platform directly (no second mapping layer).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

import requests
from django.conf import settings

from apps.integrations.agreement_platform import (
    AgreementPlatformAuthError,
    AgreementPlatformConfigError,
    AgreementPlatformNotFoundError,
    AgreementPlatformTransientError,
    SubmissionResult,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


def _require_config() -> tuple[str, str, int]:
    api_url = getattr(settings, "DOCUSEAL_API_URL", "")
    api_key = getattr(settings, "DOCUSEAL_API_KEY", "")
    template_id = getattr(settings, "DOCUSEAL_TEMPLATE_ID", "")
    if not api_url or not api_key:
        raise AgreementPlatformConfigError("DocuSeal API URL/key not configured")
    try:
        template_int = int(template_id)
    except (TypeError, ValueError) as exc:
        raise AgreementPlatformConfigError(
            f"DOCUSEAL_TEMPLATE_ID is not an integer: {template_id!r}"
        ) from exc
    return api_url.rstrip("/"), api_key, template_int


def _build_submitter(agreement) -> dict:
    # No `role` key: the template defines its own submitter role name, and
    # DocuSeal rejects a mismatching role once `values` are supplied. Omitting
    # it lets DocuSeal map our single submitter onto the template's role.
    guardian = agreement.member.guardian
    return {
        "email": guardian.email,
        "name": guardian.full_name,
    }


def _build_field_payload(agreement) -> dict:
    # agreement_date is intentionally omitted: the DocuSeal template
    # auto-fills the current date on that field, so we must not send it.
    member = agreement.member
    guardian = member.guardian
    return {
        "child_name": member.full_name,
        "child_personal_id": member.personal_id,
        "child_birth_date": (
            member.birth_date.isoformat() if member.birth_date else ""
        ),
        "guardian_name": guardian.full_name,
        "guardian_personal_id": guardian.personal_id,
        "guardian_address": guardian.address,
        "email": guardian.email,
        "phone": guardian.phone,
    }


def _normalize_state(raw: str) -> str:
    if raw == "completed":
        return "completed"
    if raw in {"archived", "expired"}:
        return "archived"
    return "pending"


def _submission_url(api_url: str, payload: dict) -> str:
    submitters = payload.get("submitters") or []
    if submitters and submitters[0].get("slug"):
        return f"{api_url}/s/{submitters[0]['slug']}"
    return str(payload.get("url", ""))


def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    headers = {"X-Auth-Token": api_key, **kwargs.pop("headers", {})}
    try:
        resp = requests.request(
            method, url, headers=headers, timeout=_TIMEOUT, **kwargs
        )
    except requests.Timeout as exc:
        raise AgreementPlatformTransientError(f"timeout: {exc}") from exc
    except requests.RequestException as exc:
        raise AgreementPlatformTransientError(f"connection error: {exc}") from exc

    status = resp.status_code
    if status in (401, 403):
        raise AgreementPlatformAuthError(f"auth failed: {status}")
    if status == 404:
        raise AgreementPlatformNotFoundError(f"not found: {url}")
    if status >= 500:
        raise AgreementPlatformTransientError(f"server error: {status}")
    if status >= 400:
        raise AgreementPlatformConfigError(f"request rejected: {status} {resp.text}")
    return resp


def create_submission(agreement) -> SubmissionResult:
    api_url, api_key, template_int = _require_config()
    submitter = {
        **_build_submitter(agreement),
        "values": _build_field_payload(agreement),
    }
    body = {
        "template_id": template_int,
        "submitters": [submitter],
    }
    resp = _request("POST", f"{api_url}/submissions", api_key, json=body)
    payload = resp.json()
    # DocuSeal returns an array of submitter objects, one per submitter. The
    # submission id (used for sync + webhook matching) is `submission_id`, and
    # the signing-page URL is `embed_src`.
    submitter = payload[0] if isinstance(payload, list) and payload else {}
    return SubmissionResult(
        external_id=str(submitter.get("submission_id", "")),
        external_url=str(submitter.get("embed_src", "")),
        external_state=_normalize_state(submitter.get("status", "pending")),
    )


def sync_submission(external_id: str) -> SubmissionResult:
    api_url, api_key, _ = _require_config()
    resp = _request("GET", f"{api_url}/submissions/{external_id}", api_key)
    payload = resp.json()
    return SubmissionResult(
        external_id=str(payload.get("id", external_id)),
        external_url=_submission_url(api_url, payload),
        external_state=_normalize_state(payload.get("status", "pending")),
    )


def archive_submission(external_id: str) -> None:
    api_url, api_key, _ = _require_config()
    _request("DELETE", f"{api_url}/submissions/{external_id}", api_key)


_WEBHOOK_TOLERANCE_SECONDS = 300


def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """Verify a DocuSeal ``X-Docuseal-Signature`` header.

    DocuSeal sends ``[timestamp].[signature]`` where the signature is the
    hex HMAC-SHA256 of ``[timestamp].[raw_body]``. Requests older than the
    tolerance window are rejected to blunt replay attacks.
    """
    secret = getattr(settings, "DOCUSEAL_WEBHOOK_SECRET", "")
    if not secret or not signature_header:
        return False
    timestamp, _, signature = signature_header.partition(".")
    if not timestamp or not signature:
        return False
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > _WEBHOOK_TOLERANCE_SECONDS:
        return False
    signed = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

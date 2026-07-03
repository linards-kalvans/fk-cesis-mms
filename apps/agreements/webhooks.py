"""DocuSeal webhook endpoint — HMAC-verified submission.completed → signed."""

from __future__ import annotations

import json
import logging

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.agreements.models import Agreement
from apps.agreements.services import mark_agreement_signed
from apps.integrations import agreement_platform

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def docuseal_webhook(request: HttpRequest) -> HttpResponse:
    raw = request.body
    signature = request.headers.get("X-Docuseal-Signature", "")
    if not agreement_platform.verify_webhook_signature(raw, signature):
        return HttpResponseForbidden("invalid signature")

    try:
        payload = json.loads(raw.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=200)  # ack malformed; don't trigger retries

    if payload.get("event_type") != "submission.completed":
        return HttpResponse(status=200)

    external_id = str((payload.get("data") or {}).get("id", ""))
    if not external_id:
        return HttpResponse(status=200)

    agreement = Agreement.objects.filter(external_id=external_id).first()
    if agreement is None:
        logger.info("DocuSeal webhook for unknown submission %s", external_id)
        return HttpResponse(status=200)

    if agreement.state in (Agreement.State.GENERATED, Agreement.State.SENT):
        try:
            mark_agreement_signed(agreement, actor=None)
        except ValueError:
            logger.warning(
                "DocuSeal webhook could not sign agreement %s",
                agreement.id,
                exc_info=True,
            )
    return HttpResponse(status=200)

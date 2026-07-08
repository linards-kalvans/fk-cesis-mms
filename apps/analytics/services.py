"""Analytics service layer (P10).

The single public call site is `track_event(name, props, *, request)`. It
returns None, never raises, and swallows provider failures behind a logged
warning. Milestone helpers wrap fixed event names + prop shapes so view
code cannot drift from the spec catalog.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging

from django.http import HttpRequest

from apps.analytics import providers
from apps.analytics.config import analytics_server_configured
from apps.analytics.sanitize import sanitize_event_props, sanitize_referral_code

logger = logging.getLogger(__name__)


def track_event(
    name: str,
    props: Mapping[str, object] | None = None,
    *,
    request: HttpRequest | None = None,
) -> None:
    if not analytics_server_configured():
        return
    clean_props = sanitize_event_props(props)
    try:
        providers.send_event(name, clean_props, request=request)
    except Exception:
        logger.warning(
            "analytics_event_failed", extra={"event_name": name}, exc_info=True
        )


def track_registration_start(
    request: HttpRequest | None, *, referral_code: object = ""
) -> None:
    track_event(
        "registration_start",
        {
            "page_area": "registration",
            "event_source": "new_application",
            "referral_code": sanitize_referral_code(referral_code),
        },
        request=request,
    )


def track_email_verified(
    request: HttpRequest | None, *, referral_code: object = ""
) -> None:
    track_event(
        "email_verified",
        {
            "page_area": "registration",
            "event_source": "email_verification",
            "referral_code": sanitize_referral_code(referral_code),
        },
        request=request,
    )


def track_application_submitted(
    request: HttpRequest | None,
    *,
    referral_code: object = "",
    application_status: object = "submitted",
) -> None:
    track_event(
        "application_submitted",
        {
            "page_area": "application",
            "event_source": "submit",
            "application_status": application_status,
            "referral_code": sanitize_referral_code(referral_code),
        },
        request=request,
    )

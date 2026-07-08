"""Analytics provider adapters (P10).

The boundary mirrors the OCR / DocuSeal / Invoice Ninja adapters in this
repo: one module exposes a `send_event(name, props, *, request)` function,
dispatching on `settings.ANALYTICS_PROVIDER`. Today only `stub` (no-op) and
`plausible`/`umami` are supported; an unknown provider is a silent no-op so a
typo in the env cannot crash a request.

Provider failures must be swallowed by the caller (`services.track_event`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.http import HttpRequest
import requests

from apps.analytics.config import (
    analytics_api_url,
    analytics_domain,
    analytics_provider,
    analytics_site_id,
)


def send_event(
    name: str,
    props: Mapping[str, str],
    *,
    request: HttpRequest | None = None,
) -> None:
    provider = analytics_provider()
    if provider == "plausible":
        _send_plausible_event(name, props, request=request)
    elif provider == "umami":
        _send_umami_event(name, props, request=request)


def _send_plausible_event(
    name: str,
    props: Mapping[str, str],
    *,
    request: HttpRequest | None = None,
) -> None:
    api_url = analytics_api_url()
    domain = analytics_domain()
    if not api_url or not domain:
        return

    url = f"{api_url}/api/event"
    page_url = "/"
    if request is not None:
        page_url = request.build_absolute_uri(request.path)

    user_agent = "FK-Cesis-MMS"
    if request is not None:
        user_agent = request.META.get("HTTP_USER_AGENT", user_agent) or user_agent

    payload: dict[str, Any] = {
        "name": name,
        "domain": domain,
        "url": page_url,
    }
    if props:
        payload["props"] = dict(props)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    if request is not None and request.META.get("REMOTE_ADDR"):
        headers["X-Forwarded-For"] = request.META["REMOTE_ADDR"]

    requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=float(getattr(settings, "ANALYTICS_TIMEOUT_SECONDS", 2)),
    ).raise_for_status()


def _send_umami_event(
    name: str,
    props: Mapping[str, str],
    *,
    request: HttpRequest | None = None,
) -> None:
    api_url = analytics_api_url()
    site_id = analytics_site_id()
    if not api_url or not site_id:
        return

    hostname = ""
    page_url = "/"
    user_agent = "FK-Cesis-MMS"
    if request is not None:
        hostname = request.get_host().split(":", 1)[0]
        page_url = request.path
        user_agent = request.META.get("HTTP_USER_AGENT", user_agent) or user_agent

    payload: dict[str, Any] = {
        "type": "event",
        "payload": {
            "website": site_id,
            "hostname": hostname,
            "language": "lv-LV",
            "url": page_url,
            "name": name,
            "data": dict(props),
        },
    }
    requests.post(
        f"{api_url}/api/send",
        json=payload,
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
        timeout=float(getattr(settings, "ANALYTICS_TIMEOUT_SECONDS", 2)),
    ).raise_for_status()

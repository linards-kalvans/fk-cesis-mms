"""Invoice Ninja self-hosted provider — HTTP transport + payload builders.

Raises the boundary exception taxonomy from
apps.integrations.invoice_platform directly (no second mapping layer).
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.utils import timezone

from apps.billing import messages
from apps.billing.services import membership_plan_product_key
from apps.integrations.invoice_platform import (
    ClientResult,
    InvoicePlatformAuthError,
    InvoicePlatformConfigError,
    InvoicePlatformNotFoundError,
    InvoicePlatformTransientError,
    InvoiceResult,
    ProductResult,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds


def _require_config() -> tuple[str, str]:
    api_url = getattr(settings, "INVOICE_NINJA_API_URL", "")
    api_key = getattr(settings, "INVOICE_NINJA_API_KEY", "")
    if not api_url or not api_key:
        raise InvoicePlatformConfigError("Invoice Ninja API URL/key not configured")
    return api_url.rstrip("/"), api_key


def _number(record, sequence: int) -> str:
    prefix = getattr(settings, "INVOICE_NINJA_NUMBER_PREFIX", "MMS") or "MMS"
    return f"{prefix}-{record.pk}-{sequence}"


def _build_line_item(record, billing_invoice) -> dict:
    notes = messages.invoice_line_label(record)
    if not record.is_full_price:
        notes = f"{notes}  {messages.sibling_discount_note(record)}"
    return {
        "product_key": membership_plan_product_key(record.plan),
        "notes": notes,
        "cost": str(billing_invoice.amount),
        "quantity": 1,
    }


def _build_invoice_body(record, billing_invoice) -> dict:
    return {
        "client_id": record.member.guardian.external_client_id,
        "number": _number(record, billing_invoice.sequence),
        "date": timezone.now().date().isoformat(),
        "due_date": billing_invoice.due_date.isoformat(),
        "line_items": [_build_line_item(record, billing_invoice)],
    }


def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    headers = {"X-Api-Token": api_key, **kwargs.pop("headers", {})}
    try:
        resp = requests.request(method, url, headers=headers, timeout=_TIMEOUT, **kwargs)
    except requests.Timeout as exc:
        raise InvoicePlatformTransientError(f"timeout: {exc}") from exc
    except requests.RequestException as exc:
        raise InvoicePlatformTransientError(f"connection error: {exc}") from exc

    status = resp.status_code
    if status in (401, 403):
        raise InvoicePlatformAuthError(f"auth failed: {status}")
    if status == 404:
        raise InvoicePlatformNotFoundError(f"not found: {url}")
    if status >= 500:
        raise InvoicePlatformTransientError(f"server error: {status}")
    return resp


def ensure_product(plan) -> ProductResult:
    api_url, api_key = _require_config()
    body = {
        "product_key": membership_plan_product_key(plan),
        "notes": messages.product_name(plan),
        "price": str(plan.annual_amount),
    }
    resp = _request("POST", f"{api_url}/products", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"product create rejected: {resp.status_code} {resp.text}")
    data = resp.json().get("data", resp.json())
    return ProductResult(external_id=str(data.get("id", "")))


def ensure_client(guardian) -> ClientResult:
    api_url, api_key = _require_config()
    body = {
        "name": guardian.full_name,
        "contacts": [{"first_name": guardian.full_name, "email": guardian.email}],
    }
    resp = _request("POST", f"{api_url}/clients", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"client create rejected: {resp.status_code} {resp.text}")
    data = resp.json().get("data", resp.json())
    return ClientResult(external_id=str(data.get("id", "")))


def _find_invoice_id_by_number(api_url: str, api_key: str, number: str) -> str:
    resp = _request("GET", f"{api_url}/invoices?number={number}", api_key)
    rows = resp.json().get("data", [])
    if rows:
        return str(rows[0].get("id", ""))
    return ""


def create_invoice(record, billing_invoice) -> InvoiceResult:
    api_url, api_key = _require_config()
    body = _build_invoice_body(record, billing_invoice)
    resp = _request("POST", f"{api_url}/invoices", api_key, json=body)
    if resp.status_code >= 400:
        # Idempotency: a duplicate invoice number means a prior attempt created
        # it but we crashed before storing the id. Recover by lookup.
        if "number" in resp.text.lower():
            existing = _find_invoice_id_by_number(api_url, api_key, body["number"])
            if existing:
                return InvoiceResult(external_id=existing)
        raise InvoicePlatformConfigError(f"invoice create rejected: {resp.status_code} {resp.text}")
    data = resp.json().get("data", resp.json())
    return InvoiceResult(external_id=str(data.get("id", "")))

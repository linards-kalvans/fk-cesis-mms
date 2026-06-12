"""Invoice Ninja self-hosted provider — HTTP transport + payload builders.

Raises the boundary exception taxonomy from
apps.integrations.invoice_platform directly (no second mapping layer).
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal

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
    PaymentResult,
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
    # Keep the line description generic. Invoice Ninja's "Update Products"
    # setting copies a line's notes onto the shared catalog product whenever
    # the line carries that product_key, so member-specific text here would
    # pollute the product. Per-member detail goes on the invoice public_notes.
    return {
        "product_key": membership_plan_product_key(record.plan),
        "notes": messages.product_name(record.plan),
        "cost": str(billing_invoice.amount),
        "quantity": 1,
    }


def _build_invoice_body(record, billing_invoice) -> dict:
    return {
        "client_id": record.member.guardian.external_client_id,
        "number": _number(record, billing_invoice.sequence),
        "date": timezone.now().date().isoformat(),
        "due_date": billing_invoice.due_date.isoformat(),
        "public_notes": messages.invoice_public_note(record),
        "line_items": [_build_line_item(record, billing_invoice)],
    }


def _unwrap(resp: requests.Response) -> dict:
    payload = resp.json()
    if isinstance(payload, dict):
        inner = payload.get("data", payload)
        return inner if isinstance(inner, dict) else {}
    return {}


def _request(method: str, url: str, api_key: str, **kwargs) -> requests.Response:
    # Invoice Ninja only returns JSON + proper HTTP status codes when the
    # request is marked as an API/XHR call. Without these headers a failed
    # request (e.g. a 422 validation error) redirects to the web app and comes
    # back as 200 + SPA HTML, which then breaks JSON parsing downstream.
    headers = {
        "X-Api-Token": api_key,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
        **kwargs.pop("headers", {}),
    }
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
    if status == 408:
        raise InvoicePlatformTransientError(f"request timeout: {status}")
    if status == 429:
        raise InvoicePlatformTransientError(f"rate limited: {status}")
    if status >= 500:
        raise InvoicePlatformTransientError(f"server error: {status}")
    return resp


def _is_deleted(row: dict) -> bool:
    """True if an Invoice Ninja row is archived or soft-deleted — such rows must
    never be reused for idempotency (their ids are invalid on new invoices)."""
    return bool(row.get("is_deleted")) or bool(row.get("archived_at"))


def _find_product_id_by_key(api_url: str, api_key: str, product_key: str) -> str:
    # Invoice Ninja's `?filter=` does a fuzzy search (it does NOT support an exact
    # `?product_key=` filter — that param is silently ignored and returns every
    # row). So narrow with `?filter=`, restrict to active records (`status=active`
    # — the default list also returns archived/soft-deleted rows, which must never
    # be reused), then verify the exact product_key client-side.
    resp = _request(
        "GET", f"{api_url}/products?filter={product_key}&status=active&per_page=100", api_key
    )
    rows = resp.json().get("data", [])
    for row in rows:
        if _is_deleted(row):
            continue
        if str(row.get("product_key", "")) == product_key:
            return str(row.get("id", ""))
    return ""


def _find_client_id_by_pk(api_url: str, api_key: str, guardian_pk: int) -> str:
    # `?custom_value1=` is ignored by Invoice Ninja (returns every client), so a
    # bare rows[0] would reuse an arbitrary/foreign client. Narrow with the fuzzy
    # `?filter=` (which DOES search custom fields), restrict to active records
    # (`status=active` excludes archived/soft-deleted), then verify custom_value1
    # equals the guardian pk exactly before reusing.
    target = str(guardian_pk)
    resp = _request(
        "GET", f"{api_url}/clients?filter={target}&status=active&per_page=100", api_key
    )
    rows = resp.json().get("data", [])
    for row in rows:
        if _is_deleted(row):
            continue
        if str(row.get("custom_value1", "")) == target:
            return str(row.get("id", ""))
    return ""


def ensure_product(plan) -> ProductResult:
    api_url, api_key = _require_config()
    product_key = membership_plan_product_key(plan)
    existing = _find_product_id_by_key(api_url, api_key, product_key)
    if existing:
        return ProductResult(external_id=existing)
    body = {
        "product_key": product_key,
        "notes": messages.product_name(plan),
        "price": str(plan.annual_amount),
    }
    resp = _request("POST", f"{api_url}/products", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"product create rejected: {resp.status_code} {resp.text}")
    data = _unwrap(resp)
    return ProductResult(external_id=str(data.get("id", "")))


def ensure_client(guardian) -> ClientResult:
    api_url, api_key = _require_config()
    existing = _find_client_id_by_pk(api_url, api_key, guardian.pk)
    if existing:
        return ClientResult(external_id=existing)
    body = {
        "name": guardian.full_name,
        "custom_value1": str(guardian.pk),
        "contacts": [{"first_name": guardian.full_name, "email": guardian.email}],
    }
    resp = _request("POST", f"{api_url}/clients", api_key, json=body)
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(f"client create rejected: {resp.status_code} {resp.text}")
    data = _unwrap(resp)
    return ClientResult(external_id=str(data.get("id", "")))


def _find_invoice_id_by_number(api_url: str, api_key: str, number: str) -> str:
    # Only recover an ACTIVE invoice with this number (a soft-deleted one must
    # not be reused), and verify the number matches exactly.
    resp = _request(
        "GET", f"{api_url}/invoices?number={number}&status=active&per_page=100", api_key
    )
    rows = resp.json().get("data", [])
    for row in rows:
        if _is_deleted(row):
            continue
        if str(row.get("number", "")) == number:
            return str(row.get("id", ""))
    return ""


def create_invoice(record, billing_invoice) -> InvoiceResult:
    api_url, api_key = _require_config()
    body = _build_invoice_body(record, billing_invoice)
    resp = _request("POST", f"{api_url}/invoices", api_key, json=body)
    if resp.status_code >= 400:
        # Idempotency: a duplicate invoice number means a prior attempt created
        # it but we crashed before storing the id. Recover by lookup. Invoice
        # Ninja reports this as a 422 with "The number has already been taken."
        if "already been taken" in resp.text.lower():
            existing = _find_invoice_id_by_number(api_url, api_key, body["number"])
            if existing:
                return InvoiceResult(external_id=existing)
        raise InvoicePlatformConfigError(f"invoice create rejected: {resp.status_code} {resp.text}")
    data = _unwrap(resp)
    return InvoiceResult(external_id=str(data.get("id", "")))


def email_invoice(external_invoice_id: str) -> None:
    """Issue + email an invoice via the v5 bulk action. Emailing a Draft in
    Invoice Ninja transitions it to Sent and sends the templated invoice email
    (PDF + payment link). Idempotent at the IN side (re-emailing a sent invoice
    just re-sends)."""
    api_url, api_key = _require_config()
    resp = _request(
        "POST",
        f"{api_url}/invoices/bulk",
        api_key,
        json={"action": "email", "ids": [external_invoice_id]},
    )
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(
            f"invoice email rejected: {resp.status_code} {resp.text}"
        )


def _to_decimal(value) -> Decimal:
    return Decimal(str(value if value not in (None, "") else "0"))


def _payment_status_from(data: dict, paid: Decimal, balance: Decimal) -> str:
    status_id = str(data.get("status_id", ""))
    if status_id == "4" or (paid > 0 and balance == 0):
        return "paid"
    if status_id == "3" or paid > 0:
        return "partial"
    return "unpaid"


def _latest_payment_date(data: dict) -> datetime.date | None:
    payments = data.get("payments") or []
    dates: list[str] = [
        str(p["date"]) for p in payments
        if isinstance(p, dict) and p.get("date")
    ]
    if not dates:
        return None
    return datetime.date.fromisoformat(max(dates))


def fetch_invoice_payment(external_invoice_id: str) -> PaymentResult:
    api_url, api_key = _require_config()
    # ?include=payments embeds the payment records so we can read the latest
    # payment date — Invoice Ninja does not embed them on the invoice by default.
    resp = _request(
        "GET", f"{api_url}/invoices/{external_invoice_id}?include=payments", api_key
    )
    if resp.status_code >= 400:
        raise InvoicePlatformConfigError(
            f"invoice fetch rejected: {resp.status_code} {resp.text}"
        )
    data = _unwrap(resp)
    amount = _to_decimal(data.get("amount"))
    paid = _to_decimal(data.get("paid_to_date"))
    balance = _to_decimal(data.get("balance"))
    return PaymentResult(
        external_invoice_id=external_invoice_id,
        payment_status=_payment_status_from(data, paid, balance),
        amount=amount,
        paid_to_date=paid,
        balance=balance,
        last_payment_date=_latest_payment_date(data),
    )
